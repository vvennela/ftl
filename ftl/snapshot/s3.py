"""S3-backed snapshot store.

Snapshots are stored as gzipped tarballs in S3:
    s3://<bucket>/snapshots/<project_hash>/<snapshot_id>.tar.gz

Each object carries project path as S3 metadata so we can list/filter without
downloading the tarball.

The snapshot is also kept in the local cache (~/.ftl/snapshots/<id>/) so the
Docker sandbox can mount it directly — no per-task S3 download while the
container is running.  S3 is the authoritative durable store; the local cache
is ephemeral.

Requires boto3: pip install -e ".[aws]"
"""

import base64
import hashlib
import io
import shutil
import subprocess
import tarfile
import uuid
from pathlib import Path

from ftl.ignore import get_ignore_set
from ftl.snapshot.base import SnapshotStore
from ftl.snapshot.local import SNAPSHOT_DIR, _RSYNC_EXCLUDES

S3_PREFIX = "snapshots"
META_KEY = "ftl-project-path"  # kept for backwards-compat reads; new keys encode path in name


def _encode_path(project_path):
    """URL-safe base64 of the project path, no padding — used in the S3 key name."""
    return base64.urlsafe_b64encode(str(project_path).encode()).decode().rstrip("=")


def _decode_path(encoded):
    """Reverse of _encode_path."""
    padding = (4 - len(encoded) % 4) % 4
    return base64.urlsafe_b64decode(encoded + "=" * padding).decode()


class S3SnapshotStore(SnapshotStore):
    """Snapshot store backed by S3, with a local cache for container mounts."""

    def __init__(self, bucket):
        try:
            import boto3
            self._s3 = boto3.client("s3")
        except ImportError:
            raise RuntimeError(
                "boto3 is required for S3 snapshots. "
                "Install with: pip install -e '.[aws]'"
            )
        self.bucket = bucket

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def create(self, project_path):
        project_path = Path(project_path).resolve()
        snapshot_id = uuid.uuid4().hex[:8]
        local_path = SNAPSHOT_DIR / snapshot_id
        local_path.mkdir(parents=True, exist_ok=True)

        # Write meta before copy so rsync picks it up
        (local_path / ".ftl_meta").write_text(str(project_path))

        # rsync to local cache (same as LocalSnapshotStore)
        ignore_set = get_ignore_set(project_path)
        excludes = list(_RSYNC_EXCLUDES) + [f"/{p}" for p in ignore_set]
        exclude_args = []
        for e in excludes:
            exclude_args += ["--exclude", e]

        subprocess.run(
            ["rsync", "-a", "--delete"] + exclude_args +
            [str(project_path) + "/", str(local_path) + "/"],
            check=True,
            capture_output=True,
        )

        # Upload tarball to S3 — project path encoded in key name, no metadata needed
        s3_key = self._key(project_path, snapshot_id)
        tarball = self._make_tarball(local_path)
        try:
            self._s3.put_object(Bucket=self.bucket, Key=s3_key, Body=tarball)
        except Exception as e:
            error_code = (getattr(e, "response", None) or {}).get("Error", {}).get("Code", "")
            if error_code == "NoSuchBucket":
                raise RuntimeError(
                    f"S3 bucket '{self.bucket}' does not exist. "
                    "Create it first or run 'ftl config --aws'."
                ) from e
            raise

        return snapshot_id

    def restore(self, snapshot_id, target_path=None):
        local_path = SNAPSHOT_DIR / snapshot_id

        # Download from S3 if not in local cache
        if not local_path.exists():
            local_path.mkdir(parents=True, exist_ok=True)
            s3_key = self._find_key(snapshot_id)
            if s3_key is None:
                raise ValueError(f"Snapshot {snapshot_id} not found in S3 or local cache")
            response = self._s3.get_object(Bucket=self.bucket, Key=s3_key)
            tarball_bytes = response["Body"].read()
            self._extract_tarball(tarball_bytes, local_path)

        meta_file = local_path / ".ftl_meta"
        if not meta_file.exists():
            raise ValueError(f"Snapshot {snapshot_id} is missing metadata")
        original_path = Path(meta_file.read_text().strip())
        target = Path(target_path) if target_path else original_path

        for item in local_path.rglob("*"):
            if item.name == ".ftl_meta":
                continue
            relative = item.relative_to(local_path)
            dest = target / relative
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)

        return target

    def list(self, project_path=None):
        prefix = f"{S3_PREFIX}/"
        paginator = self._s3.get_paginator("list_objects_v2")
        snapshots = []

        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                snapshot_id, proj = self._parse_key(key)
                if snapshot_id is None:
                    continue
                if project_path and str(Path(project_path).resolve()) != proj:
                    continue
                snapshots.append({"id": snapshot_id, "project": proj})

        return snapshots

    def delete(self, snapshot_id):
        s3_key = self._find_key(snapshot_id)
        if s3_key:
            self._s3.delete_object(Bucket=self.bucket, Key=s3_key)

        local_path = SNAPSHOT_DIR / snapshot_id
        if local_path.exists():
            shutil.rmtree(local_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _key(self, project_path, snapshot_id):
        """S3 key for a snapshot. Encodes project path in the filename — no metadata needed."""
        project_hash = hashlib.md5(str(project_path).encode()).hexdigest()[:12]
        path_b64 = _encode_path(project_path)
        return f"{S3_PREFIX}/{project_hash}/{snapshot_id}__{path_b64}.tar.gz"

    def _parse_key(self, key):
        """Extract (snapshot_id, project_path) from an S3 key. Returns (None, None) on failure."""
        stem = Path(key).stem  # strips .gz
        if stem.endswith(".tar"):
            stem = stem[:-4]    # strips .tar from .tar.gz double extension
        if "__" in stem:
            snapshot_id, path_b64 = stem.split("__", 1)
            try:
                proj = _decode_path(path_b64)
            except Exception:
                return None, None
            return snapshot_id, proj
        # Backwards compat: old keys without encoded path — fall back to head_object
        try:
            head = self._s3.head_object(Bucket=self.bucket, Key=key)
            proj = head.get("Metadata", {}).get(META_KEY, "")
            snapshot_id = stem
            return (snapshot_id, proj) if proj else (None, None)
        except Exception:
            return None, None

    def _find_key(self, snapshot_id):
        """Search for the S3 key matching exactly this snapshot ID."""
        prefix = f"{S3_PREFIX}/"
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key_id, _ = self._parse_key(obj["Key"])
                if key_id == snapshot_id:
                    return obj["Key"]
        return None

    def _make_tarball(self, directory):
        """Create a gzipped tarball of directory in memory. Returns bytes."""
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(directory, arcname=".")
        return buf.getvalue()

    def _extract_tarball(self, data, target):
        """Extract a gzipped tarball bytes into target directory.

        Validates every member path to prevent path traversal attacks (e.g. ../../../etc/passwd).
        """
        target = Path(target).resolve()
        buf = io.BytesIO(data)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            for member in tar.getmembers():
                member_path = (target / member.name).resolve()
                if not str(member_path).startswith(str(target) + "/") and member_path != target:
                    raise ValueError(f"Unsafe path in tarball: {member.name!r}")
            tar.extractall(target)
