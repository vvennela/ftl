import shlex
from ftl.agents.base import Agent


class KiroAgent(Agent):

    def run(self, task, workspace, sandbox):
        escaped = shlex.quote(task)
        return sandbox.exec(
            f'cd {workspace} && kiro-cli chat --message {escaped}',
            timeout=3600,
        )

    def continue_run(self, task, workspace, sandbox):
        # Kiro doesn't have a -c equivalent yet — send as new message
        # The workspace state carries context (agent sees its own previous changes)
        return self.run(task, workspace, sandbox)
