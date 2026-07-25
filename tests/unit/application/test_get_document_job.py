"""Tests for the document-job query application service."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes import InMemoryDocumentJobRepository

from clouddoc.application import (
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.application.get_document_job import (
    GetDocumentJob,
    GetDocumentJobQuery,
)
from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories import RepositoryError
from clouddoc.schemas.job_views import DocumentJobView

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class FailingReadRepository:
    """Repository double that simulates a read dependency failure."""

    def create_job(
        self,
        job: object,
    ) -> None:
        """Ignore unused create operations."""

    def get_job(
        self,
        job_id: str,
    ) -> None:
        """Simulate an unavailable persistence dependency."""
        raise RepositoryError("DynamoDB unavailable")


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


def make_service(
    repository: object | None = None,
) -> GetDocumentJob:
    """Create the query service with a supplied repository."""
    return GetDocumentJob(
        repository=repository or InMemoryDocumentJobRepository(),
    )


def test_returns_pending_document_job_view() -> None:
    """The service should return a normalized pending-job view."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_job())

    result = make_service(repository).execute(GetDocumentJobQuery(job_id="job-001"))

    assert result == DocumentJobView(
        job_id="job-001",
        status=JobStatus.PENDING_UPLOAD,
        request_id="request-001",
        correlation_id="correlation-001",
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
        attempts=0,
        error_reason=None,
    )


def test_returns_failed_job_error_context() -> None:
    """A failed job should expose its terminal error context."""
    repository = InMemoryDocumentJobRepository()
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
    repository.create_job(job)

    result = make_service(repository).execute(GetDocumentJobQuery(job_id="job-001"))

    assert result.status is JobStatus.FAILED
    assert result.attempts == 1
    assert result.error_reason == "invalid_utf8"
    assert result.updated_at == BASE_TIME + timedelta(seconds=2)


def test_raises_application_not_found_error() -> None:
    """Missing jobs should be translated at the application boundary."""
    service = make_service()

    with pytest.raises(
        ApplicationNotFoundError,
        match="document job missing-job was not found",
    ):
        service.execute(GetDocumentJobQuery(job_id="missing-job"))


def test_translates_repository_failure() -> None:
    """Persistence failures should become dependency errors."""
    service = make_service(
        repository=FailingReadRepository(),
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to retrieve document job",
    ) as captured_error:
        service.execute(GetDocumentJobQuery(job_id="job-001"))

    assert isinstance(
        captured_error.value.cause,
        RepositoryError,
    )
    assert captured_error.value.context == {
        "job_id": "job-001",
    }


def test_returns_detached_application_view() -> None:
    """The query result should not expose the domain aggregate."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_job())

    result = make_service(repository).execute(GetDocumentJobQuery(job_id="job-001"))

    assert isinstance(result, DocumentJobView)
    assert not hasattr(result, "start_processing")
    assert not hasattr(result, "mark_failed")


def test_query_does_not_mutate_persisted_state() -> None:
    """Reading a job must not change its persisted lifecycle state."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_job())

    service = make_service(repository)
    service.execute(GetDocumentJobQuery(job_id="job-001"))

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PENDING_UPLOAD
    assert stored_job.attempts == 0
    assert stored_job.updated_at == BASE_TIME
