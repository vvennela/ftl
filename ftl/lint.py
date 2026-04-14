"""Static analysis for credentials and destructive operations in generated code."""

import ast
import re
from pathlib import Path
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

_DANGEROUS_SQL_REASONS = [
    (re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "Destructive SQL: DROP TABLE"),
    (re.compile(r"\bDROP\s+DATABASE\b", re.IGNORECASE), "Destructive SQL: DROP DATABASE"),
    (re.compile(r"\bDROP\s+SCHEMA\b", re.IGNORECASE), "Destructive SQL: DROP SCHEMA"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE), "Destructive SQL: TRUNCATE TABLE"),
    (re.compile(r"\bTRUNCATE\b", re.IGNORECASE), "Destructive SQL: TRUNCATE"),
    (re.compile(r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", re.IGNORECASE), "Destructive SQL: DELETE without WHERE"),
]

_DANGEROUS_SHELL_REASONS = [
    (re.compile(r"\brm\s+.*-[a-zA-Z]*r[a-zA-Z]*f\b"), "Destructive shell: rm -rf"),
    (re.compile(r"\brm\s+.*-[a-zA-Z]*f[a-zA-Z]*r\b"), "Destructive shell: rm -fr"),
    (re.compile(r"\bshred\b"), "Destructive shell: shred"),
    (re.compile(r"\bdd\b.*\bif="), "Destructive shell: dd (disk write)"),
    (re.compile(r":\s*>\s*/dev/"), "Destructive shell: truncating device"),
]

_SQL_ALLOW_PATTERNS = [
    re.compile(r"\b(drop|truncate|delete|purge|wipe|remove)\b.*\b(table|tables|row|rows|record|records|data|database|schema)\b", re.IGNORECASE),
    re.compile(r"\b(clean up|cleanup)\b.*\b(table|tables|row|rows|record|records|data|database|schema)\b", re.IGNORECASE),
]

_FILE_ALLOW_PATTERNS = [
    re.compile(r"\b(delete|remove|unlink|truncate|purge|wipe|clear)\b.*\b(file|files|folder|folders|directory|directories|cache|caches|log|logs|temp|tmp|artifact|artifacts)\b", re.IGNORECASE),
    re.compile(r"\b(clean up|cleanup)\b.*\b(file|files|folder|folders|directory|directories|cache|caches|log|logs|temp|tmp|artifact|artifacts)\b", re.IGNORECASE),
]

_EXECUTE_METHODS = {"execute", "executemany", "executescript"}
_SUBPROCESS_FUNCS = {
    "os.system",
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
}
_JS_SQL_CALLS = {"query", "execute", "run", "exec"}
_JS_FS_DELETE_PATTERNS = [
    (re.compile(r"\bfs\.(unlink|unlinkSync|rm|rmSync|rmdir|rmdirSync)\s*\("), "Destructive filesystem delete: fs API"),
    (re.compile(r"\b\w+\.unlink\s*\("), "Destructive filesystem delete: fs/promises unlink"),
    (re.compile(r"\b\w+\.rm\s*\("), "Destructive filesystem delete: fs/promises rm"),
    (re.compile(r"\b\w+\.rmdir\s*\("), "Destructive filesystem delete: fs/promises rmdir"),
    (re.compile(r"\brimraf\s*\("), "Destructive filesystem delete: rimraf"),
]
_GO_FILE_DELETE_PATTERNS = [
    (re.compile(r"\bos\.(Remove|RemoveAll)\s*\("), "Destructive filesystem delete: Go os.Remove"),
]
_JAVA_FILE_DELETE_PATTERNS = [
    (re.compile(r"\bFiles\.delete(?:IfExists)?\s*\("), "Destructive filesystem delete: Java Files.delete"),
    (re.compile(r"\b\w+\.delete\s*\("), "Destructive filesystem delete: Java File.delete"),
]
_CPP_FILE_DELETE_PATTERNS = [
    (re.compile(r"\bstd::filesystem::remove(?:_all)?\s*\("), "Destructive filesystem delete: C++ filesystem remove"),
]
_FILE_DELETE_FUNCS = {
    "os.remove": "Destructive filesystem delete: os.remove",
    "os.unlink": "Destructive filesystem delete: os.unlink",
    "os.rmdir": "Destructive filesystem delete: os.rmdir",
    "shutil.rmtree": "Destructive filesystem delete: shutil.rmtree",
}

# Files to skip (config, lock files, etc.)
SKIP_EXTENSIONS = {".lock", ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini"}


class LintViolation:
    def __init__(self, file_path, line_num, line_content, reason, severity="warn", blocking=False):
        self.file_path = file_path
        self.line_num = line_num
        self.line_content = line_content
        self.reason = reason
        self.severity = severity
        self.blocking = blocking

    def __str__(self):
        return f"{self.file_path}:{self.line_num} — {self.reason}"


def _task_allows_destructive(task, category):
    task = (task or "").strip()
    if not task:
        return False
    patterns = _SQL_ALLOW_PATTERNS if category == "sql" else _FILE_ALLOW_PATTERNS
    return any(p.search(task) for p in patterns)


def _find_reason(text, patterns):
    for pat, reason in patterns:
        if pat.search(text):
            return reason
    return None


def _new_file_text(diff):
    if "_content_bytes" in diff:
        return diff["_content_bytes"].decode(errors="replace")
    return "\n".join(content for tag, content in diff["lines"] if tag != "-")


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _sql_reason(text):
    return _find_reason(text, _DANGEROUS_SQL_REASONS)


def _shell_reason(text):
    return _find_reason(text, _DANGEROUS_SHELL_REASONS)


class _PythonDangerVisitor(ast.NodeVisitor):
    def __init__(self, file_path, source, task):
        self.file_path = file_path
        self.source = source
        self.task = task
        self.violations = []

    def _add(self, node, reason, category):
        allowed = _task_allows_destructive(self.task, category)
        severity = "warn" if allowed else "block"
        line = ast.get_source_segment(self.source, node) or ""
        self.violations.append(
            LintViolation(
                self.file_path,
                getattr(node, "lineno", 1),
                line.strip(),
                reason,
                severity=severity,
                blocking=not allowed,
            )
        )

    def visit_Call(self, node):
        name = _call_name(node.func)

        if name in _FILE_DELETE_FUNCS:
            self._add(node, _FILE_DELETE_FUNCS[name], "file")
        elif name == "unlink" or name.endswith(".unlink"):
            self._add(node, "Destructive filesystem delete: Path.unlink", "file")
        elif name == "rmdir" or name.endswith(".rmdir"):
            self._add(node, "Destructive filesystem delete: Path.rmdir", "file")
        elif name == "rmtree" or name.endswith(".rmtree"):
            self._add(node, "Destructive filesystem delete: shutil.rmtree", "file")

        if isinstance(node.func, ast.Attribute) and node.func.attr in _EXECUTE_METHODS and node.args:
            sql_text = _literal_text(node.args[0])
            if sql_text:
                reason = _sql_reason(sql_text)
                if reason:
                    self._add(node, reason, "sql")

        if name in _SUBPROCESS_FUNCS and node.args:
            shell_text = _literal_text(node.args[0])
            if shell_text:
                reason = _shell_reason(shell_text)
                if reason:
                    self._add(node, reason, "file")

        self.generic_visit(node)


def _literal_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{expr}")
        return "".join(parts)
    return None


def _ast_destructive_violations(diff, task):
    path = diff["path"]
    if not path.endswith(".py"):
        return []
    try:
        source = _new_file_text(diff)
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = _PythonDangerVisitor(path, source, task)
    visitor.visit(tree)
    return visitor.violations


def _line_based_destructive_violations(diff, task):
    violations = []
    path = diff["path"]
    line_num = 0

    for tag, content in diff["lines"]:
        if tag != "-":
            line_num += 1
        if tag != "+":
            continue

        sql_reason = _sql_reason(content)
        if sql_reason:
            allowed = _task_allows_destructive(task, "sql")
            violations.append(
                LintViolation(
                    path,
                    line_num,
                    content,
                    sql_reason,
                    severity="warn" if allowed else "block",
                    blocking=not allowed,
                )
            )
            continue

        shell_reason = _shell_reason(content)
        if shell_reason:
            allowed = _task_allows_destructive(task, "file")
            violations.append(
                LintViolation(
                    path,
                    line_num,
                    content,
                    shell_reason,
                    severity="warn" if allowed else "block",
                    blocking=not allowed,
                )
            )

    return violations


def _js_ts_destructive_violations(diff, task):
    path = diff["path"]
    if not path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
        return []

    source = _new_file_text(diff)
    violations = []
    seen = set()
    lines = source.splitlines()

    for match, reason in _JS_FS_DELETE_PATTERNS:
        for found in match.finditer(source):
            line_num = source[:found.start()].count("\n") + 1
            if ("file", line_num) in seen:
                continue
            seen.add(("file", line_num))
            line = lines[line_num - 1] if lines else ""
            allowed = _task_allows_destructive(task, "file")
            violations.append(
                LintViolation(
                    path,
                    line_num,
                    line,
                    reason,
                    severity="warn" if allowed else "block",
                    blocking=not allowed,
                )
            )

    for line_num, line in enumerate(lines, start=1):
        if not any(f".{name}(" in line for name in _JS_SQL_CALLS):
            continue
        sql_reason = _sql_reason(line)
        if not sql_reason:
            continue
        if ("sql", line_num) in seen:
            continue
        seen.add(("sql", line_num))
        allowed = _task_allows_destructive(task, "sql")
        violations.append(
            LintViolation(
                path,
                line_num,
                line,
                sql_reason,
                severity="warn" if allowed else "block",
                blocking=not allowed,
            )
        )

    return violations


def _go_java_cpp_destructive_violations(diff, task):
    path = diff["path"]
    ext = Path(path).suffix.lower()
    patterns = {
        ".go": _GO_FILE_DELETE_PATTERNS,
        ".java": _JAVA_FILE_DELETE_PATTERNS,
        ".cc": _CPP_FILE_DELETE_PATTERNS,
        ".cpp": _CPP_FILE_DELETE_PATTERNS,
        ".cxx": _CPP_FILE_DELETE_PATTERNS,
        ".hpp": _CPP_FILE_DELETE_PATTERNS,
        ".h": _CPP_FILE_DELETE_PATTERNS,
    }.get(ext)
    if not patterns:
        return []

    source = _new_file_text(diff)
    violations = []
    lines = source.splitlines()
    seen = set()

    for match, reason in patterns:
        for found in match.finditer(source):
            line_num = source[:found.start()].count("\n") + 1
            if line_num in seen:
                continue
            seen.add(line_num)
            line = lines[line_num - 1] if lines else ""
            allowed = _task_allows_destructive(task, "file")
            violations.append(
                LintViolation(
                    path,
                    line_num,
                    line,
                    reason,
                    severity="warn" if allowed else "block",
                    blocking=not allowed,
                )
            )

    return violations


def lint_diffs(diffs, shadow_env=None, task=""):
    """Scan diffs for credential leaks and destructive operations."""
    violations = []
    shadow_values = set((shadow_env or {}).values())

    for diff in diffs:
        path = diff["path"]

        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue

        line_num = 0
        for tag, content in diff["lines"]:
            if tag != "-":
                line_num += 1
            if tag != "+":
                continue

            if SHADOW_PATTERN.search(content):
                violations.append(
                    LintViolation(
                        path,
                        line_num,
                        content,
                        "Hardcoded shadow credential value",
                        severity="warn",
                    )
                )
                continue

            for sv in shadow_values:
                if sv in content:
                    violations.append(
                        LintViolation(
                            path,
                            line_num,
                            content,
                            "Hardcoded shadow credential value",
                            severity="warn",
                        )
                    )
                    break
            else:
                for pat in CREDENTIAL_PATTERNS:
                    if pat.search(content):
                        violations.append(
                            LintViolation(
                                path,
                                line_num,
                                content,
                                "Possible hardcoded credential",
                                severity="warn",
                            )
                        )
                        break

        violations.extend(_ast_destructive_violations(diff, task))
        violations.extend(_js_ts_destructive_violations(diff, task))
        violations.extend(_go_java_cpp_destructive_violations(diff, task))
        if not path.endswith(".py") and not path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
            violations.extend(_line_based_destructive_violations(diff, task))

    return violations


def display_violations(violations):
    """Print violations to the terminal."""
    console = Console()

    if not violations:
        console.print("[green]Lint: clean[/green]")
        return

    blocked = [v for v in violations if v.blocking]
    warnings = [v for v in violations if not v.blocking]
    cred_warnings = [v for v in warnings if "credential" in v.reason.lower()]
    destructive_warnings = [v for v in warnings if "Destructive" in v.reason]

    if blocked:
        console.print(f"\n[bold red]Blocked destructive operations: {len(blocked)}[/bold red]\n")
        for v in blocked:
            console.print(f"  [red]{v.file_path}:{v.line_num}[/red] — {v.reason}")
            if v.line_content:
                console.print(f"    [dim]{v.line_content.strip()}[/dim]")
        console.print()
        console.print(
            "[red]These changes perform destructive deletes/drops/truncates that were not requested in the task. "
            "FTL will block merge unless the task explicitly asks for them.[/red]"
        )

    if cred_warnings:
        console.print(f"\n[bold red]Credential lint: {len(cred_warnings)} warning(s)[/bold red]\n")
        for v in cred_warnings:
            console.print(f"  [red]{v.file_path}:{v.line_num}[/red] — {v.reason}")
            console.print(f"    [dim]{v.line_content.strip()}[/dim]")
        console.print()
        console.print(
            "[yellow]The agent wrote code that references credentials directly. "
            "Review carefully before merging.[/yellow]"
        )

    if destructive_warnings:
        console.print(f"\n[bold yellow]Allowed destructive operations: {len(destructive_warnings)} warning(s)[/bold yellow]\n")
        for v in destructive_warnings:
            console.print(f"  [yellow]{v.file_path}:{v.line_num}[/yellow] — {v.reason}")
            if v.line_content:
                console.print(f"    [dim]{v.line_content.strip()}[/dim]")
        console.print()
        console.print(
            "[yellow]The task appears to request destructive behavior. Verify the scope carefully before merging.[/yellow]"
        )
