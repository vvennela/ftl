import json
from pathlib import Path

FTLCONFIG = ".ftlconfig"

DEFAULT_CONFIG = {
    "planner_model": "bedrock/amazon.nova-lite-v1:0",
    "agent": "claude-code",
    "tester": "bedrock/deepseek-r1",
}


def find_config():
    """Walk up from cwd to find .ftlconfig, like git finds .git."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        config_path = parent / FTLCONFIG
        if config_path.exists():
            return config_path
    return None


def load_config():
    config_path = find_config()
    if config_path:
        return {**DEFAULT_CONFIG, **json.loads(config_path.read_text())}
    return DEFAULT_CONFIG.copy()


def init_config(path=None):
    """Create a .ftlconfig in the given directory."""
    target = Path(path) if path else Path.cwd()
    config_path = target / FTLCONFIG
    config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
    return config_path
