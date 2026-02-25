from ftl.snapshot.local import LocalSnapshotStore


def create_snapshot_store(config=None):
    """Create a snapshot store from config.

    Config keys:
        snapshot_backend: "local" (default) or "s3"
        s3_bucket: required when snapshot_backend is "s3"
    """
    config = config or {}
    backend = config.get("snapshot_backend", "local")

    if backend == "s3":
        from ftl.snapshot.s3 import S3SnapshotStore
        bucket = config.get("s3_bucket")
        if not bucket:
            raise ValueError(
                "s3_bucket is required when snapshot_backend is 's3'. "
                "Add it to .ftlconfig: {\"s3_bucket\": \"my-ftl-bucket\"}"
            )
        return S3SnapshotStore(bucket)

    if backend == "local":
        return LocalSnapshotStore()

    raise ValueError(f"Unknown snapshot backend: {backend!r}. Use 'local' or 's3'.")
