"""Contract tests for document job repository implementations."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes import InMemoryDocumentJobRepository

from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    JobAlreadyExistsError,
    JobAttemptMismatchError,
    JobClaimConflictError,
    JobNotFoundError,
    JobStateConflictError,
)
from clouddoc.schemas import AIExtractionResult, DocumentType

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

RepositoryFactory = Callable[[], DocumentJobRepository]


@pytest.fixture
def repository_factories() -> list[RepositoryFactory]:
    """Return repository implementations covered by this contract."""
    return [
        InMemoryDocumentJobRepository,
    ]


@pytest.fixture
def repository(
    repository_factories: list[RepositoryFactory],
) -> DocumentJobRepository:
    """Create a fresh repository for each contract test."""
    return repository_factories[0]()


def make_job(
    *,
    job_id: str = "job-001",
) -> DocumentJob:
    """Create a valid pending document job."""
    return DocumentJob(
        job_id=job_id,
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def make_attempt(
    *,
    attempt_id: str = "attempt-001",
    started_at: datetime = BASE_TIME + timedelta(seconds=1),
    lease_duration: timedelta = timedelta(minutes=5),
) -> ProcessingAttempt:
    """Create a valid processing attempt."""
    return ProcessingAttempt(
        attempt_id=attempt_id,
        started_at=started_at,
        lease_expires_at=started_at + lease_duration,
    )


def make_result() -> AIExtractionResult:
    """Create a validated extraction result."""
    return AIExtractionResult(
        document_type=DocumentType.CONTRACT,
        summary="A service agreement.",
        key_fields={
            "effective_date": "2026-07-25",
        },
        confidence=0.91,
        requires_human_review=False,
    )


def test_repository_implementations_satisfy_protocol(
    repository_factories: list[RepositoryFactory],
) -> None:
    """Every registered repository must expose the public contract."""
    for factory in repository_factories:
        assert isinstance(factory(), DocumentJobRepository)


def test_create_and_get_job(
    repository: DocumentJobRepository,
) -> None:
    """A newly created job should be retrievable."""
    job = make_job()

    repository.create_job(job)

    stored_job = repository.get_job(job.job_id)

    assert stored_job is not None
    assert stored_job.job_id == job.job_id
    assert stored_job.status is JobStatus.PENDING_UPLOAD
    assert stored_job.correlation_context == job.correlation_context


def test_create_job_rejects_duplicate_identity(
    repository: DocumentJobRepository,
) -> None:
    """A repository must reject duplicate job identities."""
    repository.create_job(make_job())

    with pytest.raises(JobAlreadyExistsError):
        repository.create_job(make_job())


def test_get_job_returns_none_when_missing(
    repository: DocumentJobRepository,
) -> None:
    """Missing jobs should be represented as an absent read result."""
    assert repository.get_job("missing-job") is None


def test_get_job_returns_isolated_copy(
    repository: DocumentJobRepository,
) -> None:
    """Mutating a retrieved object must not alter persisted state."""
    repository.create_job(make_job())

    retrieved_job = repository.get_job("job-001")

    assert retrieved_job is not None

    retrieved_job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PENDING_UPLOAD
    assert stored_job.attempts == 0
    assert stored_job.active_attempt is None


def test_create_job_stores_isolated_copy(
    repository: DocumentJobRepository,
) -> None:
    """Mutating the source object must not alter persisted state."""
    job = make_job()

    repository.create_job(job)

    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    stored_job = repository.get_job(job.job_id)

    assert stored_job is not None
    assert stored_job.status is JobStatus.PENDING_UPLOAD
    assert stored_job.attempts == 0


def test_claim_pending_job(
    repository: DocumentJobRepository,
) -> None:
    """A pending job should become owned by the requested attempt."""
    repository.create_job(make_job())
    attempt = make_attempt()
    claimed_at = BASE_TIME + timedelta(seconds=1)

    claimed_job = repository.claim_job(
        "job-001",
        attempt,
        claimed_at=claimed_at,
    )

    assert claimed_job.status is JobStatus.PROCESSING
    assert claimed_job.active_attempt == attempt
    assert claimed_job.attempts == 1
    assert claimed_job.updated_at == claimed_at


def test_claim_missing_job_raises_not_found(
    repository: DocumentJobRepository,
) -> None:
    """Claiming a missing job should fail explicitly."""
    with pytest.raises(JobNotFoundError):
        repository.claim_job(
            "missing-job",
            make_attempt(),
            claimed_at=BASE_TIME + timedelta(seconds=1),
        )


def test_claim_rejects_active_non_expired_lease(
    repository: DocumentJobRepository,
) -> None:
    """A second worker must not steal a valid processing lease."""
    repository.create_job(make_job())
    first_attempt = make_attempt()

    repository.claim_job(
        "job-001",
        first_attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    second_attempt = make_attempt(
        attempt_id="attempt-002",
        started_at=BASE_TIME + timedelta(seconds=2),
    )

    with pytest.raises(JobClaimConflictError):
        repository.claim_job(
            "job-001",
            second_attempt,
            claimed_at=BASE_TIME + timedelta(seconds=2),
        )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.active_attempt == first_attempt
    assert stored_job.attempts == 1


def test_claim_reclaims_expired_lease(
    repository: DocumentJobRepository,
) -> None:
    """An expired processing lease should permit a new owner."""
    repository.create_job(make_job())

    first_attempt = make_attempt(
        lease_duration=timedelta(seconds=5),
    )
    repository.claim_job(
        "job-001",
        first_attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    second_attempt = make_attempt(
        attempt_id="attempt-002",
        started_at=BASE_TIME + timedelta(seconds=6),
    )

    reclaimed_job = repository.claim_job(
        "job-001",
        second_attempt,
        claimed_at=BASE_TIME + timedelta(seconds=6),
    )

    assert reclaimed_job.status is JobStatus.PROCESSING
    assert reclaimed_job.active_attempt == second_attempt
    assert reclaimed_job.attempts == 2


@pytest.mark.parametrize(
    "terminal_operation",
    [
        "complete",
        "fail",
    ],
)
def test_claim_rejects_terminal_job(
    repository: DocumentJobRepository,
    terminal_operation: str,
) -> None:
    """Terminal jobs must not return to active processing."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    if terminal_operation == "complete":
        repository.complete_job(
            "job-001",
            attempt.attempt_id,
            make_result(),
            completed_at=BASE_TIME + timedelta(seconds=2),
        )
    else:
        repository.fail_job(
            "job-001",
            attempt.attempt_id,
            "invalid_document",
            failed_at=BASE_TIME + timedelta(seconds=2),
        )

    with pytest.raises(JobStateConflictError):
        repository.claim_job(
            "job-001",
            make_attempt(
                attempt_id="attempt-002",
                started_at=BASE_TIME + timedelta(seconds=3),
            ),
            claimed_at=BASE_TIME + timedelta(seconds=3),
        )


