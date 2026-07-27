"""Integration tests for concurrent document-processing claims."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from typing import Any

import boto3
import pytest
from moto import mock_aws

from clouddoc.application import (
    ProcessingStartOutcome,
    ProcessingStartResult,
)
from clouddoc.application.start_document_processing import (
    StartDocumentProcessing,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
)
from clouddoc.repositories import (
    DynamoDBDocumentJobRepository,
)

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
CLAIMED_AT = BASE_TIME + timedelta(seconds=1)
LEASE_DURATION = timedelta(minutes=5)
TABLE_NAME = "clouddoc-processing-concurrency-test"


# Moto does not reliably preserve DynamoDB conditional-write atomicity
# across concurrent threads. Serialize put_item calls in this fixture so
# the integration test reproduces the per-item atomicity guaranteed by
# DynamoDB rather than testing a race condition in the emulator.
# Do not reuse this wrapper in tests that measure parallelism across
# independent items.
class AtomicConditionalTable:
    """Serialize put_item for this concurrency fixture only."""

    def __init__(
        self,
        table: Any,
    ) -> None:
        """Wrap one DynamoDB table resource."""
        self._table = table
        self._write_lock = Lock()

    def put_item(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Forward put_item unchanged under an exclusive write lock."""
        with self._write_lock:
            return self._table.put_item(
                *args,
                **kwargs,
            )

    def __getattr__(
        self,
        name: str,
    ) -> Any:
        """Delegate remaining table attributes and methods to Moto."""
        return getattr(
            self._table,
            name,
        )


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
        attempt_id: str,
    ) -> None:
        """Initialize the generator."""
        self._attempt_id = attempt_id
        self.calls = 0

    def generate(self) -> str:
        """Return the configured attempt identifier."""
        self.calls += 1
        return self._attempt_id


class CoordinatedDynamoDBDocumentJobRepository(DynamoDBDocumentJobRepository):
    """DynamoDB repository that coordinates its first authoritative read."""

    def __init__(
        self,
        *,
        table: Any,
        initial_read_barrier: Barrier,
    ) -> None:
        """Initialize the repository with one shared race barrier."""
        super().__init__(
            table=table,
        )
        self._initial_read_barrier = initial_read_barrier
        self._coordinate_initial_read = True

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob | None:
        """Pause after the first read so both workers observe pending state."""
        job = super().get_job(job_id)

        if self._coordinate_initial_read:
            self._coordinate_initial_read = False
            self._initial_read_barrier.wait(
                timeout=5,
            )

        return job


@pytest.fixture
def dynamodb_table(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Any]:
    """Create an isolated Moto-backed DynamoDB table."""
    monkeypatch.setenv(
        "AWS_ACCESS_KEY_ID",
        "testing",
    )
    monkeypatch.setenv(
        "AWS_SECRET_ACCESS_KEY",
        "testing",
    )
    monkeypatch.setenv(
        "AWS_SESSION_TOKEN",
        "testing",
    )
    monkeypatch.setenv(
        "AWS_DEFAULT_REGION",
        "us-east-1",
    )

    with mock_aws(
        config={
            "core": {
                "service_whitelist": [
                    "dynamodb",
                ],
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

        yield AtomicConditionalTable(table)


def make_pending_job() -> DocumentJob:
    """Create one authoritative pending document job."""
    return DocumentJob(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def make_event() -> UploadedDocumentEvent:
    """Create one uploaded-document event for the authoritative job."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key="documents/job-001/source.txt",
        job_id="job-001",
        object_size=128,
        etag="etag-001",
        sequencer="sequencer-001",
        version_id=None,
    )


def make_service(
    *,
    repository: DynamoDBDocumentJobRepository,
    attempt_id_generator: FixedAttemptIdGenerator,
) -> StartDocumentProcessing:
    """Create one processing-start worker."""
    return StartDocumentProcessing(
        repository=repository,
        clock=FixedClock(CLAIMED_AT),
        attempt_id_generator=attempt_id_generator,
        lease_duration=LEASE_DURATION,
    )


def test_concurrent_processing_starts_return_one_claim_and_one_active(
    dynamodb_table: Any,
) -> None:
    """Two workers should return one claim and one active-processing outcome."""
    authoritative_repository = DynamoDBDocumentJobRepository(
        table=dynamodb_table,
    )
    authoritative_repository.create_job(make_pending_job())

    initial_read_barrier = Barrier(2)

    first_repository = CoordinatedDynamoDBDocumentJobRepository(
        table=dynamodb_table,
        initial_read_barrier=initial_read_barrier,
    )
    second_repository = CoordinatedDynamoDBDocumentJobRepository(
        table=dynamodb_table,
        initial_read_barrier=initial_read_barrier,
    )

    first_generator = FixedAttemptIdGenerator("attempt-worker-001")
    second_generator = FixedAttemptIdGenerator("attempt-worker-002")

    first_service = make_service(
        repository=first_repository,
        attempt_id_generator=first_generator,
    )
    second_service = make_service(
        repository=second_repository,
        attempt_id_generator=second_generator,
    )

    event = make_event()

    with ThreadPoolExecutor(
        max_workers=2,
    ) as executor:
        first_future = executor.submit(
            first_service.execute,
            event=event,
        )
        second_future = executor.submit(
            second_service.execute,
            event=event,
        )

        results = [
            first_future.result(
                timeout=10,
            ),
            second_future.result(
                timeout=10,
            ),
        ]

    assert all(isinstance(result, ProcessingStartResult) for result in results)
    outcomes = [result.outcome for result in results]
    assert outcomes.count(ProcessingStartOutcome.CLAIM_ACQUIRED) == 1
    assert outcomes.count(ProcessingStartOutcome.PROCESSING_ALREADY_ACTIVE) == 1
    assert outcomes.count(ProcessingStartOutcome.EFFECT_ALREADY_APPLIED) == 0

    stored_job = authoritative_repository.get_job("job-001")

    assert stored_job is not None
    assert stored_job.status is JobStatus.PROCESSING
    assert stored_job.attempts == 1
    assert stored_job.active_attempt is not None
    assert stored_job.active_attempt.attempt_id in {
        "attempt-worker-001",
        "attempt-worker-002",
    }
    assert stored_job.active_attempt.started_at == CLAIMED_AT
    assert stored_job.active_attempt.lease_expires_at == (CLAIMED_AT + LEASE_DURATION)

    claim_result = next(
        result
        for result in results
        if result.outcome is ProcessingStartOutcome.CLAIM_ACQUIRED
    )
    assert claim_result.attempt is not None
    assert claim_result.attempt == stored_job.active_attempt
    assert claim_result.correlation_id == "correlation-001"

    active_result = next(
        result
        for result in results
        if result.outcome is ProcessingStartOutcome.PROCESSING_ALREADY_ACTIVE
    )
    assert active_result.attempt is None
    assert active_result.correlation_id is None

    assert first_generator.calls == 1
    assert second_generator.calls == 1
