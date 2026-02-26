import shlex
from ftl.agents.base import Agent

_FLAGS = "--output-format stream-json --verbose --dangerously-skip-permissions"


class ClaudeCodeAgent(Agent):

    def run(self, task, workspace, sandbox, callback=None):
        escaped = shlex.quote(task)
        if callback is not None:
            cmd = f"cd {workspace} && claude -p {escaped} {_FLAGS}"
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        cmd = f"cd {workspace} && claude -p {escaped} --dangerously-skip-permissions"
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None):
        escaped = shlex.quote(task)
        if callback is not None:
            cmd = f"cd {workspace} && claude -p {escaped} -c {_FLAGS}"
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        cmd = f"cd {workspace} && claude -p {escaped} -c --dangerously-skip-permissions"
        return sandbox.exec(cmd, timeout=3600)
