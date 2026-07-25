"""Document job lifecycle statuses."""

from enum import StrEnum


class JobStatus(StrEnum):
    """Supported lifecycle states for a document-processing job."""

    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"

    @property
    def is_terminal(self) -> bool:
        """Return whether the status represents a terminal job state."""
        return self in {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.DEAD,
        }