def test_complete_job_with_owning_attempt(
    repository: DocumentJobRepository,
) -> None:
    """The active owner should be able to complete the job."""
    repository.create_job(make_job())
    attempt = make_attempt()
    result = make_result()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    completed_job = repository.complete_job(
        "job-001",
        attempt.attempt_id,
        result,
        completed_at=BASE_TIME + timedelta(seconds=2),
    )

    assert completed_job.status is JobStatus.SUCCEEDED
    assert completed_job.processing_result == result
    assert completed_job.active_attempt is None
    assert completed_job.error_reason is None


def test_complete_job_rejects_stale_attempt(
    repository: DocumentJobRepository,
) -> None:
    """A stale worker must not complete another attempt's claim."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    with pytest.raises(JobAttemptMismatchError):
        repository.complete_job(
            "job-001",
            "stale-attempt",
            make_result(),
            completed_at=BASE_TIME + timedelta(seconds=2),
        )


def test_fail_job_with_owning_attempt(
    repository: DocumentJobRepository,
) -> None:
    """The active owner should be able to record terminal failure."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    failed_job = repository.fail_job(
        "job-001",
        attempt.attempt_id,
        "invalid_utf8",
        failed_at=BASE_TIME + timedelta(seconds=2),
    )

    assert failed_job.status is JobStatus.FAILED
    assert failed_job.error_reason == "invalid_utf8"
    assert failed_job.active_attempt is None
    assert failed_job.processing_result is None


def test_release_retryable_claim(
    repository: DocumentJobRepository,
) -> None:
    """The active owner should be able to release retryable work."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    released_job = repository.release_retryable_claim(
        "job-001",
        attempt.attempt_id,
        released_at=BASE_TIME + timedelta(seconds=2),
    )

    assert released_job.status is JobStatus.PENDING_UPLOAD
    assert released_job.active_attempt is None
    assert released_job.attempts == 1


def test_release_retryable_claim_rejects_stale_attempt(
    repository: DocumentJobRepository,
) -> None:
    """A stale worker must not release another attempt's claim."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    with pytest.raises(JobAttemptMismatchError):
        repository.release_retryable_claim(
            "job-001",
            "stale-attempt",
            released_at=BASE_TIME + timedelta(seconds=2),
        )


