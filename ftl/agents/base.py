from abc import ABC, abstractmethod


class Agent(ABC):
    """Base interface for coding agent adapters."""

    @abstractmethod
    def run(self, task, workspace):
        """Run a task in the given workspace. Returns (exit_code, stdout, stderr)."""
        pass
