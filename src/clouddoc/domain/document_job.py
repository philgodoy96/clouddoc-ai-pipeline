"""Core document job domain model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt


@dataclass(slots=True)
class DocumentJob:
    """Current business state of one document-processing workflow."""

    job_id: str
    correlation_context: CorrelationContext
    created_at: datetime
    updated_at: datetime

    _status: JobStatus = field(
        default=JobStatus.PENDING_UPLOAD,
        init=False,
        repr=False,
    )
    _attempts: int = field(default=0, init=False, repr=False)
    _active_attempt: ProcessingAttempt | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _processing_result: Any | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _error_reason: str | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Validate initial document job invariants."""
        if not self.job_id.strip():
            raise InvalidDomainValueError("job_id must not be empty")

        _validate_utc_datetime(self.created_at, field_name="created_at")
        _validate_utc_datetime(self.updated_at, field_name="updated_at")

        if self.updated_at < self.created_at:
            raise InvalidDomainValueError(
                "updated_at must not be earlier than created_at"
            )

    @property
    def status(self) -> JobStatus:
        """Return the current job status."""
        return self._status

    @property
    def attempts(self) -> int:
        """Return the number of acquired processing attempts."""
        return self._attempts

    @property
    def active_attempt(self) -> ProcessingAttempt | None:
        """Return the currently active processing attempt."""
        return self._active_attempt

    @property
    def processing_result(self) -> Any | None:
        """Return the accepted processing result, when available."""
        return self._processing_result

    @property
    def error_reason(self) -> str | None:
        """Return the normalized terminal error reason, when available."""
        return self._error_reason


def _validate_utc_datetime(value: datetime, *, field_name: str) -> None:
    """Require a timezone-aware datetime normalized to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidDomainValueError(f"{field_name} must be timezone-aware")

    if value.utcoffset() != UTC.utcoffset(value):
        raise InvalidDomainValueError(f"{field_name} must use UTC")
