import shlex
from ftl.agents.base import Agent


class ClaudeCodeAgent(Agent):

    def run(self, task, workspace, sandbox, callback=None):
        escaped = shlex.quote(task)
        cmd = f'cd {workspace} && claude -p {escaped} --dangerously-skip-permissions'
        if callback is not None:
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None):
        escaped = shlex.quote(task)
        cmd = f'cd {workspace} && claude -p {escaped} -c --dangerously-skip-permissions'
        if callback is not None:
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        return sandbox.exec(cmd, timeout=3600)
