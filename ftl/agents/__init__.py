from ftl.agents.claude_code import ClaudeCodeAgent
from ftl.agents.kiro import KiroAgent
from ftl.agents.codex import CodexAgent
from ftl.agents.aider import AiderAgent

AGENTS = {
    "claude-code": ClaudeCodeAgent,
    "kiro": KiroAgent,
    "codex": CodexAgent,
    "aider": AiderAgent,
}


def get_agent(name):
    if name not in AGENTS:
        raise ValueError(f"Unknown agent: {name}. Available: {list(AGENTS.keys())}")
    return AGENTS[name]()
