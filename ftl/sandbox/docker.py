import atexit
import subprocess
import threading
from pathlib import Path
from ftl.sandbox.base import Sandbox

IMAGE = "ftl-sandbox:latest"
ENV_FILE = "/tmp/.ftl_env"
DEFAULT_TIMEOUT = 1800  # 30 minutes


def _check_image_exists():
    """Check if ftl-sandbox image is built."""
    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Docker image '{IMAGE}' not found. "
            f"Run 'docker build -t {IMAGE} .' in the FTL directory."
        )


class DockerSandbox(Sandbox):

    _standby_id = None
    _lock = threading.Lock()

    def __init__(self):
        self.container_id = None
        self._credentials = {}
        atexit.register(self._cleanup_on_exit)

    def boot(self, project_path, credentials=None):
        """Boot or reuse a warm container with project mounted."""
        _check_image_exists()
        project_path = str(Path(project_path).resolve())
        self._credentials = credentials or {}

        with DockerSandbox._lock:
            if DockerSandbox._standby_id and self._is_alive(DockerSandbox._standby_id):
                self.container_id = DockerSandbox._standby_id
                DockerSandbox._standby_id = None
                self._reset_workspace(project_path)
            else:
                self.container_id = self._create(project_path)

        # Write credentials to env file inside container so they persist
        if self._credentials:
            env_lines = "\n".join(f"export {k}={v}" for k, v in self._credentials.items())
            subprocess.run(
                ["docker", "exec", self.container_id, "sh", "-c",
                 f"cat > {ENV_FILE} << 'FTLEOF'\n{env_lines}\nFTLEOF"],
                capture_output=True,
            )

        return self.container_id

    def exec(self, command, timeout=DEFAULT_TIMEOUT):
        """Run a command inside the container with credentials sourced."""
        # Source env file before every command so credentials persist
        if self._credentials:
            command = f". {ENV_FILE} && {command}"

        try:
            result = subprocess.run(
                ["docker", "exec", self.container_id, "sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return 124, "", f"Command timed out after {timeout}s"

        return result.returncode, result.stdout, result.stderr

    def standby(self):
        """Put the container into standby for reuse."""
        with DockerSandbox._lock:
            DockerSandbox._standby_id = self.container_id
        self.container_id = None

    def destroy(self):
        """Kill and remove the container."""
        if self.container_id:
            subprocess.run(
                ["docker", "rm", "-f", self.container_id],
                capture_output=True,
            )
            self.container_id = None

    def _create(self, project_path):
        cmd = [
            "docker", "run", "-d",
            "--network=bridge",
            "--memory=2g",
            "--cpus=2",
            "-v", f"{project_path}:/workspace:rw",
            "-w", "/workspace",
        ]

        cmd.append(IMAGE)
        cmd.extend(["sleep", "infinity"])

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _reset_workspace(self, project_path):
        """Wipe workspace and remount fresh project state."""
        self.exec("rm -rf /workspace/*")
        subprocess.run(
            ["docker", "cp", f"{project_path}/.", f"{self.container_id}:/workspace/"],
            capture_output=True,
            check=True,
        )

    def _is_alive(self, container_id):
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and "true" in result.stdout

    def _cleanup_on_exit(self):
        """Clean up containers on process exit."""
        self.destroy()
        with DockerSandbox._lock:
            if DockerSandbox._standby_id:
                subprocess.run(
                    ["docker", "rm", "-f", DockerSandbox._standby_id],
                    capture_output=True,
                )
                DockerSandbox._standby_id = None
