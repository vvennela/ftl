import json
from pathlib import Path

FTLCONFIG = ".ftlconfig"
GLOBAL_CONFIG_FILE = Path.home() / ".ftl" / "config.json"

REQUIRED_KEYS = {"agent", "tester"}

DEFAULT_CONFIG = {
    "agent": "claude-code",
    "tester": "claude-haiku-4-5-20251001",
    # Optional: "snapshot_backend": "s3", "s3_bucket": "my-ftl-snapshots"
    # Optional: "shadow_env": [], "agent_env": []
}


def load_global_config():
    """Load ~/.ftl/config.json — global defaults set by ftl setup."""
    if GLOBAL_CONFIG_FILE.exists():
        try:
            return json.loads(GLOBAL_CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_global_config(updates):
    """Merge updates into ~/.ftl/config.json."""
    existing = load_global_config()
    existing.update(updates)
    GLOBAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    GLOBAL_CONFIG_FILE.write_text(json.dumps(existing, indent=2) + "\n")


def find_config():
    """Walk up from cwd to find .ftlconfig, like git finds .git."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        config_path = parent / FTLCONFIG
        if config_path.exists():
            return config_path
    return None


def load_config():
    # Merge order: defaults → global config → project .ftlconfig
    config = {**DEFAULT_CONFIG, **load_global_config()}

    config_path = find_config()
    if config_path:
        try:
            raw = json.loads(config_path.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {config_path}: {e}")
        config.update(raw)

        missing = REQUIRED_KEYS - set(config.keys())
        if missing:
            raise ValueError(f"Missing required keys in .ftlconfig: {missing}")

    return config


def init_config(path=None, agent=None, tester=None):
    """Create a .ftlconfig in the given directory."""
    target = Path(path) if path else Path.cwd()
    config_path = target / FTLCONFIG
    global_cfg = load_global_config()
    init = {
        "agent": agent or global_cfg.get("agent") or DEFAULT_CONFIG["agent"],
        "tester": tester or global_cfg.get("tester") or DEFAULT_CONFIG["tester"],
    }
    config_path.write_text(json.dumps(init, indent=2))
    return config_path
