import difflib
from pathlib import Path
import litellm
from rich.console import Console
from rich.text import Text

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2",
    ".pdf", ".doc", ".docx",
    ".pyc", ".pyo", ".so", ".dylib", ".dll",
}


def _is_binary(file_path):
    """Check if a file is binary."""
    if file_path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except OSError:
        return False


DIFF_IGNORE = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}


def _should_ignore_in_diff(rel_path):
    """Filter out build artifacts from diffs."""
    for part in rel_path.parts:
        if part in DIFF_IGNORE:
            return True
    return False


def compute_diff(snapshot_path, workspace_path):
    """Compare snapshot against workspace. Returns list of file diffs."""
    snapshot_path = Path(snapshot_path)
    workspace_path = Path(workspace_path)

    snapshot_files = {
        f.relative_to(snapshot_path)
        for f in snapshot_path.rglob("*")
        if f.is_file() and f.name != ".ftl_meta" and not _should_ignore_in_diff(f.relative_to(snapshot_path))
    }
    workspace_files = {
        f.relative_to(workspace_path)
        for f in workspace_path.rglob("*")
        if f.is_file() and not _should_ignore_in_diff(f.relative_to(workspace_path))
    }

    diffs = []

    for rel in sorted(snapshot_files - workspace_files):
        if _is_binary(snapshot_path / rel):
            diffs.append({"path": str(rel), "status": "deleted", "lines": [("-", "[binary file]")]})
            continue
        old_lines = (snapshot_path / rel).read_text(errors="replace").splitlines()
        diffs.append({
            "path": str(rel),
            "status": "deleted",
            "lines": [("-", line) for line in old_lines],
        })

    for rel in sorted(workspace_files - snapshot_files):
        if _is_binary(workspace_path / rel):
            diffs.append({"path": str(rel), "status": "created", "lines": [("+", "[binary file]")]})
            continue
        new_lines = (workspace_path / rel).read_text(errors="replace").splitlines()
        diffs.append({
            "path": str(rel),
            "status": "created",
            "lines": [("+", line) for line in new_lines],
        })

    for rel in sorted(snapshot_files & workspace_files):
        old_file = snapshot_path / rel
        new_file = workspace_path / rel
        if _is_binary(old_file) or _is_binary(new_file):
            if old_file.read_bytes() != new_file.read_bytes():
                diffs.append({"path": str(rel), "status": "modified", "lines": [(" ", "[binary file changed]")]})
            continue
        old_text = old_file.read_text(errors="replace").splitlines()
        new_text = new_file.read_text(errors="replace").splitlines()
        if old_text == new_text:
            continue

        lines = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old_text, new_text).get_opcodes():
            if tag == "equal":
                for line in old_text[i1:i2]:
                    lines.append((" ", line))
            elif tag == "delete":
                for line in old_text[i1:i2]:
                    lines.append(("-", line))
            elif tag == "insert":
                for line in new_text[j1:j2]:
                    lines.append(("+", line))
            elif tag == "replace":
                for line in old_text[i1:i2]:
                    lines.append(("-", line))
                for line in new_text[j1:j2]:
                    lines.append(("+", line))

        diffs.append({
            "path": str(rel),
            "status": "modified",
            "lines": lines,
        })

    return diffs


def diff_to_text(diffs):
    """Convert structured diffs to plain text for LLM context."""
    parts = []
    for diff in diffs:
        parts.append(f"--- {diff['status'].upper()}: {diff['path']} ---")
        for tag, content in diff["lines"]:
            if tag == "+":
                parts.append(f"+ {content}")
            elif tag == "-":
                parts.append(f"- {content}")
            else:
                parts.append(f"  {content}")
        parts.append("")
    return "\n".join(parts)


def display_diff(diffs):
    """Render diffs to terminal with GitHub-style colors."""
    console = Console()

    if not diffs:
        console.print("[dim]No changes detected.[/dim]")
        return

    created = sum(1 for d in diffs if d["status"] == "created")
    modified = sum(1 for d in diffs if d["status"] == "modified")
    deleted = sum(1 for d in diffs if d["status"] == "deleted")
    insertions = sum(1 for d in diffs for tag, _ in d["lines"] if tag == "+")
    deletions = sum(1 for d in diffs for tag, _ in d["lines"] if tag == "-")

    for diff in diffs:
        status_colors = {"created": "green", "modified": "yellow", "deleted": "red"}
        color = status_colors[diff["status"]]
        console.print(f"\n[bold {color}]── {diff['status'].upper()}: {diff['path']}[/bold {color}]")
        console.print()

        for tag, content in diff["lines"]:
            if tag == "+":
                console.print(Text(f"  + {content}", style="green"))
            elif tag == "-":
                console.print(Text(f"  - {content}", style="red"))
            else:
                console.print(Text(f"    {content}", style="dim"))

    console.print()
    console.print(
        f"[bold]{len(diffs)} file(s) changed[/bold] | "
        f"[green]+{insertions} insertions[/green] | "
        f"[red]-{deletions} deletions[/red] | "
        f"[green]{created} created[/green] | "
        f"[yellow]{modified} modified[/yellow] | "
        f"[red]{deleted} deleted[/red]"
    )


def ask_about_diff(diffs, question, model):
    """Ask the planner model a question about the diff."""
    console = Console()
    diff_text = diff_to_text(diffs)

    response = litellm.completion(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are reviewing code changes in a diff. Answer the user's question about these changes concisely.",
            },
            {
                "role": "user",
                "content": f"Here are the code changes:\n\n{diff_text}\n\nQuestion: {question}",
            },
        ],
        stream=True,
    )

    console.print()
    for chunk in response:
        content = chunk.choices[0].delta.content
        if content:
            console.print(content, end="")
    console.print("\n")


def review_diff(diffs, model):
    """Interactive diff review. User can approve, reject, or ask questions."""
    console = Console()
    display_diff(diffs)

    while True:
        console.print()
        console.print("[bold]  [A]pprove  [R]eject  [Q]uit  or ask a question[/bold]")
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            return False

        if not choice:
            continue
        if choice.lower() in ("a", "approve"):
            return True
        if choice.lower() in ("r", "reject", "q", "quit", "exit"):
            return False

        ask_about_diff(diffs, choice, model)
