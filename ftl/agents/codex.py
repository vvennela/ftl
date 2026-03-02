import shlex
from ftl.agents.base import Agent


class CodexAgent(Agent):

    def run(self, task, workspace, sandbox, callback=None):
        escaped = shlex.quote(task)
        # --approval-mode full-auto skips all confirmation prompts inside the sandbox
        cmd = f"cd {workspace} && codex --approval-mode full-auto {escaped}"
        if callback is not None:
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None):
        # Codex has no native session-continue flag — workspace state carries context
        return self.run(task, workspace, sandbox, callback=callback)
