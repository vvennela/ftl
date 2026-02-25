from abc import ABC, abstractmethod


class Agent(ABC):
    """Base interface for coding agent adapters.

    Agents run INSIDE the sandbox. All commands execute via sandbox.exec() or
    sandbox.exec_stream() (when a streaming callback is provided).
    """

    @abstractmethod
    def run(self, task, workspace, sandbox, callback=None):
        """Run a task inside the sandbox (first message). Returns (exit_code, stdout, stderr).

        If callback is provided, output is streamed line-by-line through it.
        """
        pass

    @abstractmethod
    def continue_run(self, task, workspace, sandbox, callback=None):
        """Continue a conversation with the agent (follow-up message).

        Returns (exit_code, stdout, stderr).
        If callback is provided, output is streamed line-by-line through it.
        """
        pass
