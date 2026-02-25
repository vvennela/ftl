"""Smoke test for CredentialSwapProxy.

Tests:
  1. HTTP  — shadow value in Authorization header is swapped to real value
  2. HTTP  — shadow value in JSON request body is swapped
  3. HTTPS — shadow value in Authorization header swapped through MITM tunnel

Run: python3 test_proxy.py
"""

import http.server
import json
import ssl
import threading
import time
import urllib.request
import urllib.error
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# ── Test credentials ──────────────────────────────────────────────────────────
SHADOW = "ftl_shadow_stripe_secret_key_deadbeef"
REAL   = "sk_live_abc123_real_key"
SWAP   = {SHADOW: REAL}

# ── Capture what the upstream server actually received ────────────────────────
received_requests = []


class _CapturingHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        received_requests.append({
            "auth":   self.headers.get("Authorization", ""),
            "body":   body.decode(),
            "path":   self.path,
        })
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')


def start_http_server(port):
    srv = http.server.HTTPServer(("127.0.0.1", port), _CapturingHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def start_https_server(port, certfile, keyfile):
    srv = http.server.HTTPServer(("127.0.0.1", port), _CapturingHandler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile, keyfile)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_proxy_opener(proxy_port):
    """Return a urllib opener that routes through the proxy."""
    proxy = urllib.request.ProxyHandler({
        "http":  f"http://127.0.0.1:{proxy_port}",
        "https": f"http://127.0.0.1:{proxy_port}",
    })
    # Accept any TLS cert (proxy presents its own)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    https_handler = urllib.request.HTTPSHandler(context=ctx)
    return urllib.request.build_opener(proxy, https_handler)


def gen_self_signed_cert():
    """Generate a self-signed cert for the local HTTPS test server."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from datetime import datetime, timedelta, timezone
    import tempfile

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_pem  = key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption())
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)

    kf = tempfile.NamedTemporaryFile(delete=False, suffix="-key.pem")
    kf.write(key_pem); kf.close()
    cf = tempfile.NamedTemporaryFile(delete=False, suffix="-cert.pem")
    cf.write(cert_pem); cf.close()
    return kf.name, cf.name, cert_pem


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_http_header_swap(proxy_port):
    """Shadow value in Authorization header → swapped to real value."""
    target_port = find_free_port()
    start_http_server(target_port)
    time.sleep(0.05)

    opener = make_proxy_opener(proxy_port)
    req = urllib.request.Request(
        f"http://127.0.0.1:{target_port}/api/charge",
        data=b"{}",
        headers={
            "Authorization": f"Bearer {SHADOW}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    opener.open(req)
    time.sleep(0.05)

    hit = received_requests[-1]
    assert REAL   in hit["auth"], f"Expected real key in Authorization, got: {hit['auth']}"
    assert SHADOW not in hit["auth"], "Shadow key leaked into Authorization header!"
    print("  [PASS] HTTP header swap")


def test_http_body_swap(proxy_port):
    """Shadow value in JSON body → swapped to real value."""
    target_port = find_free_port()
    start_http_server(target_port)
    time.sleep(0.05)

    payload = json.dumps({"api_key": SHADOW, "amount": 100}).encode()
    opener = make_proxy_opener(proxy_port)
    req = urllib.request.Request(
        f"http://127.0.0.1:{target_port}/api/charge",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener.open(req)
    time.sleep(0.05)

    hit = received_requests[-1]
    body = json.loads(hit["body"])
    assert body["api_key"] == REAL,   f"Expected real key in body, got: {body['api_key']}"
    assert SHADOW not in hit["body"], "Shadow key leaked into request body!"
    print("  [PASS] HTTP body swap")


def test_https_header_swap(proxy_port, proxy):
    """Shadow value in Authorization header → swapped through HTTPS MITM tunnel."""
    key_path, cert_path, server_cert_pem = gen_self_signed_cert()
    target_port = find_free_port()
    start_https_server(target_port, cert_path, key_path)
    time.sleep(0.1)

    # The proxy's CA cert needs to be trusted by our test opener.
    # We'll use a context that skips verification (simulating a container with
    # the CA installed). The proxy itself verifies the upstream server cert —
    # but our test server is self-signed, so we need to tell the proxy to allow it.
    # For the test, patch the proxy's upstream context to skip verification.
    from ftl.proxy import _ProxyHandler
    original_connect = _ProxyHandler.do_CONNECT

    def patched_connect(self):
        host, _, port_str = self.path.rpartition(":")
        port = int(port_str) if port_str.isdigit() else 443

        self.send_response(200, "Connection Established")
        self.end_headers()

        ssl_ctx = self._get_ssl_context(host)
        try:
            client_ssl = ssl_ctx.wrap_socket(self.connection, server_side=True)
        except ssl.SSLError:
            return

        # Connect to test server — skip verification (self-signed cert)
        import socket as _socket
        try:
            upstream_sock = _socket.create_connection((host, port), timeout=5)
            upstream_ctx = ssl.create_default_context()
            upstream_ctx.check_hostname = False
            upstream_ctx.verify_mode = ssl.CERT_NONE
            upstream_ssl = upstream_ctx.wrap_socket(upstream_sock, server_hostname=host)
        except Exception:
            client_ssl.close()
            return

        self._relay(client_ssl, upstream_ssl)

    _ProxyHandler.do_CONNECT = patched_connect

    try:
        opener = make_proxy_opener(proxy_port)
        req = urllib.request.Request(
            f"https://127.0.0.1:{target_port}/api/charge",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {SHADOW}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        opener.open(req, timeout=10)
        time.sleep(0.1)

        hit = received_requests[-1]
        assert REAL   in hit["auth"], f"Expected real key in Authorization, got: {hit['auth']}"
        assert SHADOW not in hit["auth"], "Shadow key leaked through HTTPS tunnel!"
        print("  [PASS] HTTPS header swap (MITM)")
    finally:
        _ProxyHandler.do_CONNECT = original_connect
        os.unlink(key_path)
        os.unlink(cert_path)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    from ftl.proxy import CredentialSwapProxy

    print("Starting proxy...")
    proxy = CredentialSwapProxy(SWAP)
    proxy.start()
    print(f"  Proxy on port {proxy.port}")
    time.sleep(0.1)

    print("\nRunning tests:")
    try:
        test_http_header_swap(proxy.port)
        test_http_body_swap(proxy.port)
        test_https_header_swap(proxy.port, proxy)
        print("\nAll tests passed.")
    except AssertionError as e:
        print(f"\n[FAIL] {e}")
        sys.exit(1)
    finally:
        proxy.stop()


if __name__ == "__main__":
    main()
