"""Tests for the initial document job model."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.errors import (
    InvalidDomainValueError,
    InvalidStateTransitionError,
    TerminalJobMutationError,
)
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def _make_pending_job(
    *,
    created_at: datetime = BASE_TIME,
    updated_at: datetime | None = None,
) -> DocumentJob:
    """Create a pending-upload job for start_processing tests."""
    return DocumentJob(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=created_at,
        updated_at=created_at if updated_at is None else updated_at,
    )


def _make_attempt(
    *,
    attempt_id: str = "attempt-001",
    started_at: datetime = BASE_TIME,
) -> ProcessingAttempt:
    """Create a valid processing attempt."""
    return ProcessingAttempt(
        attempt_id=attempt_id,
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )


def _rehydrate_job(
    *,
    status: JobStatus,
    attempts: int,
    active_attempt: ProcessingAttempt | None,
    processing_result: object | None,
    error_reason: str | None,
    updated_at: datetime = BASE_TIME,
) -> DocumentJob:
    """Rebuild a job in a specific persisted lifecycle state."""
    return DocumentJob.rehydrate(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=BASE_TIME,
        updated_at=updated_at,
        status=status,
        attempts=attempts,
        active_attempt=active_attempt,
        processing_result=processing_result,
        error_reason=error_reason,
    )


def test_document_job_starts_pending_upload() -> None:
    """A newly created job should begin with no processing activity."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    context = CorrelationContext(
        request_id="request-001",
        correlation_id="correlation-001",
    )

    job = DocumentJob(
        job_id="job-001",
        correlation_context=context,
        created_at=created_at,
        updated_at=created_at,
    )

    assert job.job_id == "job-001"
    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.attempts == 0
    assert job.active_attempt is None
    assert job.processing_result is None
    assert job.error_reason is None
    assert job.correlation_context is context


def test_document_job_rejects_empty_job_id() -> None:
    """A document job must have a non-empty identifier."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    with pytest.raises(
        InvalidDomainValueError,
        match="job_id must not be empty",
    ):
        DocumentJob(
            job_id=" ",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=created_at,
        )


@pytest.mark.parametrize(
    ("request_id", "correlation_id", "expected_message"),
    [
        ("", "correlation-001", "request_id must not be empty"),
        ("request-001", " ", "correlation_id must not be empty"),
    ],
)
def test_correlation_context_rejects_empty_identifiers(
    request_id: str,
    correlation_id: str,
    expected_message: str,
) -> None:
    """Workflow tracing identifiers must not be empty."""
    with pytest.raises(
        InvalidDomainValueError,
        match=expected_message,
    ):
        CorrelationContext(
            request_id=request_id,
            correlation_id=correlation_id,
        )


def test_document_job_rejects_naive_timestamp() -> None:
    """Document job timestamps must be timezone-aware."""
    created_at = datetime(2026, 7, 25, 12, 0)

    with pytest.raises(
        InvalidDomainValueError,
        match="created_at must be timezone-aware",
    ):
        DocumentJob(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=created_at,
        )


def test_document_job_rejects_updated_at_before_created_at() -> None:
    """A job cannot be updated before it was created."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    with pytest.raises(
        InvalidDomainValueError,
        match="updated_at must not be earlier than created_at",
    ):
        DocumentJob(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=created_at - timedelta(seconds=1),
        )


def test_job_status_terminal_classification() -> None:
    """Only completed lifecycle states should be terminal."""
    assert not JobStatus.PENDING_UPLOAD.is_terminal
    assert not JobStatus.PROCESSING.is_terminal
    assert JobStatus.SUCCEEDED.is_terminal
    assert JobStatus.FAILED.is_terminal
    assert JobStatus.DEAD.is_terminal


def test_document_job_rejects_non_utc_created_at() -> None:
    """Document job creation timestamps must use UTC."""
    from datetime import timezone

    brasilia_timezone = timezone(timedelta(hours=-3))
    created_at = datetime(
        2026,
        7,
        25,
        9,
        0,
        tzinfo=brasilia_timezone,
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="created_at must use UTC",
    ):
        DocumentJob(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=created_at,
        )


