import json
from pathlib import Path

FTLCONFIG = ".ftlconfig"

REQUIRED_KEYS = {"agent", "tester"}

DEFAULT_CONFIG = {
    "planner_model": "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "agent": "claude-code",
    "tester": "bedrock/us.anthropic.claude-sonnet-4-6",
    "planner_max_steps": 20,
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
        try:
            raw = json.loads(config_path.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {config_path}: {e}")

        config = {**DEFAULT_CONFIG, **raw}

        missing = REQUIRED_KEYS - set(config.keys())
        if missing:
            raise ValueError(f"Missing required keys in .ftlconfig: {missing}")

        return config
    return DEFAULT_CONFIG.copy()


def init_config(path=None):
    """Create a .ftlconfig in the given directory."""
    target = Path(path) if path else Path.cwd()
    config_path = target / FTLCONFIG
    config_path.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
    return config_path
