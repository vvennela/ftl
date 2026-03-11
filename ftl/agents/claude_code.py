import shlex
from ftl.agents.base import Agent

_FLAGS = "--output-format stream-json --verbose --dangerously-skip-permissions --disallowed-tools EnterPlanMode"


class ClaudeCodeAgent(Agent):
    supports_continue = True
    supports_structured_stream = True
    persistent_state_paths = ("/home/ftl/.claude/",)

    def run(self, task, workspace, sandbox, callback=None, context=None):
        escaped = shlex.quote(self.prepare_task(task))
        if callback is not None:
            cmd = f"cd {workspace} && claude -p {escaped} {_FLAGS}"
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        cmd = f"cd {workspace} && claude -p {escaped} --dangerously-skip-permissions"
        return sandbox.exec(cmd, timeout=3600)

    def continue_run(self, task, workspace, sandbox, callback=None, context=None):
        escaped = shlex.quote(task.strip())
        if callback is not None:
            cmd = f"cd {workspace} && claude -p {escaped} -c {_FLAGS}"
            return sandbox.exec_stream(cmd, callback=callback, timeout=3600)
        cmd = f"cd {workspace} && claude -p {escaped} -c --dangerously-skip-permissions"
        return sandbox.exec(cmd, timeout=3600)

    def warmup_command(self):
        return "claude --version"
