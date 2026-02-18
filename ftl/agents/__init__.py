from ftl.agents.claude_code import ClaudeCodeAgent
from ftl.agents.kiro import KiroAgent

AGENTS = {
    "claude-code": ClaudeCodeAgent,
    "kiro": KiroAgent,
}


def get_agent(name):
    if name not in AGENTS:
        raise ValueError(f"Unknown agent: {name}. Available: {list(AGENTS.keys())}")
    return AGENTS[name]()
