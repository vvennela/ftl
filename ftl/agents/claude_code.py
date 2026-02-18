import subprocess
from ftl.agents.base import Agent


class ClaudeCodeAgent(Agent):

    def run(self, task, workspace):
        result = subprocess.run(
            ["claude", "-p", task, "--directory", workspace],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
