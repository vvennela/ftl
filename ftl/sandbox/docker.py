import atexit
import hashlib
import json
import subprocess
import threading
from pathlib import Path
from ftl.sandbox.base import Sandbox

try:
    import fcntl
    _FCNTL_AVAILABLE = True
except ImportError:
    _FCNTL_AVAILABLE = False  # Windows fallback — no locking

_REGISTRY = "vvenne/ftl"
AGENT_IMAGES = {
    "claude-code": f"{_REGISTRY}:latest",
    "codex":       f"{_REGISTRY}:codex",
    "aider":       f"{_REGISTRY}:aider",
}
_DEFAULT_IMAGE = f"{_REGISTRY}:latest"
ENV_FILE = "/tmp/.ftl_env"
DEFAULT_TIMEOUT = 3600  # 60 minutes (matches agent timeout)

# Python script run inside the container to compare /workspace against the snapshot.
# Uses a precomputed snapshot manifest so the hot path is one workspace walk plus
# selective reads for changed files.
_DIFF_SCRIPT_TMPL = """\
import os, json, base64
from pathlib import Path

SNAP = Path('/mnt/snapshots/{snapshot_id}')
WORK = Path('/workspace')
MANIFEST = SNAP / '.ftl_manifest'
IGNORE = {{'__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
           'node_modules', 'site-packages', 'venv', '.venv'}}
SUFFIXES = ('.dist-info', '.egg-info', '.egg-link')
SKIP_FILES = {{'_ftl_test.py', '_ftl_test.js', '.ftl_meta', '.ftl_manifest'}}

def skip(rel):
    p = Path(rel)
    if p.name in SKIP_FILES:
        return True
    for part in p.parts:
        if part in IGNORE or part.endswith(tuple(SUFFIXES)):
            return True
    return False

snap_meta = {{}}
try:
    with open(MANIFEST, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\\n')
            if not line:
                continue
            rel, size, mtime_ns = line.split('\\t')
            if skip(rel):
                continue
            snap_meta[rel] = (int(size), int(mtime_ns))
except OSError:
    print('[]')
    raise SystemExit(0)

work_meta = {{}}
for f in WORK.rglob('*'):
    if not f.is_file():
        continue
    rel = str(f.relative_to(WORK))
    if skip(rel):
        continue
    try:
        stat = f.stat()
    except OSError:
        continue
    work_meta[rel] = (stat.st_size, stat.st_mtime_ns)

results = []
for rel in sorted(snap_meta.keys() - work_meta.keys()):
    results.append({{'path': rel, 'deleted': True}})
for rel in sorted(work_meta.keys() - snap_meta.keys()):
    try:
        content = open(WORK / rel, 'rb').read()
        results.append({{'path': rel, 'deleted': False, 'exists_in_snapshot': False,
                         'content_b64': base64.b64encode(content).decode()}})
    except OSError:
        pass
for rel in sorted(snap_meta.keys() & work_meta.keys()):
    if snap_meta[rel] != work_meta[rel]:
        try:
            content = open(WORK / rel, 'rb').read()
            results.append({{'path': rel, 'deleted': False, 'exists_in_snapshot': True,
                             'content_b64': base64.b64encode(content).decode()}})
        except OSError:
            pass

print(json.dumps(results))
"""


def _container_file(project_path, image):
    """Path to the persisted container ID file for this project + image combo."""
    slug = hashlib.md5(f"{project_path}:{image}".encode()).hexdigest()[:12]
    container_dir = Path.home() / ".ftl" / "containers"
    container_dir.mkdir(parents=True, exist_ok=True)
    return container_dir / slug


def _container_lock_file(project_path, image):
    """Path to the lock file used to serialize container boot for this project."""
    slug = hashlib.md5(f"{project_path}:{image}".encode()).hexdigest()[:12]
    container_dir = Path.home() / ".ftl" / "containers"
    container_dir.mkdir(parents=True, exist_ok=True)
    return container_dir / f"{slug}.lock"


def _check_image_exists(image):
    """Check Docker is running and the required image exists locally."""
    result = subprocess.run(
        ["docker", "images", "-q", image],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Docker is not running or not installed. "
            "Start Docker Desktop and try again."
        )
    if not result.stdout.strip():
        raise RuntimeError(
            f"Docker image '{image}' not found. Run 'ftl setup' or: docker pull {image}"
        )


