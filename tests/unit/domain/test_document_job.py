"""Tests for the initial document job model."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.domain.job_status import JobStatus


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
