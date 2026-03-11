from abc import ABC, abstractmethod

_ENGINEERING_POLICY = """\
FTL engineering policy:
- Solve the task with the smallest correct change.
- Keep the diff proportional to the request; do not expand scope or refactor unrelated code.
- Prefer editing existing code over adding new files, modules, classes, or layers.
- Do not add new dependencies, helpers, or abstractions unless they are clearly necessary.
- Follow the repository's existing conventions and architecture.
- Write code that is easy for a human to read and review quickly.
- Favor simple, well-organized functions that each do one sensible thing.
- Avoid speculative future-proofing, cleanup, and aesthetic overengineering.
"""


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

    def prepare_task(self, task):
        """Apply FTL's shared engineering policy to a user task."""
        task = task.strip()
        return f"{task}\n\n{_ENGINEERING_POLICY}"
