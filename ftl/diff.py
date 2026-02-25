import base64
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


DIFF_IGNORE = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "site-packages", "venv", ".venv"}

_DIFF_IGNORE_SUFFIXES = (".dist-info", ".egg-info", ".egg-link")


def _should_ignore_in_diff(rel_path):
    """Filter out build artifacts from diffs."""
    for part in rel_path.parts:
        if part in DIFF_IGNORE:
            return True
        if part.endswith(_DIFF_IGNORE_SUFFIXES):
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


def compute_diff_from_overlay(overlay_changes, snapshot_path):
    """Compute structured diffs from the overlay upper layer.

    overlay_changes: list of dicts from sandbox.get_diff():
        [{"path": str, "deleted": bool, "content_b64": str}]
    snapshot_path: local path to the read-only snapshot dir.

    Returns the same format as compute_diff(), with an extra "_content_bytes" key
    on created/modified entries so _merge_changes() can write them directly.
    """
    snapshot_path = Path(snapshot_path)

    snapshot_files = {
        f.relative_to(snapshot_path)
        for f in snapshot_path.rglob("*")
        if f.is_file()
        and f.name != ".ftl_meta"
        and not _should_ignore_in_diff(f.relative_to(snapshot_path))
    }

    diffs = []

    for change in overlay_changes:
        rel = Path(change["path"])

        if _should_ignore_in_diff(rel):
            continue

        if change["deleted"]:
            snapshot_file = snapshot_path / rel
            if not snapshot_file.exists():
                continue
            if _is_binary(snapshot_file):
                diffs.append({
                    "path": str(rel),
                    "status": "deleted",
                    "lines": [("-", "[binary file]")],
                })
            else:
                old_lines = snapshot_file.read_text(errors="replace").splitlines()
                diffs.append({
                    "path": str(rel),
                    "status": "deleted",
                    "lines": [("-", line) for line in old_lines],
                })
            continue

        content_bytes = base64.b64decode(change["content_b64"])
        status = "modified" if rel in snapshot_files else "created"

        # Binary detection: check extension or null bytes
        is_bin = rel.suffix.lower() in BINARY_EXTENSIONS or b"\x00" in content_bytes[:8192]

        if is_bin:
            label = "[binary file]" if status == "created" else "[binary file changed]"
            tag = "+" if status == "created" else " "
            diffs.append({
                "path": str(rel),
                "status": status,
                "lines": [(tag, label)],
                "_content_bytes": content_bytes,
            })
            continue

        new_text = content_bytes.decode(errors="replace").splitlines()

        if status == "created":
            diffs.append({
                "path": str(rel),
                "status": "created",
                "lines": [("+", line) for line in new_text],
                "_content_bytes": content_bytes,
            })
        else:
            old_file = snapshot_path / rel
            if _is_binary(old_file):
                diffs.append({
                    "path": str(rel),
                    "status": "modified",
                    "lines": [(" ", "[binary file changed]")],
                    "_content_bytes": content_bytes,
                })
                continue

            old_text = old_file.read_text(errors="replace").splitlines()
            if old_text == new_text:
                continue  # file in upper layer but no actual change

            lines = []
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
                None, old_text, new_text
            ).get_opcodes():
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
                "_content_bytes": content_bytes,
            })

    return sorted(diffs, key=lambda d: d["path"])


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
