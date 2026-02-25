from abc import ABC, abstractmethod


class Sandbox(ABC):
    """Base interface for sandbox backends.

    Implementations: DockerSandbox (MVP), VMSandbox (future).
    """

    @abstractmethod
    def boot(self, snapshot_path, credentials=None, agent_env=None, project_path=None):
        """Boot the sandbox, reusing a persistent container for this project if available.

        Args:
            snapshot_path: Path to the project snapshot to load into the workspace.
            credentials: Shadow credential env vars for the user's project secrets.
            agent_env: Auth env vars for the agent itself (e.g., ANTHROPIC_API_KEY).
            project_path: Project directory path, used to key the persistent container.
        """
        pass

    @abstractmethod
    def exec(self, command, timeout=1800):
        """Run a command inside the sandbox. Returns (exit_code, stdout, stderr)."""
        pass

    @abstractmethod
    def exec_stream(self, command, callback=None, timeout=1800):
        """Run a command, streaming output line-by-line through callback.

        Returns (exit_code, stdout, stderr) where stdout is the accumulated full output.
        """
        pass

    @abstractmethod
    def destroy(self):
        """Tear down the sandbox and clean up resources."""
        pass
