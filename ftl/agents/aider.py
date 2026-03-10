import shlex
from ftl.agents.base import Agent


class AiderAgent(Agent):
    supports_continue = False
    supports_structured_stream = False

    def run(self, task, workspace, sandbox, callback=None, context=None):
        escaped = shlex.quote(task)
        # --yes auto-confirms all prompts; --no-git lets FTL own the diffing
        cmd = f"cd {workspace} && aider --yes --no-git --message {escaped}"
        if callback is not None:
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None, context=None):
        # Aider writes .aider.chat.history.md to /workspace, which persists
        # within a session — subsequent messages pick up prior context automatically
        return self.run(task, workspace, sandbox, callback=callback)

    def warmup_command(self):
        return "aider --version"
