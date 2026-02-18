from abc import ABC, abstractmethod


class Sandbox(ABC):
    """Base interface for sandbox backends.

    Implementations: DockerSandbox (MVP), VMSandbox (future).
    """

    @abstractmethod
    def boot(self, project_path, credentials):
        """Boot the sandbox with project mounted and shadow creds injected."""
        pass

    @abstractmethod
    def exec(self, command):
        """Run a command inside the sandbox. Returns (exit_code, stdout, stderr)."""
        pass

    @abstractmethod
    def destroy(self):
        """Tear down the sandbox and clean up resources."""
        pass
