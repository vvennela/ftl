from ftl.snapshot.local import LocalSnapshotStore
import ftl.snapshot.local as local_mod


def test_snapshot_create_writes_manifest_and_restore_skips_it(monkeypatch, tmp_path):
    snapshots_dir = tmp_path / "snapshots"
    monkeypatch.setattr(local_mod, "SNAPSHOT_DIR", snapshots_dir)

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('hi')\n")
    (project / "nested").mkdir()
    (project / "nested" / "data.txt").write_text("hello\n")

    store = LocalSnapshotStore()
    snapshot_id = store.create(project)
    snapshot_path = snapshots_dir / snapshot_id

    manifest = snapshot_path / ".ftl_manifest"
    assert manifest.exists()
    manifest_lines = set(manifest.read_text().splitlines())
    assert any(line.startswith("app.py\t12\t") for line in manifest_lines)
    assert any(line.startswith("nested/data.txt\t") for line in manifest_lines)

    restore_target = tmp_path / "restore"
    store.restore(snapshot_id, restore_target)

    assert (restore_target / "app.py").read_text() == "print('hi')\n"
    assert (restore_target / "nested" / "data.txt").read_text() == "hello\n"
    assert not (restore_target / ".ftl_manifest").exists()
    assert not (restore_target / ".ftl_meta").exists()
