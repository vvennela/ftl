import subprocess
from ftl.agents.base import Agent


class KiroAgent(Agent):

    def run(self, task, workspace):
        result = subprocess.run(
            ["kiro-cli", "chat", "--message", task, "--directory", workspace],
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr
