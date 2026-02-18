from ftl.snapshot.local import LocalSnapshotStore


def create_snapshot_store(backend="local"):
    if backend == "local":
        return LocalSnapshotStore()
    raise ValueError(f"Unknown snapshot backend: {backend}")
