"""Tests for the document-job creation application service."""

from datetime import UTC, datetime

import pytest
from tests.fakes import InMemoryDocumentJobRepository

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    Clock,
    JobIdGenerator,
)
from clouddoc.application.create_document_job import (
    CreateDocumentJob,
    CreateDocumentJobCommand,
)
from clouddoc.application.upload_ports import (
    DocumentUploadProvider,
    DocumentUploadProviderError,
)
from clouddoc.domain import JobStatus
from clouddoc.repositories import (
    JobAlreadyExistsError,
    RepositoryError,
)
from clouddoc.schemas.job_views import DocumentJobView
from clouddoc.schemas.upload_views import (
    CreateDocumentJobResult,
    PresignedDocumentUpload,
)

FIXED_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
FIXED_UPLOAD_URL = "https://example.com/presigned-upload"
FIXED_OBJECT_KEY = "documents/job-001/source.txt"
FIXED_EXPIRES_IN_SECONDS = 900


class FixedClock:
    """Deterministic clock used by application tests."""

    def __init__(
        self,
        current_time: datetime,
    ) -> None:
        """Initialize the clock with one fixed timestamp."""
        self._current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        """Return the configured timestamp."""
        self.calls += 1
        return self._current_time


class FixedJobIdGenerator:
    """Deterministic job-id generator used by application tests."""

    def __init__(
        self,
        job_id: str,
    ) -> None:
        """Initialize the generator with one fixed identifier."""
        self._job_id = job_id
        self.calls = 0

    def generate(self) -> str:
        """Return the configured identifier."""
        self.calls += 1
        return self._job_id


class SuccessfulUploadProvider:
    """Upload provider double that returns deterministic instructions."""

    def __init__(self) -> None:
        """Initialize received job-id tracking."""
        self.job_ids: list[str] = []

    def create_upload(
        self,
        *,
        job_id: str,
    ) -> PresignedDocumentUpload:
        """Record the job id and return fixed upload instructions."""
        self.job_ids.append(job_id)

        return PresignedDocumentUpload.create(
            url=FIXED_UPLOAD_URL,
            object_key=FIXED_OBJECT_KEY,
            expires_in_seconds=FIXED_EXPIRES_IN_SECONDS,
        )


class FailingUploadProvider:
    """Upload provider double that cannot provision instructions."""

    def create_upload(
        self,
        *,
        job_id: str,
    ) -> PresignedDocumentUpload:
        """Simulate an unavailable upload dependency."""
        raise DocumentUploadProviderError("S3 unavailable")


class DuplicateJobRepository:
    """Repository double that rejects job creation."""

    def create_job(
        self,
        job: object,
    ) -> None:
        """Simulate a duplicate generated identifier."""
        raise JobAlreadyExistsError("duplicate job")

    def get_job(
        self,
        job_id: str,
    ) -> None:
        """Return no job for unused read operations."""
        return None


class FailingJobRepository:
    """Repository double that simulates a dependency failure."""

    def create_job(
        self,
        job: object,
    ) -> None:
        """Simulate an unavailable persistence dependency."""
        raise RepositoryError("DynamoDB unavailable")

    def get_job(
        self,
        job_id: str,
    ) -> None:
        """Return no job for unused read operations."""
        return None


class RecordingUploadProvider:
    """Upload provider double that records call order."""

    def __init__(
        self,
        *,
        call_order: list[str],
    ) -> None:
        """Initialize with a shared call-order recorder."""
        self._call_order = call_order
        self.job_ids: list[str] = []

    def create_upload(
        self,
        *,
        job_id: str,
    ) -> PresignedDocumentUpload:
        """Record upload provisioning before returning instructions."""
        self._call_order.append("upload")
        self.job_ids.append(job_id)

        return PresignedDocumentUpload.create(
            url=FIXED_UPLOAD_URL,
            object_key=FIXED_OBJECT_KEY,
            expires_in_seconds=FIXED_EXPIRES_IN_SECONDS,
        )


class RecordingJobRepository:
    """Repository double that records persistence call order."""

    def __init__(
        self,
        *,
        call_order: list[str],
    ) -> None:
        """Initialize with a shared call-order recorder."""
        self._call_order = call_order
        self.jobs: list[object] = []

    def create_job(
        self,
        job: object,
    ) -> None:
        """Record persistence after accepting the job."""
        self._call_order.append("persist")
        self.jobs.append(job)

    def get_job(
        self,
        job_id: str,
    ) -> None:
        """Return no job for unused read operations."""
        return None


def make_service(
    *,
    repository: object | None = None,
    clock: FixedClock | None = None,
    generator: FixedJobIdGenerator | None = None,
    upload_provider: object | None = None,
) -> CreateDocumentJob:
    """Create the application service with deterministic dependencies."""
    return CreateDocumentJob(
        repository=repository or InMemoryDocumentJobRepository(),
        clock=clock or FixedClock(FIXED_TIME),
        job_id_generator=generator or FixedJobIdGenerator("job-001"),
        upload_provider=upload_provider or SuccessfulUploadProvider(),
    )


