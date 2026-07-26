"""Tests for idempotent document-processing claim acquisition."""

from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes import InMemoryDocumentJobRepository

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
    Clock,
    ProcessingAttemptIdGenerator,
)
from clouddoc.application.start_document_processing import (
    StartDocumentProcessing,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories import (
    JobClaimConflictError,
    RepositoryError,
)

FIXED_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
LEASE_DURATION = timedelta(minutes=5)


class FixedClock:
    """Clock double returning one deterministic timestamp."""

    def __init__(
        self,
        value: datetime,
    ) -> None:
        """Initialize the clock."""
        self._value = value
        self.calls = 0

    def now(self) -> datetime:
        """Return the configured timestamp."""
        self.calls += 1
        return self._value


class FixedAttemptIdGenerator:
    """Attempt-ID generator returning one deterministic identity."""

    def __init__(
        self,
        attempt_id: str = "attempt-001",
    ) -> None:
        """Initialize the generator."""
        self._attempt_id = attempt_id
        self.calls = 0

    def generate(self) -> str:
        """Return the configured attempt identifier."""
        self.calls += 1
        return self._attempt_id


class FailingReadRepository:
    """Repository double that fails authoritative reads."""

    def get_job(
        self,
        job_id: str,
    ) -> None:
        """Simulate an unavailable repository."""
        raise RepositoryError("DynamoDB unavailable")


class FailingClaimRepository:
    """Repository double that fails claim persistence."""

    def __init__(
        self,
        job: DocumentJob,
    ) -> None:
        """Initialize the repository with one authoritative job."""
        self._job = job

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob:
        """Return the authoritative job."""
        return self._job

    def claim_job(
        self,
        job_id: str,
        attempt: ProcessingAttempt,
        *,
        claimed_at: datetime,
    ) -> DocumentJob:
        """Simulate a dependency failure while claiming."""
        raise RepositoryError("DynamoDB unavailable")


class ReconciledConflictRepository:
    """Repository double simulating a competing successful claim."""

    def __init__(
        self,
        *,
        initial_job: DocumentJob,
        reconciled_job: DocumentJob,
    ) -> None:
        """Initialize authoritative states around a claim race."""
        self._jobs = [
            initial_job,
            reconciled_job,
        ]
        self.get_calls = 0
        self.claim_calls = 0

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob:
        """Return the state visible at the current race phase."""
        index = min(
            self.get_calls,
            len(self._jobs) - 1,
        )
        self.get_calls += 1
        return self._jobs[index]

    def claim_job(
        self,
        job_id: str,
        attempt: ProcessingAttempt,
        *,
        claimed_at: datetime,
    ) -> DocumentJob:
        """Simulate a conditional claim conflict."""
        self.claim_calls += 1
        raise JobClaimConflictError(f"job {job_id} already has an active claim")


def make_pending_job() -> DocumentJob:
    """Create one pending document job."""
    return DocumentJob(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )


def make_processing_job(
    *,
    attempt_id: str = "attempt-existing",
    started_at: datetime = FIXED_TIME,
    lease_expires_at: datetime | None = None,
) -> DocumentJob:
    """Create a processing job with one active lease."""
    resolved_expiration = lease_expires_at or started_at + LEASE_DURATION

    return DocumentJob.rehydrate(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=FIXED_TIME,
        updated_at=started_at,
        status=JobStatus.PROCESSING,
        attempts=1,
        active_attempt=ProcessingAttempt(
            attempt_id=attempt_id,
            started_at=started_at,
            lease_expires_at=resolved_expiration,
        ),
        processing_result=None,
        error_reason=None,
    )


def make_terminal_job(
    status: JobStatus,
) -> DocumentJob:
    """Create one valid terminal job."""
    processing_result = (
        {"document_type": "invoice"} if status is JobStatus.SUCCEEDED else None
    )
    error_reason = None if status is JobStatus.SUCCEEDED else "processing failed"

    return DocumentJob.rehydrate(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
        status=status,
        attempts=1,
        active_attempt=None,
        processing_result=processing_result,
        error_reason=error_reason,
    )


def make_event(
    *,
    object_key: str = "documents/job-001/source.txt",
) -> UploadedDocumentEvent:
    """Create one normalized uploaded-document event."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key=object_key,
        job_id="job-001",
        object_size=128,
        etag="etag-001",
        sequencer="sequencer-001",
        version_id=None,
    )


def make_service(
    *,
    repository: object | None = None,
    clock: FixedClock | None = None,
    generator: FixedAttemptIdGenerator | None = None,
    lease_duration: timedelta = LEASE_DURATION,
) -> StartDocumentProcessing:
    """Create the service with deterministic dependencies."""
    resolved_repository = (
        repository if repository is not None else InMemoryDocumentJobRepository()
    )

    return StartDocumentProcessing(
        repository=resolved_repository,
        clock=clock or FixedClock(FIXED_TIME),
        attempt_id_generator=(generator or FixedAttemptIdGenerator()),
        lease_duration=lease_duration,
    )


def test_doubles_satisfy_application_ports() -> None:
    """Deterministic doubles should satisfy application contracts."""
    assert isinstance(
        FixedClock(FIXED_TIME),
        Clock,
    )
    assert isinstance(
        FixedAttemptIdGenerator(),
        ProcessingAttemptIdGenerator,
    )


def test_claims_pending_job() -> None:
    """A pending job should acquire one processing attempt."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_pending_job())
    clock = FixedClock(FIXED_TIME)
    generator = FixedAttemptIdGenerator()
    service = make_service(
        repository=repository,
        clock=clock,
        generator=generator,
    )

    result = service.execute(
        event=make_event(),
    )

    assert result is None

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PROCESSING
    assert stored_job.attempts == 1
    assert stored_job.active_attempt == ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=FIXED_TIME,
        lease_expires_at=FIXED_TIME + LEASE_DURATION,
    )
    assert clock.calls == 1
    assert generator.calls == 1


