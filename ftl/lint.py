"""Static analysis to catch credential leaks in agent-generated code.

Scans diffs for:
1. Hardcoded shadow credential values (ftl_shadow_*)
2. Direct credential access (os.getenv/os.environ for shadowed vars)
3. Known credential patterns (sk_live_, sk_test_, eyJhbG, etc.)
"""

import re
from rich.console import Console

# Matches ftl_shadow_<name>_<hex> — agent should never hardcode these
SHADOW_PATTERN = re.compile(r"ftl_shadow_\w+_[0-9a-f]{16}")

# Direct env access patterns — agent should use config/client, not raw access
ENV_ACCESS_PATTERNS = [
    re.compile(r"""os\.getenv\(\s*['"]({keys})['"]\s*\)"""),
    re.compile(r"""os\.environ\[['"]({keys})['"]\]"""),
    re.compile(r"""os\.environ\.get\(\s*['"]({keys})['"]\s*\)"""),
]

# Known credential prefixes/patterns that should never appear as literals
CREDENTIAL_PATTERNS = [
    re.compile(r"""['"]sk_live_[A-Za-z0-9]{20,}['"]"""),       # Stripe live
    re.compile(r"""['"]sk_test_[A-Za-z0-9]{20,}['"]"""),       # Stripe test
    re.compile(r"""['"]sk-ant-[A-Za-z0-9_\-]{20,}['"]"""),     # Anthropic
    re.compile(r"""['"]AKIA[A-Z0-9]{16}['"]"""),                # AWS access key
    re.compile(r"""['"]ghp_[A-Za-z0-9]{36,}['"]"""),            # GitHub PAT
    re.compile(r"""['"]gho_[A-Za-z0-9]{36,}['"]"""),            # GitHub OAuth
    re.compile(r"""['"]glpat-[A-Za-z0-9\-]{20,}['"]"""),       # GitLab PAT
    re.compile(r"""['"]xoxb-[A-Za-z0-9\-]{20,}['"]"""),        # Slack bot
    re.compile(r"""['"]xoxp-[A-Za-z0-9\-]{20,}['"]"""),        # Slack user
    re.compile(r"""['"]SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}['"]"""),  # SendGrid
]

# Files to skip (config, lock files, etc.)
SKIP_EXTENSIONS = {".lock", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


class LintViolation:
    def __init__(self, file_path, line_num, line_content, reason):
        self.file_path = file_path
        self.line_num = line_num
        self.line_content = line_content
        self.reason = reason

    def __str__(self):
        return f"{self.file_path}:{self.line_num} — {self.reason}"


def _build_env_patterns(shadow_keys):
    """Build regex patterns for direct access to shadowed env var names."""
    if not shadow_keys:
        return []
    keys_alt = "|".join(re.escape(k) for k in shadow_keys)
    return [
        re.compile(p.pattern.format(keys=keys_alt))
        for p in ENV_ACCESS_PATTERNS
    ]


def lint_diffs(diffs, shadow_env=None):
    """Scan added lines in diffs for credential violations.

    Args:
        diffs: list of file diffs from compute_diff()
        shadow_env: dict of {VAR_NAME: shadow_value} — the shadow credentials
                    that were injected into the sandbox

    Returns:
        list of LintViolation
    """
    violations = []
    shadow_values = set((shadow_env or {}).values())
    env_patterns = _build_env_patterns(shadow_env)

    for diff in diffs:
        path = diff["path"]

        # Skip non-code files
        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue

        line_num = 0
        for tag, content in diff["lines"]:
            if tag != "-":
                line_num += 1
            if tag != "+":
                continue

            # 1. Hardcoded shadow values
            if SHADOW_PATTERN.search(content):
                violations.append(LintViolation(
                    path, line_num, content,
                    "Hardcoded shadow credential value"
                ))
                continue

            # Also check for exact shadow values (in case format changes)
            for sv in shadow_values:
                if sv in content:
                    violations.append(LintViolation(
                        path, line_num, content,
                        "Hardcoded shadow credential value"
                    ))
                    break
            else:
                # 2. Direct env access for shadowed vars
                for pat in env_patterns:
                    if pat.search(content):
                        violations.append(LintViolation(
                            path, line_num, content,
                            "Direct credential access — use a configured client instead"
                        ))
                        break
                else:
                    # 3. Known credential patterns
                    for pat in CREDENTIAL_PATTERNS:
                        if pat.search(content):
                            violations.append(LintViolation(
                                path, line_num, content,
                                "Possible hardcoded credential"
                            ))
                            break

    return violations


def display_violations(violations):
    """Print violations to the terminal."""
    console = Console()

    if not violations:
        console.print("[green]Credential lint: clean[/green]")
        return

    console.print(f"\n[bold red]Credential lint: {len(violations)} violation(s) found[/bold red]\n")

    for v in violations:
        console.print(f"  [red]{v.file_path}:{v.line_num}[/red] — {v.reason}")
        console.print(f"    [dim]{v.line_content.strip()}[/dim]")

    console.print()
    console.print(
        "[yellow]The agent wrote code that references credentials directly. "
        "Review carefully before merging.[/yellow]"
    )
