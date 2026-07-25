"""Integration tests for the DynamoDB document job repository."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from moto import mock_aws

from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories import (
    DynamoDBDocumentJobRepository,
    JobAlreadyExistsError,
    JobAttemptMismatchError,
    JobClaimConflictError,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)
from clouddoc.schemas import AIExtractionResult, DocumentType

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
TABLE_NAME = "clouddoc-document-jobs-test"


@pytest.fixture
def dynamodb_table(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Any]:
    """Create an isolated Moto-backed DynamoDB table."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws(
        config={
            "core": {
                "service_whitelist": ["dynamodb"],
            }
        }
    ):
        dynamodb = boto3.resource(
            "dynamodb",
            region_name="us-east-1",
        )
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {
                    "AttributeName": "pk",
                    "KeyType": "HASH",
                }
            ],
            AttributeDefinitions=[
                {
                    "AttributeName": "pk",
                    "AttributeType": "S",
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()

        yield table


@pytest.fixture
def repository(
    dynamodb_table: Any,
) -> DynamoDBDocumentJobRepository:
    """Create a repository connected to the isolated test table."""
    return DynamoDBDocumentJobRepository(
        table=dynamodb_table,
    )


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
            "amount": 10.5,
        },
        confidence=0.91,
        requires_human_review=False,
    )


def test_create_and_get_job(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A job should round-trip through the DynamoDB repository."""
    repository.create_job(make_job())

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.job_id == "job-001"
    assert stored_job.status is JobStatus.PENDING_UPLOAD
    assert stored_job.attempts == 0
    assert stored_job.correlation_context == CorrelationContext(
        request_id="request-001",
        correlation_id="correlation-001",
    )


def test_create_job_rejects_duplicate_identity(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """Conditional creation should reject an existing key."""
    repository.create_job(make_job())

    with pytest.raises(JobAlreadyExistsError):
        repository.create_job(make_job())


def test_get_job_returns_none_when_missing(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """An absent DynamoDB item should produce an absent read."""
    assert repository.get_job("missing-job") is None


def test_claim_pending_job(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A pending job should be claimed conditionally."""
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

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PROCESSING
    assert stored_job.active_attempt == attempt


def test_claim_missing_job_raises_not_found(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A missing job cannot be claimed."""
    with pytest.raises(JobNotFoundError):
        repository.claim_job(
            "missing-job",
            make_attempt(),
            claimed_at=BASE_TIME + timedelta(seconds=1),
        )


def test_claim_rejects_active_non_expired_lease(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A second worker must not steal an active lease."""
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
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """An expired lease should allow a new processing owner."""
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


def test_complete_job_with_owning_attempt(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """The current owner should complete the persisted job."""
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

    stored_job = repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.SUCCEEDED
    assert stored_job.processing_result == result


def test_complete_job_rejects_stale_attempt(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A stale worker must not complete another claim."""
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
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """The current owner should persist a terminal failure."""
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


def test_release_retryable_claim(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """The current owner should release retryable work."""
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
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A stale worker must not release another claim."""
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
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A processing job should become dead after retry exhaustion."""
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
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """A previously attempted pending job may be reconciled dead."""
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


def test_mark_dead_rejects_unattempted_job(
    repository: DynamoDBDocumentJobRepository,
) -> None:
    """An unattempted pending job is not retry-exhausted."""
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
def test_mark_dead_protects_terminal_state(
    repository: DynamoDBDocumentJobRepository,
    terminal_operation: str,
) -> None:
    """Dead reconciliation must not overwrite terminal outcomes."""
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


def test_repository_translates_unexpected_dynamodb_error(
    dynamodb_table: Any,
) -> None:
    """Unexpected AWS errors should not leak as ClientError."""
    repository = DynamoDBDocumentJobRepository(
        table=dynamodb_table,
    )
    dynamodb_table.delete()

    with pytest.raises(
        RepositoryError,
        match="failed to get document job",
    ):
        repository.get_job("job-001")