def test_active_processing_claim_is_idempotent() -> None:
    """A duplicate should accept an already-active claim."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(
        make_processing_job(
            started_at=FIXED_TIME,
            lease_expires_at=FIXED_TIME + LEASE_DURATION,
        )
    )
    generator = FixedAttemptIdGenerator()
    service = make_service(
        repository=repository,
        clock=FixedClock(FIXED_TIME + timedelta(minutes=1)),
        generator=generator,
    )

    service.execute(
        event=make_event(),
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.attempts == 1
    assert stored_job.active_attempt is not None
    assert stored_job.active_attempt.attempt_id == "attempt-existing"
    assert generator.calls == 0


def test_reclaims_expired_processing_lease() -> None:
    """An expired claim should be replaced by a new attempt."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(
        make_processing_job(
            started_at=FIXED_TIME,
            lease_expires_at=(FIXED_TIME + timedelta(minutes=1)),
        )
    )
    claimed_at = FIXED_TIME + timedelta(minutes=2)
    service = make_service(
        repository=repository,
        clock=FixedClock(claimed_at),
        generator=FixedAttemptIdGenerator("attempt-replacement"),
    )

    service.execute(
        event=make_event(),
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PROCESSING
    assert stored_job.attempts == 2
    assert stored_job.active_attempt == ProcessingAttempt(
        attempt_id="attempt-replacement",
        started_at=claimed_at,
        lease_expires_at=claimed_at + LEASE_DURATION,
    )


def test_succeeded_job_is_idempotent() -> None:
    """A late duplicate should not regress a succeeded job."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_terminal_job(JobStatus.SUCCEEDED))
    generator = FixedAttemptIdGenerator()
    service = make_service(
        repository=repository,
        generator=generator,
    )

    service.execute(
        event=make_event(),
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.SUCCEEDED
    assert generator.calls == 0


@pytest.mark.parametrize(
    "status",
    [
        JobStatus.FAILED,
        JobStatus.DEAD,
    ],
)
def test_rejects_terminal_failure_states(
    status: JobStatus,
) -> None:
    """Upload duplication must not restart terminal failures."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_terminal_job(status))
    service = make_service(
        repository=repository,
    )

    with pytest.raises(
        ApplicationConflictError,
        match=(f"job job-001 cannot start processing from {status.value}"),
    ):
        service.execute(
            event=make_event(),
        )


def test_rejects_object_ownership_mismatch() -> None:
    """The uploaded key must belong to the authoritative job."""
    repository = InMemoryDocumentJobRepository()
    repository.create_job(make_pending_job())
    service = make_service(
        repository=repository,
    )

    invalid_event = make_event().model_copy(
        update={
            "object_key": "documents/job-002/source.txt",
        }
    )

    with pytest.raises(
        ApplicationConflictError,
        match="uploaded object does not belong",
    ):
        service.execute(
            event=invalid_event,
        )


def test_missing_job_is_not_found() -> None:
    """An S3 event without an authoritative job should fail."""
    service = make_service()

    with pytest.raises(
        ApplicationNotFoundError,
        match="document job job-001 was not found",
    ):
        service.execute(
            event=make_event(),
        )


def test_translates_repository_read_failure() -> None:
    """Read failures should remain dependency failures."""
    service = make_service(
        repository=FailingReadRepository(),
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to load document job",
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert isinstance(
        captured_error.value.cause,
        RepositoryError,
    )
    assert captured_error.value.context == {
        "job_id": "job-001",
    }


def test_translates_repository_claim_failure() -> None:
    """Claim persistence failures should remain retryable."""
    service = make_service(
        repository=FailingClaimRepository(make_pending_job()),
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to claim document job",
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert isinstance(
        captured_error.value.cause,
        RepositoryError,
    )
    assert captured_error.value.context == {
        "job_id": "job-001",
        "attempt_id": "attempt-001",
    }


def test_reconciles_competing_active_claim_as_success() -> None:
    """A competing worker claim should satisfy the desired effect."""
    repository = ReconciledConflictRepository(
        initial_job=make_pending_job(),
        reconciled_job=make_processing_job(
            attempt_id="attempt-competitor",
            started_at=FIXED_TIME,
            lease_expires_at=(FIXED_TIME + LEASE_DURATION),
        ),
    )
    service = make_service(
        repository=repository,
    )

    service.execute(
        event=make_event(),
    )

    assert repository.claim_calls == 1
    assert repository.get_calls == 2


def test_rejects_unresolved_claim_conflict() -> None:
    """A conflict with incompatible authoritative state should fail."""
    repository = ReconciledConflictRepository(
        initial_job=make_pending_job(),
        reconciled_job=make_terminal_job(JobStatus.FAILED),
    )
    service = make_service(
        repository=repository,
    )

    with pytest.raises(
        ApplicationConflictError,
        match="could not acquire processing ownership",
    ):
        service.execute(
            event=make_event(),
        )


@pytest.mark.parametrize(
    "lease_duration",
    [
        timedelta(0),
        timedelta(seconds=-1),
    ],
)
def test_rejects_non_positive_lease_duration(
    lease_duration: timedelta,
) -> None:
    """Processing ownership must always be bounded in the future."""
    with pytest.raises(
        ValueError,
        match="lease_duration must be positive",
    ):
        make_service(
            lease_duration=lease_duration,
        )