def make_command() -> CreateDocumentJobCommand:
    """Create a valid creation command."""
    return CreateDocumentJobCommand(
        request_id="request-001",
        correlation_id="correlation-001",
    )


def expected_job_view() -> DocumentJobView:
    """Build the deterministic pending job view."""
    return DocumentJobView(
        job_id="job-001",
        status=JobStatus.PENDING_UPLOAD,
        request_id="request-001",
        correlation_id="correlation-001",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
        attempts=0,
        error_reason=None,
    )


def expected_upload() -> PresignedDocumentUpload:
    """Build the deterministic upload instructions."""
    return PresignedDocumentUpload.create(
        url=FIXED_UPLOAD_URL,
        object_key=FIXED_OBJECT_KEY,
        expires_in_seconds=FIXED_EXPIRES_IN_SECONDS,
    )


def test_test_doubles_satisfy_application_ports() -> None:
    """Test doubles should structurally implement the application ports."""
    assert isinstance(FixedClock(FIXED_TIME), Clock)
    assert isinstance(
        FixedJobIdGenerator("job-001"),
        JobIdGenerator,
    )
    assert isinstance(
        SuccessfulUploadProvider(),
        DocumentUploadProvider,
    )


def test_creates_pending_document_job() -> None:
    """The service should persist and return a new pending job."""
    repository = InMemoryDocumentJobRepository()
    upload_provider = SuccessfulUploadProvider()
    service = make_service(
        repository=repository,
        upload_provider=upload_provider,
    )

    result = service.execute(make_command())

    assert isinstance(result, CreateDocumentJobResult)
    assert result.job == expected_job_view()
    assert result.upload == expected_upload()
    assert result.upload.method == "PUT"
    assert upload_provider.job_ids == ["job-001"]

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.job_id == "job-001"
    assert stored_job.status is JobStatus.PENDING_UPLOAD
    assert stored_job.created_at == FIXED_TIME
    assert stored_job.updated_at == FIXED_TIME


def test_provisions_upload_before_persistence() -> None:
    """Upload provisioning must happen before the job is persisted."""
    call_order: list[str] = []
    service = make_service(
        repository=RecordingJobRepository(call_order=call_order),
        upload_provider=RecordingUploadProvider(call_order=call_order),
    )

    service.execute(make_command())

    assert call_order == ["upload", "persist"]


def test_translates_upload_provider_failure() -> None:
    """Upload provisioning failures should become dependency errors."""
    repository = InMemoryDocumentJobRepository()
    service = make_service(
        repository=repository,
        upload_provider=FailingUploadProvider(),
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to provision document upload",
    ) as captured_error:
        service.execute(make_command())

    assert isinstance(
        captured_error.value.cause,
        DocumentUploadProviderError,
    )
    assert captured_error.value.context == {
        "job_id": "job-001",
    }
    assert repository.get_job("job-001") is None


def test_reads_clock_and_identifier_once() -> None:
    """Creation should use one identity and one timestamp snapshot."""
    clock = FixedClock(FIXED_TIME)
    generator = FixedJobIdGenerator("job-001")
    service = make_service(
        clock=clock,
        generator=generator,
    )

    service.execute(make_command())

    assert clock.calls == 1
    assert generator.calls == 1


def test_preserves_trace_context() -> None:
    """Request and correlation identifiers should reach persistence."""
    repository = InMemoryDocumentJobRepository()
    service = make_service(repository=repository)

    service.execute(
        CreateDocumentJobCommand(
            request_id="request-special",
            correlation_id="correlation-special",
        )
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.correlation_context.request_id == "request-special"
    assert stored_job.correlation_context.correlation_id == "correlation-special"


def test_returns_detached_application_view() -> None:
    """The result should not expose the mutable domain aggregate."""
    result = make_service().execute(make_command())

    assert isinstance(result, CreateDocumentJobResult)
    assert isinstance(result.job, DocumentJobView)
    assert isinstance(result.upload, PresignedDocumentUpload)
    assert not hasattr(result.job, "start_processing")
    assert not hasattr(result.job, "mark_succeeded")
    assert not hasattr(result, "start_processing")
    assert not hasattr(result, "mark_succeeded")


def test_translates_duplicate_job_error() -> None:
    """Duplicate generated identities should become app conflicts."""
    service = make_service(
        repository=DuplicateJobRepository(),
    )

    with pytest.raises(
        ApplicationConflictError,
        match="document job job-001 already exists",
    ):
        service.execute(make_command())


def test_translates_repository_failure() -> None:
    """Infrastructure failures should become dependency errors."""
    service = make_service(
        repository=FailingJobRepository(),
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to persist document job",
    ) as captured_error:
        service.execute(make_command())

    assert isinstance(
        captured_error.value.cause,
        RepositoryError,
    )
    assert captured_error.value.context == {
        "job_id": "job-001",
    }
