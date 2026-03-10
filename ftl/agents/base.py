from abc import ABC, abstractmethod


class Agent(ABC):
    """Base interface for coding agent adapters.

    Agents run INSIDE the sandbox. All commands execute via sandbox.exec() or
    sandbox.exec_stream() (when a streaming callback is provided).
    """

    supports_continue = False
    supports_structured_stream = False
    supports_review_chat = True
    persistent_state_paths = ()

    @abstractmethod
    def run(self, task, workspace, sandbox, callback=None, context=None):
        """Run a task inside the sandbox (first message). Returns (exit_code, stdout, stderr).

        If callback is provided, output is streamed line-by-line through it.
        """
        pass

    @abstractmethod
    def continue_run(self, task, workspace, sandbox, callback=None, context=None):
        """Continue a conversation with the agent (follow-up message).

        Returns (exit_code, stdout, stderr).
        If callback is provided, output is streamed line-by-line through it.
        """
        pass

    def warmup_command(self):
        """Optional lightweight command to warm the agent runtime inside the sandbox."""
        return None

    def setup_sandbox(self, sandbox):
        """Optional post-boot sandbox initialization for agent-specific state."""
        return None
