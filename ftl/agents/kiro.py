import shlex
from ftl.agents.base import Agent


class KiroAgent(Agent):

    def run(self, task, workspace, sandbox, callback=None):
        escaped = shlex.quote(task)
        cmd = f'cd {workspace} && kiro-cli chat --message {escaped}'
        if callback is not None:
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None):
        # Kiro doesn't have a -c equivalent yet — send as new message
        # The workspace state carries context (agent sees its own previous changes)
        return self.run(task, workspace, sandbox, callback=callback)
