"""Repository-specific exceptions for document job persistence."""


class RepositoryError(Exception):
    """Base exception for repository operations."""


class JobAlreadyExistsError(RepositoryError):
    """Raised when a job is created with an existing identity."""

    error_code = "job_already_exists"


class JobNotFoundError(RepositoryError):
    """Raised when a required job does not exist."""

    error_code = "job_not_found"


class JobClaimConflictError(RepositoryError):
    """Raised when a job cannot be claimed by the requested attempt."""

    error_code = "job_claim_conflict"


class JobAttemptMismatchError(RepositoryError):
    """Raised when an operation is performed by a stale attempt."""

    error_code = "job_attempt_mismatch"


class JobStateConflictError(RepositoryError):
    """Raised when persisted job state rejects an operation."""

    error_code = "job_state_conflict"