def test_document_job_rejects_naive_updated_at() -> None:
    """The update timestamp must also be timezone-aware."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    updated_at = datetime(2026, 7, 25, 12, 0)

    with pytest.raises(
        InvalidDomainValueError,
        match="updated_at must be timezone-aware",
    ):
        DocumentJob(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=updated_at,
        )


def test_document_job_rejects_non_utc_updated_at() -> None:
    """The update timestamp must be normalized to UTC."""
    from datetime import timezone

    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    brasilia_timezone = timezone(timedelta(hours=-3))
    updated_at = datetime(
        2026,
        7,
        25,
        9,
        0,
        tzinfo=brasilia_timezone,
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="updated_at must use UTC",
    ):
        DocumentJob(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=updated_at,
        )


def test_document_job_preserves_identity_values() -> None:
    """Job and correlation identities should remain stable after creation."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    context = CorrelationContext(
        request_id="request-001",
        correlation_id="correlation-001",
    )
    job = DocumentJob(
        job_id="job-001",
        correlation_context=context,
        created_at=created_at,
        updated_at=created_at,
    )

    assert job.job_id == "job-001"
    assert job.correlation_context.request_id == "request-001"
    assert job.correlation_context.correlation_id == "correlation-001"


def test_rehydrate_restores_processing_job() -> None:
    """Persisted processing state should be restored without replay."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )

    job = DocumentJob.rehydrate(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=created_at,
        updated_at=started_at,
        status=JobStatus.PROCESSING,
        attempts=1,
        active_attempt=attempt,
        processing_result=None,
        error_reason=None,
    )

    assert job.status is JobStatus.PROCESSING
    assert job.attempts == 1
    assert job.active_attempt is attempt
    assert job.processing_result is None
    assert job.error_reason is None


def test_rehydrate_restores_succeeded_job() -> None:
    """Persisted successful state should retain its validated result."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    completed_at = created_at + timedelta(seconds=2)
    result = {"document_type": "contract"}

    job = DocumentJob.rehydrate(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=created_at,
        updated_at=completed_at,
        status=JobStatus.SUCCEEDED,
        attempts=1,
        active_attempt=None,
        processing_result=result,
        error_reason=None,
    )

    assert job.status is JobStatus.SUCCEEDED
    assert job.attempts == 1
    assert job.processing_result == result
    assert job.active_attempt is None


