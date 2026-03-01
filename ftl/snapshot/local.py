import shutil
import subprocess
import uuid
from pathlib import Path
from ftl.snapshot.base import SnapshotStore
from ftl.ignore import get_ignore_set

SNAPSHOT_DIR = Path.home() / ".ftl" / "snapshots"

# Files/dirs always excluded from snapshots regardless of .ftlignore
_RSYNC_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    "node_modules",
    ".venv",
    "venv",
    "*.egg-info",
    "*.dist-info",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
]


class LocalSnapshotStore(SnapshotStore):

    def create(self, project_path):
        project_path = Path(project_path).resolve()
        snapshot_id = uuid.uuid4().hex[:8]
        snapshot_path = SNAPSHOT_DIR / snapshot_id
        snapshot_path.mkdir(parents=True, exist_ok=True)

        # Write meta before copy so rsync picks it up
        (snapshot_path / ".ftl_meta").write_text(str(project_path))

        # Build exclude args from hardcoded list + .ftlignore patterns
        ignore_set = get_ignore_set(project_path)
        excludes = list(_RSYNC_EXCLUDES) + [f"/{p}" for p in ignore_set]
        exclude_args = []
        for e in excludes:
            exclude_args += ["--exclude", e]

        # Warn about large files (> 100MB)
        large_files = []
        for f in project_path.rglob("*"):
            if f.is_file() and not any(p in f.parts for p in ignore_set):
                size_mb = f.stat().st_size / 1_000_000
                if size_mb > 100:
                    large_files.append((f.name, int(size_mb)))
        if large_files:
            print(f"Warning: {len(large_files)} large file(s) found (add to .ftlignore to exclude):")
            for name, size in large_files[:3]:
                print(f"  {name} ({size}MB)")

        subprocess.run(
            ["rsync", "-a", "--delete"] + exclude_args +
            [str(project_path) + "/", str(snapshot_path) + "/"],
            check=True,
            capture_output=True,
        )

        return snapshot_id

    def restore(self, snapshot_id, target_path=None):
        snapshot_path = SNAPSHOT_DIR / snapshot_id
        if not snapshot_path.exists():
            raise ValueError(f"Snapshot {snapshot_id} not found")

        meta_file = snapshot_path / ".ftl_meta"
        original_path = Path(meta_file.read_text().strip())
        target = Path(target_path) if target_path else original_path

        for item in snapshot_path.rglob("*"):
            if item.name == ".ftl_meta":
                continue
            relative = item.relative_to(snapshot_path)
            dest = target / relative
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

        return target

    def list(self, project_path=None):
        if not SNAPSHOT_DIR.exists():
            return []

        snapshots = []
        for entry in sorted(SNAPSHOT_DIR.iterdir()):
            meta_file = entry / ".ftl_meta"
            if not meta_file.exists():
                continue
            original_path = meta_file.read_text().strip()
            if project_path and str(Path(project_path).resolve()) != original_path:
                continue
            snapshots.append({"id": entry.name, "project": original_path})

        return snapshots

    def delete(self, snapshot_id):
        snapshot_path = SNAPSHOT_DIR / snapshot_id
        if snapshot_path.exists():
            shutil.rmtree(snapshot_path)
