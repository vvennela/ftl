import subprocess
from pathlib import Path
from ftl.sandbox.base import Sandbox

IMAGE = "ftl-sandbox:latest"


class DockerSandbox(Sandbox):

    _standby_id = None

    def __init__(self):
        self.container_id = None

    def boot(self, project_path, credentials=None):
        """Boot or reuse a warm container with project mounted."""
        project_path = str(Path(project_path).resolve())

        if DockerSandbox._standby_id and self._is_alive(DockerSandbox._standby_id):
            self.container_id = DockerSandbox._standby_id
            DockerSandbox._standby_id = None
            self._reset_workspace(project_path, credentials)
        else:
            self.container_id = self._create(project_path, credentials)

        return self.container_id

    def exec(self, command):
        """Run a command inside the container."""
        result = subprocess.run(
            ["docker", "exec", self.container_id, "sh", "-c", command],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def standby(self):
        """Put the container into standby for reuse."""
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

    def _create(self, project_path, credentials=None):
        cmd = [
            "docker", "run", "-d",
            "--network=bridge",
            "-v", f"{project_path}:/workspace:rw",
            "-w", "/workspace",
        ]

        for key, value in (credentials or {}).items():
            cmd.extend(["-e", f"{key}={value}"])

        cmd.append(IMAGE)
        cmd.extend(["sleep", "infinity"])

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def _reset_workspace(self, project_path, credentials=None):
        """Wipe workspace and remount fresh project state."""
        self.exec("rm -rf /workspace/*")
        subprocess.run(
            ["docker", "cp", f"{project_path}/.", f"{self.container_id}:/workspace/"],
            capture_output=True,
            check=True,
        )
        for key, value in (credentials or {}).items():
            subprocess.run(
                ["docker", "exec", self.container_id, "sh", "-c", f"export {key}={value}"],
                capture_output=True,
            )

    def _is_alive(self, container_id):
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_id],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and "true" in result.stdout
