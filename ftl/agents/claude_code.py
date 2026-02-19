import shlex
from ftl.agents.base import Agent


class ClaudeCodeAgent(Agent):

    def run(self, task, workspace, sandbox):
        escaped = shlex.quote(task)
        return sandbox.exec(
            f'cd {workspace} && claude -p {escaped} --dangerously-skip-permissions',
            timeout=3600,
        )

    def continue_run(self, task, workspace, sandbox):
        escaped = shlex.quote(task)
        return sandbox.exec(
            f'cd {workspace} && claude -p {escaped} -c --dangerously-skip-permissions',
            timeout=3600,
        )
