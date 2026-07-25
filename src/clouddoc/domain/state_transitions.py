"""Allowed document job lifecycle transitions."""

from clouddoc.domain.job_status import JobStatus

_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING_UPLOAD: frozenset(
        {
            JobStatus.PROCESSING,
        }
    ),
    JobStatus.PROCESSING: frozenset(
        {
            JobStatus.PENDING_UPLOAD,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.DEAD,
        }
    ),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.DEAD: frozenset(),
}


def is_transition_allowed(
    current_status: JobStatus,
    target_status: JobStatus,
) -> bool:
    """Return whether a lifecycle transition is allowed."""
    return target_status in _ALLOWED_TRANSITIONS[current_status]
