"""Tests for application-facing document job views."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.schemas.job_views import DocumentJobView

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def make_job() -> DocumentJob:
    """Create a valid pending document job."""
    return DocumentJob(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def make_attempt() -> ProcessingAttempt:
    """Create a valid processing attempt."""
    started_at = BASE_TIME + timedelta(seconds=1)

    return ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )


def test_creates_view_from_pending_job() -> None:
    """A pending domain job should produce a stable application view."""
    job = make_job()

    view = DocumentJobView.from_job(job)

    assert view == DocumentJobView(
        job_id="job-001",
        status=JobStatus.PENDING_UPLOAD,
        request_id="request-001",
        correlation_id="correlation-001",
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
        attempts=0,
        error_reason=None,
    )


def test_creates_view_from_failed_job() -> None:
    """Terminal error context should be exposed through the view."""
    job = make_job()
    attempt = make_attempt()

    job.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    job.mark_failed(
        "invalid_utf8",
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    view = DocumentJobView.from_job(job)

    assert view.status is JobStatus.FAILED
    assert view.attempts == 1
    assert view.error_reason == "invalid_utf8"
    assert view.updated_at == BASE_TIME + timedelta(seconds=2)


def test_view_is_detached_from_domain_mutations() -> None:
    """Later domain transitions must not alter an existing view."""
    job = make_job()
    view = DocumentJobView.from_job(job)

    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    assert view.status is JobStatus.PENDING_UPLOAD
    assert view.attempts == 0
    assert view.updated_at == BASE_TIME


def test_view_is_immutable() -> None:
    """Application views should not be mutable response containers."""
    view = DocumentJobView.from_job(make_job())

    with pytest.raises(ValidationError):
        view.status = JobStatus.PROCESSING


def test_serializes_status_and_timestamps_for_json() -> None:
    """The view should expose JSON-compatible boundary values."""
    view = DocumentJobView.from_job(make_job())

    payload = view.model_dump(mode="json")

    assert payload == {
        "job_id": "job-001",
        "status": "pending_upload",
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "created_at": "2026-07-25T12:00:00Z",
        "updated_at": "2026-07-25T12:00:00Z",
        "attempts": 0,
        "error_reason": None,
    }
