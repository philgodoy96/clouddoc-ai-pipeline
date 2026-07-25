"""Core document job domain model."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.errors import (
    InvalidDomainValueError,
    InvalidStateTransitionError,
    TerminalJobMutationError,
)
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt
from clouddoc.domain.state_transitions import is_transition_allowed


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

    def start_processing(
        self,
        attempt: ProcessingAttempt,
        *,
        updated_at: datetime,
    ) -> None:
        """Acquire a new processing attempt for the job."""
        self._ensure_mutation_timestamp(updated_at)
        self._transition_to(JobStatus.PROCESSING)

        self._active_attempt = attempt
        self._attempts += 1
        self._processing_result = None
        self._error_reason = None
        self.updated_at = updated_at

    def mark_succeeded(
        self,
        result: Any,
        *,
        finished_at: datetime,
    ) -> None:
        """Complete the active processing attempt successfully."""
        self._ensure_active_attempt()
        self._ensure_mutation_timestamp(finished_at)

        if result is None:
            raise InvalidDomainValueError("processing result must not be None")

        self._transition_to(JobStatus.SUCCEEDED)

        self._processing_result = result
        self._error_reason = None
        self._active_attempt = None
        self.updated_at = finished_at

    def mark_failed(
        self,
        reason: str,
        *,
        finished_at: datetime,
    ) -> None:
        """Complete the active processing attempt with a terminal failure."""
        self._ensure_active_attempt()
        self._ensure_mutation_timestamp(finished_at)
        normalized_reason = _validate_error_reason(reason)

        self._transition_to(JobStatus.FAILED)

        self._processing_result = None
        self._error_reason = normalized_reason
        self._active_attempt = None
        self.updated_at = finished_at

    def release_for_retry(
        self,
        *,
        updated_at: datetime,
    ) -> None:
        """Release an active processing claim after a retryable failure."""
        self._ensure_active_attempt()
        self._ensure_mutation_timestamp(updated_at)
        self._transition_to(JobStatus.PENDING_UPLOAD)

        self._processing_result = None
        self._error_reason = None
        self._active_attempt = None
        self.updated_at = updated_at

    def mark_dead(
        self,
        reason: str,
        *,
        finished_at: datetime,
    ) -> None:
        """Mark an active processing attempt as retry-exhausted."""
        self._ensure_active_attempt()
        self._ensure_mutation_timestamp(finished_at)
        normalized_reason = _validate_error_reason(reason)

        self._transition_to(JobStatus.DEAD)

        self._processing_result = None
        self._error_reason = normalized_reason
        self._active_attempt = None
        self.updated_at = finished_at

    def _transition_to(self, target_status: JobStatus) -> None:
        """Validate a lifecycle transition before applying it."""
        if self._status.is_terminal:
            raise TerminalJobMutationError(
                f"terminal job cannot transition from "
                f"{self._status.value} to {target_status.value}"
            )

        if not is_transition_allowed(self._status, target_status):
            raise InvalidStateTransitionError(
                f"transition from {self._status.value} "
                f"to {target_status.value} is not allowed"
            )

        self._status = target_status

    def _ensure_active_attempt(self) -> ProcessingAttempt:
        """Require the job to have an active processing attempt."""
        if self._active_attempt is None:
            raise InvalidStateTransitionError(
                "job must have an active processing attempt"
            )

        return self._active_attempt

    def _ensure_mutation_timestamp(self, value: datetime) -> None:
        """Require a valid non-decreasing UTC mutation timestamp."""
        _validate_utc_datetime(value, field_name="mutation timestamp")

        if value < self.updated_at:
            raise InvalidDomainValueError(
                "mutation timestamp must not be earlier than updated_at"
            )


def _validate_error_reason(reason: str) -> str:
    """Validate and normalize a terminal error reason."""
    normalized_reason = reason.strip()

    if not normalized_reason:
        raise InvalidDomainValueError("error reason must not be empty")

    return normalized_reason


def _validate_utc_datetime(value: datetime, *, field_name: str) -> None:
    """Require a timezone-aware datetime normalized to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidDomainValueError(f"{field_name} must be timezone-aware")

    if value.utcoffset() != UTC.utcoffset(value):
        raise InvalidDomainValueError(f"{field_name} must use UTC")