def test_mark_dead_from_processing(
    repository: DocumentJobRepository,
) -> None:
    """A retry-exhausted processing job should become dead."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    dead_job = repository.mark_dead(
        "job-001",
        "retry_exhausted",
        marked_at=BASE_TIME + timedelta(seconds=2),
    )

    assert dead_job.status is JobStatus.DEAD
    assert dead_job.error_reason == "retry_exhausted"
    assert dead_job.active_attempt is None


def test_mark_dead_after_retry_release(
    repository: DocumentJobRepository,
) -> None:
    """A previously attempted retry-pending job may be reconciled dead."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )
    repository.release_retryable_claim(
        "job-001",
        attempt.attempt_id,
        released_at=BASE_TIME + timedelta(seconds=2),
    )

    dead_job = repository.mark_dead(
        "job-001",
        "retry_exhausted",
        marked_at=BASE_TIME + timedelta(seconds=3),
    )

    assert dead_job.status is JobStatus.DEAD
    assert dead_job.attempts == 1
    assert dead_job.error_reason == "retry_exhausted"


def test_mark_dead_rejects_unattempted_pending_job(
    repository: DocumentJobRepository,
) -> None:
    """A newly created job cannot be reconciled as retry-exhausted."""
    repository.create_job(make_job())

    with pytest.raises(JobStateConflictError):
        repository.mark_dead(
            "job-001",
            "retry_exhausted",
            marked_at=BASE_TIME + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    "terminal_operation",
    [
        "complete",
        "fail",
    ],
)
def test_mark_dead_protects_existing_terminal_state(
    repository: DocumentJobRepository,
    terminal_operation: str,
) -> None:
    """DLQ reconciliation must not overwrite completed outcomes."""
    repository.create_job(make_job())
    attempt = make_attempt()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    if terminal_operation == "complete":
        repository.complete_job(
            "job-001",
            attempt.attempt_id,
            make_result(),
            completed_at=BASE_TIME + timedelta(seconds=2),
        )
    else:
        repository.fail_job(
            "job-001",
            attempt.attempt_id,
            "invalid_document",
            failed_at=BASE_TIME + timedelta(seconds=2),
        )

    with pytest.raises(JobStateConflictError):
        repository.mark_dead(
            "job-001",
            "retry_exhausted",
            marked_at=BASE_TIME + timedelta(seconds=3),
        )


@pytest.mark.parametrize(
    "operation",
    [
        "complete",
        "fail",
        "release",
        "mark_dead",
    ],
)
def test_mutations_raise_not_found_for_missing_job(
    repository: DocumentJobRepository,
    operation: str,
) -> None:
    """Required lifecycle operations should fail for missing jobs."""
    with pytest.raises(JobNotFoundError):
        if operation == "complete":
            repository.complete_job(
                "missing-job",
                "attempt-001",
                make_result(),
                completed_at=BASE_TIME,
            )
        elif operation == "fail":
            repository.fail_job(
                "missing-job",
                "attempt-001",
                "invalid_document",
                failed_at=BASE_TIME,
            )
        elif operation == "release":
            repository.release_retryable_claim(
                "missing-job",
                "attempt-001",
                released_at=BASE_TIME,
            )
        else:
            repository.mark_dead(
                "missing-job",
                "retry_exhausted",
                marked_at=BASE_TIME,
            )


def test_returned_mutation_result_is_isolated(
    repository: DocumentJobRepository,
) -> None:
    """A returned mutation result must not expose internal storage."""
    repository.create_job(make_job())
    attempt = make_attempt()

    claimed_job = repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )

    claimed_job.release_for_retry(
        updated_at=BASE_TIME + timedelta(seconds=2),
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PROCESSING
    assert stored_job.active_attempt == attempt


def test_repository_preserves_validated_result(
    repository: DocumentJobRepository,
) -> None:
    """A completed job should retain the validated AI result."""
    repository.create_job(make_job())
    attempt = make_attempt()
    result = make_result()

    repository.claim_job(
        "job-001",
        attempt,
        claimed_at=BASE_TIME + timedelta(seconds=1),
    )
    repository.complete_job(
        "job-001",
        attempt.attempt_id,
        result,
        completed_at=BASE_TIME + timedelta(seconds=2),
    )

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.processing_result == result
    assert stored_job.processing_result is not result
