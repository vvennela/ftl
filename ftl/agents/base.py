from abc import ABC, abstractmethod

_COMMUNICATION_POLICY = """\
FTL communication policy:
- Use direct, high-signal language. No filler, pleasantries, or repeated framing.
- Lead with the answer, bug, or decision. Keep explanations short unless detail is necessary.
- Preserve exact technical terms, code, commands, paths, versions, and errors.
- Prefer concise bullets over long paragraphs when they are easier to scan.
"""

_ENGINEERING_POLICY = """\
FTL engineering policy:
- Solve the task with the smallest correct change.
- Keep the diff proportional to the request; do not expand scope or refactor unrelated code.
- Prefer editing existing code over adding new files, modules, classes, or layers.
- Do not add new dependencies, helpers, or abstractions unless they are clearly necessary.
- Follow the repository's existing conventions and architecture.
- Write code that is easy for a human to read and review quickly.
- Favor simple, well-organized functions that each do one sensible thing.
- Prefer modular code with clear responsibilities, explicit names, and straightforward control flow.
- Minimize hidden side effects and keep related logic close together.
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
        return f"{task}\n\n{_COMMUNICATION_POLICY}\n{_ENGINEERING_POLICY}"
