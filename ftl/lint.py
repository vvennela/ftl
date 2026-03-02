"""Static analysis to catch credential leaks and dangerous operations in agent-generated code.

Scans diffs for:
1. Hardcoded shadow credential values (ftl_shadow_*)
2. Known credential patterns (sk_live_, sk_test_, eyJhbG, etc.)
3. Dangerous destructive operations (DROP TABLE, rm -rf, etc.) — advisory only
"""

import re
from rich.console import Console

# Matches ftl_shadow_<name>_<hex> — agent should never hardcode these
SHADOW_PATTERN = re.compile(r"ftl_shadow_\w+_[0-9a-f]{16}")

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

# Dangerous SQL operations — flag when present in added lines
# DELETE is only flagged when there's no WHERE clause (bare DELETE FROM <table>)
DANGEROUS_SQL_PATTERNS = [
    (re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),    "Dangerous SQL: DROP TABLE"),
    (re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE), "Dangerous SQL: DROP DATABASE"),
    (re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE),   "Dangerous SQL: DROP SCHEMA"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),"Dangerous SQL: TRUNCATE TABLE"),
    (re.compile(r"\bTRUNCATE\b", re.IGNORECASE),         "Dangerous SQL: TRUNCATE"),
    # DELETE FROM without WHERE anywhere on the same line
    (re.compile(r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", re.IGNORECASE),
     "Dangerous SQL: DELETE without WHERE"),
]

# Dangerous shell commands — flag when present in added lines
DANGEROUS_SHELL_PATTERNS = [
    (re.compile(r"\brm\s+.*-[a-zA-Z]*r[a-zA-Z]*f\b"),   "Dangerous shell: rm -rf"),
    (re.compile(r"\brm\s+.*-[a-zA-Z]*f[a-zA-Z]*r\b"),   "Dangerous shell: rm -fr"),
    (re.compile(r"\bshred\b"),                             "Dangerous shell: shred"),
    (re.compile(r"\bdd\b.*\bif="),                         "Dangerous shell: dd (disk write)"),
    (re.compile(r":\s*>\s*/dev/"),                         "Dangerous shell: truncating device"),
    (re.compile(r"\bchmod\s+-R\s+777\b"),                  "Dangerous shell: chmod 777 -R"),
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

            # 1. Hardcoded shadow values (ftl_shadow_* pattern or exact value)
            if SHADOW_PATTERN.search(content):
                violations.append(LintViolation(
                    path, line_num, content,
                    "Hardcoded shadow credential value"
                ))
                continue

            for sv in shadow_values:
                if sv in content:
                    violations.append(LintViolation(
                        path, line_num, content,
                        "Hardcoded shadow credential value"
                    ))
                    break
            else:
                # 2. Known hardcoded credential patterns
                for pat in CREDENTIAL_PATTERNS:
                    if pat.search(content):
                        violations.append(LintViolation(
                            path, line_num, content,
                            "Possible hardcoded credential"
                        ))
                        break

            # 3. Dangerous SQL operations (advisory)
            for pat, reason in DANGEROUS_SQL_PATTERNS:
                if pat.search(content):
                    violations.append(LintViolation(path, line_num, content, reason))
                    break

            # 4. Dangerous shell commands (advisory)
            for pat, reason in DANGEROUS_SHELL_PATTERNS:
                if pat.search(content):
                    violations.append(LintViolation(path, line_num, content, reason))
                    break

    return violations


def display_violations(violations):
    """Print violations to the terminal."""
    console = Console()

    if not violations:
        console.print("[green]Lint: clean[/green]")
        return

    cred_violations = [v for v in violations if not v.reason.startswith("Dangerous")]
    danger_violations = [v for v in violations if v.reason.startswith("Dangerous")]

    if cred_violations:
        console.print(f"\n[bold red]Credential lint: {len(cred_violations)} violation(s)[/bold red]\n")
        for v in cred_violations:
            console.print(f"  [red]{v.file_path}:{v.line_num}[/red] — {v.reason}")
            console.print(f"    [dim]{v.line_content.strip()}[/dim]")
        console.print()
        console.print(
            "[yellow]The agent wrote code that references credentials directly. "
            "Review carefully before merging.[/yellow]"
        )

    if danger_violations:
        console.print(f"\n[bold yellow]Dangerous operations: {len(danger_violations)} warning(s)[/bold yellow]\n")
        for v in danger_violations:
            console.print(f"  [yellow]{v.file_path}:{v.line_num}[/yellow] — {v.reason}")
            console.print(f"    [dim]{v.line_content.strip()}[/dim]")
        console.print()
        console.print(
            "[yellow]The agent wrote destructive operations (DROP, DELETE, rm -rf, etc.). "
            "Verify this is intentional before merging.[/yellow]"
        )
