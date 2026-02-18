from abc import ABC, abstractmethod


class SnapshotStore(ABC):
    """Base interface for snapshot backends.

    Implementations: LocalSnapshotStore (MVP), S3SnapshotStore (future).
    """

    @abstractmethod
    def create(self, project_path):
        """Snapshot the project. Returns snapshot ID."""
        pass

    @abstractmethod
    def restore(self, snapshot_id, target_path=None):
        """Restore a snapshot. Returns the restored path."""
        pass

    @abstractmethod
    def list(self, project_path=None):
        """List snapshots. Filter to project if given."""
        pass

    @abstractmethod
    def delete(self, snapshot_id):
        """Delete a snapshot by ID."""
        pass
