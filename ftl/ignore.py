from pathlib import Path

ALWAYS_IGNORE = {
    "node_modules",
    ".git",
    "__pycache__",
    ".env",
    "venv",
    ".venv",
    "dist",
    "build",
    ".next",
    ".ftl",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "coverage",
    "htmlcov",
}


def load_ftlignore(project_path):
    """Load additional ignore patterns from .ftlignore."""
    ignore_file = Path(project_path) / ".ftlignore"
    if not ignore_file.exists():
        return set()
    patterns = set()
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.add(line)
    return patterns


def get_ignore_set(project_path):
    """Get the full ignore set for a project."""
    return ALWAYS_IGNORE | load_ftlignore(project_path)


def should_ignore(path, ignore_set):
    """Check if a relative path matches any ignore pattern."""
    for part in path.parts:
        if part in ignore_set:
            return True
    return False