class DockerSandbox(Sandbox):

    _standby_id = None
    _lock = threading.Lock()

    def __init__(self, image=None, agent_name=None):
        self.image = image or _DEFAULT_IMAGE
        self.agent_name = agent_name or "claude-code"
        self.container_id = None
        self.fresh = False  # True if boot() created a new container this session
        self._credentials = {}
        self._agent_env = {}
        self._project_path = None
        atexit.register(self._cleanup_on_exit)

    def boot(self, snapshot_path, credentials=None, agent_env=None, project_path=None,
             setup_cmd=None):
        """Boot or reuse a persistent container for this project.

        Container lookup order:
          1. Disk — persisted container ID for this project path (survives process restarts)
          2. Class variable — standby from earlier in the same process (interactive shell)
          3. Create fresh

        Workspace is always reset from the snapshot before handing off to the agent.
        setup_cmd runs only on a fresh container (not on warm reuse) after env vars are written.
        """
        _check_image_exists(self.image)
        snapshot_path = Path(snapshot_path).resolve()
        snapshot_id = snapshot_path.name
        self._credentials = credentials or {}
        self._agent_env = agent_env or {}
        self._project_path = str(project_path) if project_path else None

        # 1. Check disk for a persisted container for this project.
        #    Use a file lock so two concurrent sessions for the same project
        #    can't both claim the same container (race condition).
        existing_id = None
        if self._project_path:
            cfile = _container_file(self._project_path, self.image)
            lock_path = _container_lock_file(self._project_path, self.image)
            lock_fd = open(lock_path, "w")
            try:
                if _FCNTL_AVAILABLE:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX)
                if cfile.exists():
                    stored = cfile.read_text().strip()
                    if stored and self._is_alive(stored):
                        existing_id = stored
                        # Claim it by removing the file — the next caller
                        # won't see it and will create a fresh container.
                        cfile.unlink(missing_ok=True)
                    else:
                        cfile.unlink(missing_ok=True)  # stale reference
            finally:
                if _FCNTL_AVAILABLE:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                lock_fd.close()

        # 2. Fall back to in-process standby
        if existing_id is None:
            with DockerSandbox._lock:
                if DockerSandbox._standby_id and self._is_alive(DockerSandbox._standby_id):
                    existing_id = DockerSandbox._standby_id
                    DockerSandbox._standby_id = None

        self.fresh = existing_id is None
        if existing_id:
            self.container_id = existing_id
            self._init_workspace(snapshot_id, wipe=True)
        else:
            self.container_id = self._create()
            self._init_workspace(snapshot_id, wipe=False)

        # Persist so the next `ftl code` invocation can reuse this container
        if self._project_path:
            _container_file(self._project_path, self.image).write_text(self.container_id)

        # Write all env vars to file inside container:
        # - shadow credentials (project secrets the agent sees as fake keys)
        # - agent auth (ANTHROPIC_API_KEY, etc. so the agent can call its own API)
        all_env = {**self._credentials, **self._agent_env}
        self._write_env_file(all_env)

        # Run setup command on fresh containers only — installs project deps that
        # will persist in /home/ftl/.local/ for the lifetime of this container.
        if self.fresh and setup_cmd:
            self._run_setup(setup_cmd)

        # Pre-warm the selected agent runtime in the background so first-task
        # startup cost is paid before the user sees agent output.
        threading.Thread(target=self._prewarm_agent, daemon=True).start()

        return self.container_id

    def prepare(self, snapshot_path, credentials=None, agent_env=None, setup_cmd=None):
        """Refresh the workspace and env inside an already-running container."""
        if not self.container_id:
            raise RuntimeError("Sandbox is not booted")

        snapshot_path = Path(snapshot_path).resolve()
        self._credentials = credentials or {}
        self._agent_env = agent_env or {}
        self._write_env_file({**self._credentials, **self._agent_env})
        self._init_workspace(snapshot_path.name, wipe=True)

    def _with_env(self, cmd):
        """Prepend ENV_FILE sourcing if any credentials/agent env are configured."""
        if self._credentials or self._agent_env:
            return f". {ENV_FILE} && {cmd}"
        return cmd

    def _write_env_file(self, all_env):
        env_lines = "\n".join(f"export {k}='{v}'" for k, v in all_env.items())
        subprocess.run(
            ["docker", "exec", self.container_id, "sh", "-c",
             f"cat > {ENV_FILE} << 'FTLEOF'\n{env_lines}\nFTLEOF"],
            capture_output=True,
        )

    def exec(self, command, timeout=DEFAULT_TIMEOUT):
        """Run a command inside the container with credentials sourced."""
        try:
            result = subprocess.run(
                ["docker", "exec", self.container_id, "sh", "-c", self._with_env(command)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return 124, "", f"Command timed out after {timeout}s"

        return result.returncode, result.stdout, result.stderr

    def exec_stream(self, command, callback=None, timeout=DEFAULT_TIMEOUT):
        """Run a command inside the container, streaming output line-by-line.

        Merges stderr into stdout so errors appear live. Accumulates full output
        and returns (exit_code, stdout, stderr) matching the exec() interface.
        """
        proc = subprocess.Popen(
            ["docker", "exec", self.container_id, "sh", "-c", self._with_env(command)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lines = []
        try:
            for line in proc.stdout:
                lines.append(line)
                if callback:
                    callback(line)
        except KeyboardInterrupt:
            proc.terminate()
            raise
        proc.wait()
        return proc.returncode, "".join(lines), ""

    def get_diff(self, snapshot_path):
        """Return structured diffs by comparing /workspace against the snapshot.

        The comparison runs inside the Linux VM container — no host-side Python
        walking through VirtioFS. Returns the same format as diff.compute_diff().
        """
        snapshot_id = Path(snapshot_path).name
        script = _DIFF_SCRIPT_TMPL.format(snapshot_id=snapshot_id)
        cmd = (
            f"cat > /tmp/_ftl_diff.py << 'PYEOF'\n{script}\nPYEOF\n"
            "python3 /tmp/_ftl_diff.py\n"
            "rm -f /tmp/_ftl_diff.py"
        )
        result = self.exec_as_root(cmd)
        try:
            overlay_changes = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError):
            return []

        from ftl.diff import compute_diff_from_overlay
        return compute_diff_from_overlay(overlay_changes, snapshot_path)

    def standby(self):
        """Release the container — keep it running for reuse (disk + class var)."""
        with DockerSandbox._lock:
            DockerSandbox._standby_id = self.container_id
        # Disk file already written in boot(); nothing more to do here
        self.container_id = None

    def destroy(self):
        """Kill and remove the container."""
        if self.container_id:
            subprocess.run(
                ["docker", "rm", "-f", self.container_id],
                capture_output=True,
            )
            self.container_id = None

    def _create(self):
        """Create a container with the snapshots dir bind-mounted read-only."""
        snapshots_dir = str((Path.home() / ".ftl" / "snapshots").resolve())
        Path(snapshots_dir).mkdir(parents=True, exist_ok=True)

        cmd = [
            "docker", "run", "-d",
            "--network=bridge",
            "--add-host=host.docker.internal:host-gateway",
            "--memory=2g",
            "--cpus=2",
            "-v", f"{snapshots_dir}:/mnt/snapshots:ro",
            "-w", "/workspace",
        ]
        # Mount host AWS credentials so agents that use AWS-backed auth or services can
        # authenticate without separate credential setup inside the container.
        aws_dir = Path.home() / ".aws"
        if aws_dir.is_dir():
            cmd += ["-v", f"{aws_dir}:/home/ftl/.aws:ro"]
        cmd += [self.image, "sleep", "infinity"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def exec_as_root(self, cmd):
        """Run a shell command inside the container as root."""
        return subprocess.run(
            ["docker", "exec", "-u", "root", self.container_id, "sh", "-c", cmd],
            capture_output=True,
            text=True,
        )

    def _run_setup(self, cmd):
        """Run the project setup command as the ftl user with credentials sourced."""
        result = subprocess.run(
            ["docker", "exec", "-u", "ftl", "-w", "/workspace",
             self.container_id, "sh", "-c", self._with_env(cmd)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result

    def _prewarm_agent(self):
        """Run the selected agent's lightweight warm-up command inside the sandbox."""
        from ftl.agents import get_agent

        command = get_agent(self.agent_name).warmup_command()
        if not command or not self.container_id:
            return

        subprocess.run(
            ["docker", "exec", "-u", "ftl", self.container_id, "sh", "-c", command],
            capture_output=True,
            timeout=30,
        )

    def _init_workspace(self, snapshot_id, wipe=False):
        """Populate /workspace from snapshot. If wipe=True, clears it first.

        Fast path runs as the unprivileged sandbox user so we avoid a recursive
        root-owned copy + chown on every refresh. Older containers may still
        have root-owned files, so we fall back to the original root path only if
        the user-level refresh fails.
        """
        cmds = []
        if wipe:
            cmds.append("find /workspace -mindepth 1 -delete")
        cmds.extend([
            f"cp -R /mnt/snapshots/{snapshot_id}/. /workspace/",
            "rm -f /workspace/.ftl_meta",
            "rm -f /workspace/.ftl_manifest",
        ])

        user_result = subprocess.run(
            ["docker", "exec", "-u", "ftl", "-w", "/workspace", self.container_id, "sh", "-c", "; ".join(cmds)],
            capture_output=True,
            text=True,
        )
        if user_result.returncode == 0:
            return

        root_cmds = []
        if wipe:
            root_cmds.append("find /workspace -mindepth 1 -delete")
        root_cmds.extend([
            f"cp -a /mnt/snapshots/{snapshot_id}/. /workspace/",
            "rm -f /workspace/.ftl_meta",
            "rm -f /workspace/.ftl_manifest",
            "chown -R ftl:ftl /workspace",
        ])
        root_result = self.exec_as_root("; ".join(root_cmds))
        if root_result.returncode != 0:
            raise RuntimeError(
                "Failed to initialize workspace: "
                f"{root_result.stderr or root_result.stdout or user_result.stderr or user_result.stdout}"
            )

    def _is_alive(self, container_id):
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and "true" in result.stdout

    def _cleanup_on_exit(self):
        """On process exit, leave containers running — they're reused by the next invocation.

        Only clears in-memory references; the disk file written in boot() ensures
        the container is found again even after the process restarts.
        """
        self.container_id = None
        with DockerSandbox._lock:
            DockerSandbox._standby_id = None
