import os
import secrets
from pathlib import Path

SHADOW_PREFIX = "ftl_shadow_"


def generate_shadow_key(name):
    """Generate a recognizable shadow key for a credential."""
    token = secrets.token_hex(8)
    return f"{SHADOW_PREFIX}{name.lower()}_{token}"


def load_real_keys(project_path, extra_vars=None):
    """Load real credentials from .env and any extra vars from os.environ.

    - .env: every key=value pair is treated as sensitive
    - extra_vars: additional env var names from .ftlconfig "shadow_env"
    """
    real_keys = {}

    # Everything in .env is sensitive
    env_file = Path(project_path) / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if value:
                real_keys[key] = value

    # Extra vars from .ftlconfig pulled from os.environ
    for key in (extra_vars or []):
        if key not in real_keys and key in os.environ:
            real_keys[key] = os.environ[key]

    return real_keys


def build_shadow_map(project_path, extra_vars=None):
    """Build a mapping of shadow keys to real keys.

    Returns:
        shadow_env: dict of {VAR_NAME: shadow_value} to inject into sandbox
        swap_table: dict of {shadow_value: real_value} for the proxy
    """
    real_keys = load_real_keys(project_path, extra_vars)

    shadow_env = {}
    swap_table = {}

    for name, real_value in real_keys.items():
        shadow_value = generate_shadow_key(name)
        shadow_env[name] = shadow_value
        swap_table[shadow_value] = real_value

    return shadow_env, swap_table
