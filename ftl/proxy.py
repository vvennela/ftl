"""HTTP/HTTPS intercepting proxy that swaps shadow credentials for real ones.

When the coding agent runs user code inside the sandbox, that code makes real
API calls using shadow credentials (e.g. STRIPE_SECRET_KEY=ftl_shadow_...).
This proxy intercepts those calls and swaps in the real keys before they reach
the upstream server — so live code can run and test against real APIs while the
agent never learns the actual credentials.

Architecture:
    - HTTP requests:  proxy receives full request, swaps in headers/body, forwards
    - HTTPS requests: MITM via CONNECT tunnel with a per-host TLS leaf cert signed
                      by an ephemeral CA installed in the container trust store

Usage:
    proxy = CredentialSwapProxy(swap_table)  # {shadow_value: real_value}
    proxy.start()
    proxy.install_ca_in_container(sandbox)   # installs CA into container
    # ... agent runs, makes API calls through proxy ...
    proxy.stop()

Requires: cryptography  (pip install -e ".[proxy]")
"""

import os
import select
import socket
import ssl
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_CONNECT_TIMEOUT = 30
_RELAY_TIMEOUT = 120


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _generate_ca():
    """Generate an ephemeral CA certificate + private key. Returns (key, cert)."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        raise RuntimeError(
            "cryptography is required for the network proxy. "
            "Install with: pip install -e '.[proxy]'"
        )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "FTL Proxy CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FTL"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


def _generate_leaf_cert(hostname, ca_key_pem, ca_cert_pem):
    """Generate a per-hostname leaf cert signed by the CA. Returns (key_pem, cert_pem)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.x509 import load_pem_x509_certificate
    from cryptography.x509.oid import NameOID

    ca_key = load_pem_private_key(ca_key_pem, password=None)
    ca_cert = load_pem_x509_certificate(ca_cert_pem)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)

    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=1))
    )
    try:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(hostname)]),
            critical=False,
        )
    except Exception:
        pass

    cert = builder.sign(ca_key, hashes.SHA256())

    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    return key_pem, cert_pem


class _ProxyHandler(BaseHTTPRequestHandler):
    """Request handler for the intercepting proxy."""

    def log_message(self, fmt, *args):
        pass  # suppress default stdout access log

    def _swap(self, data: bytes) -> bytes:
        """Replace shadow credential bytes with real credential bytes."""
        for shadow, real in self.server.swap_table.items():
            if shadow.encode() in data:
                data = data.replace(shadow.encode(), real.encode())
        return data

    def _swap_str(self, s: str) -> str:
        for shadow, real in self.server.swap_table.items():
            if shadow in s:
                s = s.replace(shadow, real)
        return s

    # ------------------------------------------------------------------
    # HTTPS (CONNECT)
    # ------------------------------------------------------------------

    def do_CONNECT(self):
        """Handle HTTPS CONNECT: perform MITM, swap credentials in the tunnel."""
        host, _, port_str = self.path.rpartition(":")
        port = int(port_str) if port_str.isdigit() else 443

        # Tell the client the tunnel is open
        self.send_response(200, "Connection Established")
        self.end_headers()

        # Build (or reuse) an SSL context for this hostname
        ssl_ctx = self._get_ssl_context(host)

        try:
            # Wrap the client-side connection with our fake cert
            client_ssl = ssl_ctx.wrap_socket(self.connection, server_side=True)
        except ssl.SSLError:
            return

        # Connect to the real upstream server
        try:
            upstream_sock = socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT)
            upstream_ssl = ssl.create_default_context().wrap_socket(
                upstream_sock, server_hostname=host
            )
        except (socket.error, ssl.SSLError):
            client_ssl.close()
            return

        self._relay(client_ssl, upstream_ssl)

    def _get_ssl_context(self, hostname):
        with self.server.ssl_ctx_lock:
            if hostname in self.server.ssl_ctx_cache:
                return self.server.ssl_ctx_cache[hostname]

        key_pem, cert_pem = _generate_leaf_cert(
            hostname,
            self.server.ca_key_pem,
            self.server.ca_cert_pem,
        )

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

        # Write combined PEM to a temp file, load it, then delete
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".pem", delete=False
        ) as tf:
            tf.write(key_pem + cert_pem)
            tmp_path = tf.name
        try:
            ctx.load_cert_chain(tmp_path)
        finally:
            os.unlink(tmp_path)

        with self.server.ssl_ctx_lock:
            self.server.ssl_ctx_cache[hostname] = ctx
        return ctx

    def _relay(self, client, upstream):
        """Relay bytes between client and upstream with credential swapping on client→upstream."""
        try:
            while True:
                r, _, _ = select.select([client, upstream], [], [], _RELAY_TIMEOUT)
                if not r:
                    break
                for sock in r:
                    try:
                        data = sock.recv(65536)
                    except (ssl.SSLError, OSError):
                        return
                    if not data:
                        return
                    if sock is client:
                        data = self._swap(data)
                        try:
                            upstream.sendall(data)
                        except OSError:
                            return
                    else:
                        try:
                            client.sendall(data)
                        except OSError:
                            return
        except Exception:
            pass
        finally:
            for s in (client, upstream):
                try:
                    s.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # HTTP (plain)
    # ------------------------------------------------------------------

    def _forward(self):
        """Forward a plain HTTP request, swapping credentials in headers and body."""
        host = self.headers.get("Host", "")
        path = self.path
        if not path.startswith("http"):
            path = f"http://{host}{path}"

        body = b""
        content_len = self.headers.get("Content-Length")
        if content_len:
            body = self.rfile.read(int(content_len))
        body = self._swap(body)

        # Swap in headers
        headers = {}
        for k, v in self.headers.items():
            if k.lower() in ("host", "proxy-connection", "connection", "content-length"):
                continue
            headers[k] = self._swap_str(v)

        # Add correct Content-Length after swap (length may change)
        if body:
            headers["Content-Length"] = str(len(body))

        req = urllib.request.Request(
            path,
            data=body or None,
            headers=headers,
            method=self.command,
        )
        try:
            with urllib.request.urlopen(req, timeout=_CONNECT_TIMEOUT) as resp:
                self.send_response(resp.status)
                for k, v in resp.headers.items():
                    if k.lower() not in ("transfer-encoding",):
                        self.send_header(k, v)
                self.end_headers()
                self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            self.end_headers()
            try:
                self.wfile.write(e.read())
            except Exception:
                pass
        except Exception as e:
            self.send_error(502, str(e))

    do_GET = _forward
    do_POST = _forward
    do_PUT = _forward
    do_DELETE = _forward
    do_PATCH = _forward
    do_HEAD = _forward
    do_OPTIONS = _forward


