from abc import ABC, abstractmethod


class Sandbox(ABC):
    """Base interface for sandbox backends.

    Implementations: DockerSandbox (MVP), VMSandbox (future).
    """

    @abstractmethod
    def boot(self, project_path, credentials=None, agent_env=None):
        """Boot the sandbox with project mounted, shadow creds, and agent auth injected.

        Args:
            project_path: Path to the workspace to mount.
            credentials: Shadow credential env vars for the user's project secrets.
            agent_env: Auth env vars for the agent itself (e.g., ANTHROPIC_API_KEY).
        """
        pass

    @abstractmethod
    def exec(self, command):
        """Run a command inside the sandbox. Returns (exit_code, stdout, stderr)."""
        pass

    @abstractmethod
    def destroy(self):
        """Tear down the sandbox and clean up resources."""
        pass
