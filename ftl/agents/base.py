from abc import ABC, abstractmethod


class Agent(ABC):
    """Base interface for coding agent adapters.

    Agents run INSIDE the sandbox. All commands execute via sandbox.exec().
    """

    @abstractmethod
    def run(self, task, workspace, sandbox):
        """Run a task inside the sandbox (first message). Returns (exit_code, stdout, stderr)."""
        pass

    @abstractmethod
    def continue_run(self, task, workspace, sandbox):
        """Continue a conversation with the agent (follow-up message).

        Returns (exit_code, stdout, stderr).
        """
        pass