class _ProxyServer(HTTPServer):
    def __init__(self, *args, swap_table, ca_key_pem, ca_cert_pem, **kwargs):
        super().__init__(*args, **kwargs)
        self.swap_table = swap_table
        self.ca_key_pem = ca_key_pem
        self.ca_cert_pem = ca_cert_pem
        self.ssl_ctx_cache = {}
        self.ssl_ctx_lock = threading.Lock()

    def handle_error(self, request, client_address):
        pass  # swallow connection errors silently


class CredentialSwapProxy:
    """Threaded HTTP/HTTPS intercepting proxy that swaps shadow credentials for real ones.

    Generates an ephemeral CA on creation. Call install_ca_in_container() after
    boot() so the container trusts the proxy's TLS certificates.
    """

    def __init__(self, swap_table):
        """
        Args:
            swap_table: dict mapping shadow_value → real_value
                        (second return value of build_shadow_map())
        """
        self.swap_table = swap_table
        self.port = _find_free_port()
        self.ca_key_pem, self.ca_cert_pem = _generate_ca()
        self._server = None
        self._thread = None

    @property
    def url(self):
        """Proxy URL as seen from inside Docker (host.docker.internal resolves to host)."""
        return f"http://host.docker.internal:{self.port}"

    def start(self):
        """Start the proxy server in a background daemon thread."""
        self._server = _ProxyServer(
            ("127.0.0.1", self.port),
            _ProxyHandler,
            swap_table=self.swap_table,
            ca_key_pem=self.ca_key_pem,
            ca_cert_pem=self.ca_cert_pem,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="ftl-proxy",
        )
        self._thread.start()

    def stop(self):
        """Shut down the proxy server."""
        if self._server:
            self._server.shutdown()
            self._server = None

    def install_ca_in_container(self, sandbox):
        """Install the proxy's CA certificate into the container's trust store.

        Must be called after sandbox.boot() and before the agent runs.
        Requires root exec capability on the sandbox.
        """
        import base64
        # Base64-encode the cert to avoid shell quoting/newline issues
        cert_b64 = base64.b64encode(self.ca_cert_pem).decode()
        cmds = (
            f"echo '{cert_b64}' | base64 -d"
            f" > /usr/local/share/ca-certificates/ftl-proxy.crt"
            f" && update-ca-certificates"
        )
        sandbox.exec_as_root(cmds)

    def env_vars(self):
        """Return env vars to inject into the container for proxy routing."""
        return {
            "HTTP_PROXY": self.url,
            "HTTPS_PROXY": self.url,
            "http_proxy": self.url,
            "https_proxy": self.url,
            # Don't proxy localhost or the agent's own API calls
            "NO_PROXY": "localhost,127.0.0.1,::1",
            "no_proxy": "localhost,127.0.0.1,::1",
        }
