"""Tests for the initial document job model."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt


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
