"""Tests for DynamoDB document job item mapping."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.schemas import AIExtractionResult, DocumentType
from clouddoc.schemas.persistence_models import (
    DYNAMODB_PARTITION_KEY_ATTRIBUTE,
    ENTITY_TYPE_DOCUMENT_JOB,
    build_job_partition_key,
    document_job_from_item,
    document_job_to_item,
)

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
NON_UTC = timezone(timedelta(hours=-3))
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DYNAMODB_TERRAFORM_PATH = REPOSITORY_ROOT / "infra" / "terraform" / "dynamodb.tf"


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


def make_result() -> AIExtractionResult:
    """Create a validated AI extraction result."""
    return AIExtractionResult(
        document_type=DocumentType.CONTRACT,
        summary="A service agreement.",
        key_fields={
            "amount": 10.5,
            "parties": [
                "Example Company",
                "Customer Company",
            ],
        },
        confidence=0.91,
        requires_human_review=False,
    )


def test_builds_document_job_partition_key() -> None:
    """Job partition keys should use the approved format."""
    assert build_job_partition_key("job-001") == "JOB#job-001"


def test_dynamodb_partition_key_attribute_is_uppercase_pk() -> None:
    """The physical DynamoDB partition-key attribute must match Terraform."""
    assert DYNAMODB_PARTITION_KEY_ATTRIBUTE == "PK"


def test_application_partition_key_matches_terraform_contract() -> None:
    """Application and Terraform must share the uppercase PK attribute name."""
    terraform_source = DYNAMODB_TERRAFORM_PATH.read_text(encoding="utf-8")

    assert 'hash_key                    = "PK"' in terraform_source
    assert 'name = "PK"' in terraform_source
    assert DYNAMODB_PARTITION_KEY_ATTRIBUTE == "PK"


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        "   ",
    ],
)
def test_partition_key_rejects_empty_job_id(
    job_id: str,
) -> None:
    """A partition key requires a valid job identity."""
    with pytest.raises(
        InvalidDomainValueError,
        match="job_id must not be empty",
    ):
        build_job_partition_key(job_id)


def test_serializes_pending_job() -> None:
    """A new job should serialize without processing state."""
    item = document_job_to_item(make_job())

    assert item == {
        "PK": "JOB#job-001",
        "entity_type": ENTITY_TYPE_DOCUMENT_JOB,
        "job_id": "job-001",
        "status": "pending_upload",
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "created_at": BASE_TIME.isoformat(),
        "updated_at": BASE_TIME.isoformat(),
        "attempts": 0,
        "active_attempt_id": None,
        "active_attempt_started_at": None,
        "active_attempt_lease_expires_at": None,
        "processing_result": None,
        "error_reason": None,
    }
    assert "pk" not in item
    assert DYNAMODB_PARTITION_KEY_ATTRIBUTE in item
    assert item[DYNAMODB_PARTITION_KEY_ATTRIBUTE] == "JOB#job-001"
    partition_key_attributes = [key for key in item if key.casefold() == "pk"]
    assert partition_key_attributes == ["PK"]


def test_serializes_processing_job() -> None:
    """An active claim should serialize all lease fields."""
    job = make_job()
    attempt = make_attempt()
    claimed_at = BASE_TIME + timedelta(seconds=1)

    job.start_processing(
        attempt,
        updated_at=claimed_at,
    )

    item = document_job_to_item(job)

    assert item["status"] == "processing"
    assert item["attempts"] == 1
    assert item["active_attempt_id"] == "attempt-001"
    assert item["active_attempt_started_at"] == attempt.started_at.isoformat()
    assert (
        item["active_attempt_lease_expires_at"] == attempt.lease_expires_at.isoformat()
    )


def test_serializes_succeeded_job_with_dynamodb_numbers() -> None:
    """Floating-point result values should become Decimal values."""
    job = make_job()
    attempt = make_attempt()

    job.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    job.mark_succeeded(
        make_result(),
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    item = document_job_to_item(job)
    result = item["processing_result"]

    assert isinstance(result, dict)
    assert result["confidence"] == Decimal("0.91")
    assert result["key_fields"]["amount"] == Decimal("10.5")
    assert item["active_attempt_id"] is None
    assert item["error_reason"] is None


def test_serializes_failed_job() -> None:
    """Terminal failure state should retain its normalized reason."""
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

    item = document_job_to_item(job)

    assert item["status"] == "failed"
    assert item["processing_result"] is None
    assert item["error_reason"] == "invalid_utf8"


def test_round_trip_pending_job() -> None:
    """A pending job should survive serialization and reconstruction."""
    original = make_job()

    reconstructed = document_job_from_item(document_job_to_item(original))

    assert reconstructed.job_id == original.job_id
    assert reconstructed.status is JobStatus.PENDING_UPLOAD
    assert reconstructed.correlation_context == original.correlation_context
    assert reconstructed.created_at == original.created_at
    assert reconstructed.updated_at == original.updated_at
    assert reconstructed.attempts == 0


def test_round_trip_processing_job() -> None:
    """A processing job should retain its active attempt."""
    original = make_job()
    attempt = make_attempt()

    original.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    reconstructed = document_job_from_item(document_job_to_item(original))

    assert reconstructed.status is JobStatus.PROCESSING
    assert reconstructed.attempts == 1
    assert reconstructed.active_attempt == attempt


def test_round_trip_succeeded_job() -> None:
    """A completed job should retain its validated AI result."""
    original = make_job()
    attempt = make_attempt()
    result = make_result()

    original.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    original.mark_succeeded(
        result,
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    reconstructed = document_job_from_item(document_job_to_item(original))

    assert reconstructed.status is JobStatus.SUCCEEDED
    assert reconstructed.processing_result == result
    assert isinstance(
        reconstructed.processing_result,
        AIExtractionResult,
    )


def test_round_trip_dead_job() -> None:
    """A retry-exhausted job should retain its error context."""
    original = make_job()
    attempt = make_attempt()

    original.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    original.mark_dead(
        "retry_exhausted",
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    reconstructed = document_job_from_item(document_job_to_item(original))

    assert reconstructed.status is JobStatus.DEAD
    assert reconstructed.error_reason == "retry_exhausted"
    assert reconstructed.active_attempt is None


def test_rejects_unexpected_entity_type() -> None:
    """Unrelated DynamoDB entities must not be parsed as jobs."""
    item = document_job_to_item(make_job())
    item["entity_type"] = "other_entity"

    with pytest.raises(
        InvalidDomainValueError,
        match="persisted item is not a document job",
    ):
        document_job_from_item(item)


def test_rejects_partition_key_identity_mismatch() -> None:
    """The item key must match its declared job identity."""
    item = document_job_to_item(make_job())
    item[DYNAMODB_PARTITION_KEY_ATTRIBUTE] = "JOB#different-job"

    with pytest.raises(
        InvalidDomainValueError,
        match="partition key does not match job_id",
    ):
        document_job_from_item(item)


def test_rejects_lowercase_only_partition_key() -> None:
    """Lowercase pk alone is not a valid physical partition key."""
    item = document_job_to_item(make_job())
    item["pk"] = item.pop(DYNAMODB_PARTITION_KEY_ATTRIBUTE)

    with pytest.raises(
        InvalidDomainValueError,
        match="missing required field: PK",
    ):
        document_job_from_item(item)


def test_deserializes_uppercase_partition_key() -> None:
    """Deserialization must accept the deployed uppercase PK attribute."""
    item = document_job_to_item(make_job())

    assert DYNAMODB_PARTITION_KEY_ATTRIBUTE in item
    assert "pk" not in item

    reconstructed = document_job_from_item(item)

    assert reconstructed.job_id == "job-001"
    assert reconstructed.status is JobStatus.PENDING_UPLOAD


def test_rejects_missing_required_field() -> None:
    """Incomplete persisted jobs should fail explicitly."""
    item = document_job_to_item(make_job())
    del item["correlation_id"]

    with pytest.raises(
        InvalidDomainValueError,
        match="missing required field: correlation_id",
    ):
        document_job_from_item(item)


def test_rejects_unsupported_status() -> None:
    """Persisted lifecycle states must be recognized."""
    item = document_job_to_item(make_job())
    item["status"] = "queued"

    with pytest.raises(
        InvalidDomainValueError,
        match="unsupported status",
    ):
        document_job_from_item(item)


def test_rejects_incomplete_active_attempt() -> None:
    """Active attempt fields must be present as one complete group."""
    item = document_job_to_item(make_job())
    item["status"] = "processing"
    item["attempts"] = 1
    item["active_attempt_id"] = "attempt-001"

    with pytest.raises(
        InvalidDomainValueError,
        match="persisted active attempt is incomplete",
    ):
        document_job_from_item(item)


def test_rejects_invalid_processing_result() -> None:
    """Persisted AI results must still satisfy the output schema."""
    item = document_job_to_item(make_job())
    item["status"] = "succeeded"
    item["attempts"] = 1
    item["processing_result"] = {
        "document_type": "unsupported",
        "summary": "Summary",
        "key_fields": {},
        "confidence": Decimal("0.9"),
        "requires_human_review": False,
    }

    with pytest.raises(
        InvalidDomainValueError,
        match="persisted processing_result is invalid",
    ):
        document_job_from_item(item)


def test_rejects_generic_unvalidated_result() -> None:
    """Only the validated AI result may cross persistence."""
    job = make_job()
    attempt = make_attempt()

    job.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    job.mark_succeeded(
        {"document_type": "contract"},
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="processing_result must be an AIExtractionResult",
    ):
        document_job_to_item(job)


def test_accepts_integral_decimal_attempts() -> None:
    """DynamoDB integral Decimals should round-trip as Python ints."""
    item = document_job_to_item(make_job())
    item["attempts"] = Decimal("3")
    item["status"] = "failed"
    item["error_reason"] = "retry_exhausted"

    reconstructed = document_job_from_item(item)

    assert reconstructed.attempts == 3


@pytest.mark.parametrize(
    "attempts",
    [
        "3",
        Decimal("3.9"),
        3.0,
        True,
        -1,
    ],
)
def test_rejects_invalid_attempts(
    attempts: Any,
) -> None:
    """Attempt counts must be strict non-negative integers."""
    item = document_job_to_item(make_job())
    item["attempts"] = attempts

    with pytest.raises(
        InvalidDomainValueError,
        match="attempts must be a non-negative integer",
    ):
        document_job_from_item(item)


def test_rejects_null_job_id() -> None:
    """Persisted job identity must remain a concrete string."""
    item = document_job_to_item(make_job())
    item["job_id"] = None

    with pytest.raises(
        InvalidDomainValueError,
        match="job_id must be a non-empty string",
    ):
        document_job_from_item(item)


def test_rejects_null_request_id() -> None:
    """Correlation request identifiers must not be coerced from null."""
    item = document_job_to_item(make_job())
    item["request_id"] = None

    with pytest.raises(
        InvalidDomainValueError,
        match="request_id must be a non-empty string",
    ):
        document_job_from_item(item)


def test_rejects_whitespace_correlation_id() -> None:
    """Whitespace-only correlation identifiers are not valid strings."""
    item = document_job_to_item(make_job())
    item["correlation_id"] = "   "

    with pytest.raises(
        InvalidDomainValueError,
        match="correlation_id must be a non-empty string",
    ):
        document_job_from_item(item)


def test_accepts_absent_active_attempt_group() -> None:
    """All-null active attempt fields remain a valid absent attempt."""
    item = document_job_to_item(make_job())

    reconstructed = document_job_from_item(item)

    assert reconstructed.active_attempt is None
    assert item["active_attempt_id"] is None
    assert item["active_attempt_started_at"] is None
    assert item["active_attempt_lease_expires_at"] is None


def test_rejects_partial_active_attempt_with_invalid_id() -> None:
    """A partial attempt group with a bad ID is still rejected."""
    item = document_job_to_item(make_job())
    item["status"] = "processing"
    item["attempts"] = 1
    item["active_attempt_id"] = ""
    item["active_attempt_started_at"] = (BASE_TIME + timedelta(seconds=1)).isoformat()
    item["active_attempt_lease_expires_at"] = (
        BASE_TIME + timedelta(minutes=5)
    ).isoformat()

    with pytest.raises(
        InvalidDomainValueError,
        match="active_attempt_id must be a non-empty string",
    ):
        document_job_from_item(item)


def test_rejects_partial_active_attempt_with_missing_id() -> None:
    """Missing attempt ID with other fields present is incomplete."""
    item = document_job_to_item(make_job())
    item["status"] = "processing"
    item["attempts"] = 1
    item["active_attempt_id"] = None
    item["active_attempt_started_at"] = (BASE_TIME + timedelta(seconds=1)).isoformat()
    item["active_attempt_lease_expires_at"] = (
        BASE_TIME + timedelta(minutes=5)
    ).isoformat()

    with pytest.raises(
        InvalidDomainValueError,
        match="persisted active attempt is incomplete",
    ):
        document_job_from_item(item)


def test_rejects_naive_created_at() -> None:
    """Persisted creation timestamps must carry timezone information."""
    item = document_job_to_item(make_job())
    item["created_at"] = BASE_TIME.replace(tzinfo=None).isoformat()

    with pytest.raises(
        InvalidDomainValueError,
        match="created_at must be timezone-aware",
    ):
        document_job_from_item(item)


def test_rejects_non_utc_created_at() -> None:
    """Persisted creation timestamps must use UTC."""
    item = document_job_to_item(make_job())
    item["created_at"] = datetime(
        2026,
        7,
        25,
        12,
        0,
        tzinfo=NON_UTC,
    ).isoformat()

    with pytest.raises(
        InvalidDomainValueError,
        match="created_at must use UTC",
    ):
        document_job_from_item(item)


def test_rejects_naive_active_attempt_timestamps() -> None:
    """Active attempt lease timestamps must be timezone-aware."""
    attempt = make_attempt()
    item = document_job_to_item(make_job())
    item["status"] = "processing"
    item["attempts"] = 1
    item["active_attempt_id"] = attempt.attempt_id
    item["active_attempt_started_at"] = attempt.started_at.replace(
        tzinfo=None
    ).isoformat()
    item["active_attempt_lease_expires_at"] = attempt.lease_expires_at.isoformat()

    with pytest.raises(
        InvalidDomainValueError,
        match="active_attempt_started_at must be timezone-aware",
    ):
        document_job_from_item(item)


def test_utc_timestamps_round_trip() -> None:
    """Timezone-aware UTC timestamps should survive mapping unchanged."""
    original = make_job()
    attempt = make_attempt()

    original.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    reconstructed = document_job_from_item(document_job_to_item(original))

    assert reconstructed.created_at == original.created_at
    assert reconstructed.updated_at == original.updated_at
    assert reconstructed.active_attempt is not None
    assert reconstructed.active_attempt.started_at == attempt.started_at
    assert reconstructed.active_attempt.lease_expires_at == attempt.lease_expires_at
