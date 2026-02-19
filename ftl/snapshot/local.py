import shutil
import uuid
from pathlib import Path
from ftl.snapshot.base import SnapshotStore
from ftl.ignore import get_ignore_set, should_ignore

SNAPSHOT_DIR = Path.home() / ".ftl" / "snapshots"


class LocalSnapshotStore(SnapshotStore):

    def create(self, project_path):
        project_path = Path(project_path).resolve()
        snapshot_id = uuid.uuid4().hex[:8]
        snapshot_path = SNAPSHOT_DIR / snapshot_id

        ignore_set = get_ignore_set(project_path)

        snapshot_path.mkdir(parents=True, exist_ok=True)

        meta_file = snapshot_path / ".ftl_meta"
        meta_file.write_text(str(project_path))

        for item in project_path.rglob("*"):
            relative = item.relative_to(project_path)
            if should_ignore(relative, ignore_set):
                continue
            dest = snapshot_path / relative
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

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
