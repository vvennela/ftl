import os
import secrets
from pathlib import Path
from dotenv import dotenv_values

SHADOW_PREFIX = "ftl_shadow_"
FTL_CREDENTIALS_FILE = Path.home() / ".ftl" / "credentials"


def load_ftl_credentials():
    """Load FTL's own credentials from ~/.ftl/credentials into os.environ.

    This file stores auth for FTL infrastructure (Anthropic key, Bedrock token, etc.)
    so users don't have to export env vars every session.
    Format: KEY=VALUE, one per line. Lines starting with # are comments.
    """
    if not FTL_CREDENTIALS_FILE.exists():
        return {}

    creds = {}
    for line in FTL_CREDENTIALS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        creds[key] = value
        # Set in os.environ so downstream code (litellm, agent auth) picks it up
        if key not in os.environ:
            os.environ[key] = value

    return creds


def save_ftl_credential(key, value):
    """Save or update a single credential in ~/.ftl/credentials."""
    FTL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FTL_CREDENTIALS_FILE.parent.chmod(0o700)

    lines = []
    found = False
    if FTL_CREDENTIALS_FILE.exists():
        for line in FTL_CREDENTIALS_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k == key:
                    lines.append(f"{key}={value}")
                    found = True
                    continue
            lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    FTL_CREDENTIALS_FILE.write_text("\n".join(lines) + "\n")
    FTL_CREDENTIALS_FILE.chmod(0o600)
    os.environ[key] = value


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

    # Everything in .env is sensitive — use python-dotenv for robust parsing
    env_file = Path(project_path) / ".env"
    if env_file.exists():
        parsed = dotenv_values(env_file)
        for key, value in parsed.items():
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