@pytest.mark.parametrize(
    (
        "status",
        "attempts",
        "active_attempt",
        "processing_result",
        "error_reason",
        "expected_message",
    ),
    [
        (
            JobStatus.PENDING_UPLOAD,
            0,
            "active",
            None,
            None,
            "pending job must not have an active attempt",
        ),
        (
            JobStatus.PROCESSING,
            1,
            None,
            None,
            None,
            "processing job must have an active attempt",
        ),
        (
            JobStatus.SUCCEEDED,
            1,
            None,
            None,
            None,
            "succeeded job must have a processing result",
        ),
        (
            JobStatus.FAILED,
            1,
            None,
            None,
            None,
            "failed job must have an error reason",
        ),
    ],
)
def test_rehydrate_rejects_inconsistent_persisted_state(
    status: JobStatus,
    attempts: int,
    active_attempt: object,
    processing_result: object,
    error_reason: str | None,
    expected_message: str,
) -> None:
    """Persistence must not reconstruct impossible job states."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=created_at,
        lease_expires_at=created_at + timedelta(minutes=5),
    )

    resolved_attempt = attempt if active_attempt == "active" else None

    with pytest.raises(
        InvalidDomainValueError,
        match=expected_message,
    ):
        DocumentJob.rehydrate(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=created_at,
            status=status,
            attempts=attempts,
            active_attempt=resolved_attempt,
            processing_result=processing_result,
            error_reason=error_reason,
        )


def test_rehydrate_rejects_negative_attempt_count() -> None:
    """Persisted attempt counts must never be negative."""
    created_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    with pytest.raises(
        InvalidDomainValueError,
        match="attempts must not be negative",
    ):
        DocumentJob.rehydrate(
            job_id="job-001",
            correlation_context=CorrelationContext(
                request_id="request-001",
                correlation_id="correlation-001",
            ),
            created_at=created_at,
            updated_at=created_at,
            status=JobStatus.PENDING_UPLOAD,
            attempts=-1,
            active_attempt=None,
            processing_result=None,
            error_reason=None,
        )


def test_start_processing_transitions_pending_upload_to_processing() -> None:
    """A pending job can start processing with a UTC mutation timestamp."""
    job = _make_pending_job()
    attempt = _make_attempt(started_at=BASE_TIME + timedelta(seconds=1))
    now = BASE_TIME + timedelta(seconds=1)

    job.start_processing(attempt, updated_at=now)

    assert job.status is JobStatus.PROCESSING
    assert job.updated_at == now


def test_start_processing_preserves_unrelated_metadata() -> None:
    """Identity and creation metadata must remain stable across the transition."""
    job = _make_pending_job()
    attempt = _make_attempt(started_at=BASE_TIME + timedelta(seconds=1))
    now = BASE_TIME + timedelta(seconds=1)

    job.start_processing(attempt, updated_at=now)

    assert job.job_id == "job-001"
    assert job.correlation_context.request_id == "request-001"
    assert job.correlation_context.correlation_id == "correlation-001"
    assert job.created_at == BASE_TIME
    assert job.attempts == 1
    assert job.active_attempt is attempt
    assert job.processing_result is None
    assert job.error_reason is None


@pytest.mark.parametrize(
    (
        "status",
        "attempts",
        "active_attempt",
        "processing_result",
        "error_reason",
        "error_type",
        "expected_message",
    ),
    [
        (
            JobStatus.PROCESSING,
            1,
            "active",
            None,
            None,
            InvalidStateTransitionError,
            "transition from processing to processing is not allowed",
        ),
        (
            JobStatus.SUCCEEDED,
            1,
            None,
            {"document_type": "contract"},
            None,
            TerminalJobMutationError,
            "terminal job cannot transition from succeeded to processing",
        ),
        (
            JobStatus.FAILED,
            1,
            None,
            None,
            "unsupported_content_type",
            TerminalJobMutationError,
            "terminal job cannot transition from failed to processing",
        ),
        (
            JobStatus.DEAD,
            1,
            None,
            None,
            "retry_exhausted",
            TerminalJobMutationError,
            "terminal job cannot transition from dead to processing",
        ),
    ],
)
def test_start_processing_rejects_non_pending_source_states(
    status: JobStatus,
    attempts: int,
    active_attempt: object,
    processing_result: object | None,
    error_reason: str | None,
    error_type: type[Exception],
    expected_message: str,
) -> None:
    """Only pending_upload may transition into processing."""
    attempt = _make_attempt()
    job = _rehydrate_job(
        status=status,
        attempts=attempts,
        active_attempt=attempt if active_attempt == "active" else None,
        processing_result=processing_result,
        error_reason=error_reason,
    )
    original_updated_at = job.updated_at
    next_attempt = _make_attempt(
        attempt_id="attempt-002",
        started_at=BASE_TIME + timedelta(seconds=1),
    )

    with pytest.raises(error_type, match=expected_message):
        job.start_processing(
            next_attempt,
            updated_at=BASE_TIME + timedelta(seconds=1),
        )

    assert job.status is status
    assert job.updated_at == original_updated_at


def test_start_processing_rejects_naive_timestamp() -> None:
    """start_processing requires a timezone-aware mutation timestamp."""
    job = _make_pending_job()
    original_updated_at = job.updated_at

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must be timezone-aware",
    ):
        job.start_processing(
            _make_attempt(),
            updated_at=datetime(2026, 7, 25, 12, 0),
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.updated_at == original_updated_at


def test_start_processing_rejects_non_utc_timestamp() -> None:
    """start_processing requires a UTC mutation timestamp."""
    job = _make_pending_job()
    original_updated_at = job.updated_at
    brasilia_timezone = timezone(timedelta(hours=-3))
    non_utc = datetime(2026, 7, 25, 9, 0, 1, tzinfo=brasilia_timezone)

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must use UTC",
    ):
        job.start_processing(
            _make_attempt(),
            updated_at=non_utc,
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.updated_at == original_updated_at


def test_start_processing_rejects_timestamp_earlier_than_updated_at() -> None:
    """The transition must not move the aggregate backward in time."""
    job = _make_pending_job()
    original_updated_at = job.updated_at

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must not be earlier than updated_at",
    ):
        job.start_processing(
            _make_attempt(),
            updated_at=BASE_TIME - timedelta(seconds=1),
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.updated_at == original_updated_at


def test_start_processing_accepts_equal_updated_at_timestamp() -> None:
    """An equal mutation timestamp satisfies the non-decreasing invariant."""
    job = _make_pending_job()
    attempt = _make_attempt()

    job.start_processing(attempt, updated_at=BASE_TIME)

    assert job.status is JobStatus.PROCESSING
    assert job.updated_at == BASE_TIME


def test_start_processing_is_strict_not_idempotent() -> None:
    """A second start_processing call must raise after a successful claim."""
    job = _make_pending_job()
    first_attempt = _make_attempt()
    second_attempt = _make_attempt(
        attempt_id="attempt-002",
        started_at=BASE_TIME + timedelta(seconds=2),
    )

    job.start_processing(
        first_attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    with pytest.raises(
        InvalidStateTransitionError,
        match="transition from processing to processing is not allowed",
    ):
        job.start_processing(
            second_attempt,
            updated_at=BASE_TIME + timedelta(seconds=2),
        )

    assert job.status is JobStatus.PROCESSING
    assert job.updated_at == BASE_TIME + timedelta(seconds=1)
    assert job.active_attempt is first_attempt
    assert job.attempts == 1
