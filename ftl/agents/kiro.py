from ftl.agents.base import Agent

_NOT_SUPPORTED_MSG = """\
Kiro is not supported as a headless agent.

kiro-cli requires a PTY daemon (kiro-cli-term) to be running in the terminal
session before `kiro-cli chat` can connect. This daemon is not compatible with
FTL's non-interactive docker exec model.

Use a supported agent instead:
  ftl config  # set agent to claude-code, codex, or aider
"""


class KiroAgent(Agent):

    def run(self, task, workspace, sandbox, callback=None, context=None):
        raise RuntimeError(_NOT_SUPPORTED_MSG)

    def continue_run(self, task, workspace, sandbox, callback=None, context=None):
        raise RuntimeError(_NOT_SUPPORTED_MSG)
