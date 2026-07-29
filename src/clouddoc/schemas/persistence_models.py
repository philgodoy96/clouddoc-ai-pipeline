"""DynamoDB item mapping for persisted document jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.schemas.ai_output import AIExtractionResult

ENTITY_TYPE_DOCUMENT_JOB = "document_job"
JOB_PARTITION_KEY_PREFIX = "JOB#"
DYNAMODB_PARTITION_KEY_ATTRIBUTE = "PK"


def build_job_partition_key(job_id: str) -> str:
    """Build the DynamoDB partition key for a document job."""
    normalized_job_id = job_id.strip()

    if not normalized_job_id:
        raise InvalidDomainValueError("job_id must not be empty")

    return f"{JOB_PARTITION_KEY_PREFIX}{normalized_job_id}"


def document_job_to_item(
    job: DocumentJob,
) -> dict[str, Any]:
    """Serialize a document job into a DynamoDB-compatible item."""
    active_attempt = job.active_attempt
    processing_result = job.processing_result

    if processing_result is not None and not isinstance(
        processing_result, AIExtractionResult
    ):
        raise InvalidDomainValueError("processing_result must be an AIExtractionResult")

    return {
        DYNAMODB_PARTITION_KEY_ATTRIBUTE: build_job_partition_key(job.job_id),
        "entity_type": ENTITY_TYPE_DOCUMENT_JOB,
        "job_id": job.job_id,
        "status": job.status.value,
        "request_id": job.correlation_context.request_id,
        "correlation_id": job.correlation_context.correlation_id,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "attempts": job.attempts,
        "active_attempt_id": (
            active_attempt.attempt_id if active_attempt is not None else None
        ),
        "active_attempt_started_at": (
            active_attempt.started_at.isoformat()
            if active_attempt is not None
            else None
        ),
        "active_attempt_lease_expires_at": (
            active_attempt.lease_expires_at.isoformat()
            if active_attempt is not None
            else None
        ),
        "processing_result": (
            _to_dynamodb_value(processing_result.model_dump(mode="json"))
            if processing_result is not None
            else None
        ),
        "error_reason": job.error_reason,
    }


def document_job_from_item(
    item: dict[str, Any],
) -> DocumentJob:
    """Reconstruct a document job from a DynamoDB item."""
    _validate_entity_type(item)
    _validate_partition_key(item)

    status = _parse_status(item)
    active_attempt = _parse_active_attempt(item)
    processing_result = _parse_processing_result(item)

    try:
        attempts = _parse_attempts(item["attempts"])

        return DocumentJob.rehydrate(
            job_id=_parse_required_string(
                item["job_id"],
                field_name="job_id",
            ),
            correlation_context=CorrelationContext(
                request_id=_parse_required_string(
                    item["request_id"],
                    field_name="request_id",
                ),
                correlation_id=_parse_required_string(
                    item["correlation_id"],
                    field_name="correlation_id",
                ),
            ),
            created_at=_parse_datetime(
                item["created_at"],
                field_name="created_at",
            ),
            updated_at=_parse_datetime(
                item["updated_at"],
                field_name="updated_at",
            ),
            status=status,
            attempts=attempts,
            active_attempt=active_attempt,
            processing_result=processing_result,
            error_reason=_parse_optional_string(
                item.get("error_reason"),
                field_name="error_reason",
            ),
        )
    except KeyError as error:
        missing_field = str(error.args[0])

        raise InvalidDomainValueError(
            f"persisted job is missing required field: {missing_field}"
        ) from error
    except (TypeError, ValueError) as error:
        raise InvalidDomainValueError(
            "persisted job contains an invalid value"
        ) from error


def _validate_entity_type(item: dict[str, Any]) -> None:
    """Require the expected persisted entity type."""
    entity_type = item.get("entity_type")

    if entity_type != ENTITY_TYPE_DOCUMENT_JOB:
        raise InvalidDomainValueError("persisted item is not a document job")


def _validate_partition_key(item: dict[str, Any]) -> None:
    """Require the partition key to match the persisted job identity."""
    try:
        job_id = _parse_required_string(
            item["job_id"],
            field_name="job_id",
        )
        partition_key = _parse_required_string(
            item[DYNAMODB_PARTITION_KEY_ATTRIBUTE],
            field_name=DYNAMODB_PARTITION_KEY_ATTRIBUTE,
        )
    except KeyError as error:
        missing_field = str(error.args[0])

        raise InvalidDomainValueError(
            f"persisted job is missing required field: {missing_field}"
        ) from error

    expected_partition_key = build_job_partition_key(job_id)

    if partition_key != expected_partition_key:
        raise InvalidDomainValueError(
            "persisted job partition key does not match job_id"
        )


def _parse_status(item: dict[str, Any]) -> JobStatus:
    """Parse the persisted job status."""
    try:
        status_value = _parse_required_string(
            item["status"],
            field_name="status",
        )
        return JobStatus(status_value)
    except KeyError as error:
        raise InvalidDomainValueError(
            "persisted job is missing required field: status"
        ) from error
    except ValueError as error:
        raise InvalidDomainValueError(
            "persisted job contains an unsupported status"
        ) from error


def _parse_active_attempt(
    item: dict[str, Any],
) -> ProcessingAttempt | None:
    """Reconstruct the active processing attempt when present."""
    attempt_id = item.get("active_attempt_id")
    started_at = item.get("active_attempt_started_at")
    lease_expires_at = item.get("active_attempt_lease_expires_at")

    values = (
        attempt_id,
        started_at,
        lease_expires_at,
    )

    if all(value is None for value in values):
        return None

    if any(value is None for value in values):
        raise InvalidDomainValueError("persisted active attempt is incomplete")

    return ProcessingAttempt(
        attempt_id=_parse_required_string(
            attempt_id,
            field_name="active_attempt_id",
        ),
        started_at=_parse_datetime(
            started_at,
            field_name="active_attempt_started_at",
        ),
        lease_expires_at=_parse_datetime(
            lease_expires_at,
            field_name="active_attempt_lease_expires_at",
        ),
    )


def _parse_processing_result(
    item: dict[str, Any],
) -> AIExtractionResult | None:
    """Reconstruct the validated processing result when present."""
    raw_result = item.get("processing_result")

    if raw_result is None:
        return None

    if not isinstance(raw_result, dict):
        raise InvalidDomainValueError("persisted processing_result must be an object")

    try:
        return AIExtractionResult.model_validate(_from_dynamodb_value(raw_result))
    except ValueError as error:
        raise InvalidDomainValueError(
            "persisted processing_result is invalid"
        ) from error


def _parse_attempts(value: object) -> int:
    """Parse a strictly typed non-negative attempt count."""
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise InvalidDomainValueError("attempts must be a non-negative integer")

    if isinstance(value, Decimal):
        if value != value.to_integral_value() or value < 0:
            raise InvalidDomainValueError("attempts must be a non-negative integer")

        return int(value)

    if value < 0:
        raise InvalidDomainValueError("attempts must be a non-negative integer")

    return value


def _parse_required_string(
    value: object,
    *,
    field_name: str,
) -> str:
    """Parse a required non-empty persisted string."""
    if not isinstance(value, str) or not value.strip():
        raise InvalidDomainValueError(f"{field_name} must be a non-empty string")

    return value


def _parse_datetime(
    value: object,
    *,
    field_name: str,
) -> datetime:
    """Parse one ISO-8601 persisted datetime in UTC."""
    if not isinstance(value, str):
        raise InvalidDomainValueError(f"{field_name} must be an ISO-8601 string")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise InvalidDomainValueError(
            f"{field_name} must be a valid ISO-8601 datetime"
        ) from error

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvalidDomainValueError(f"{field_name} must be timezone-aware")

    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise InvalidDomainValueError(f"{field_name} must use UTC")

    return parsed


def _parse_optional_string(
    value: object,
    *,
    field_name: str,
) -> str | None:
    """Parse an optional persisted string."""
    if value is None:
        return None

    if not isinstance(value, str):
        raise InvalidDomainValueError(f"{field_name} must be a string or null")

    return value


def _to_dynamodb_value(value: object) -> object:
    """Convert JSON-compatible values into DynamoDB resource values."""
    if isinstance(value, float):
        return Decimal(str(value))

    if isinstance(value, list):
        return [_to_dynamodb_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _to_dynamodb_value(nested_value)
            for key, nested_value in value.items()
        }

    return value


def _from_dynamodb_value(value: object) -> object:
    """Convert DynamoDB numeric values into JSON-compatible values."""
    # Persisted AI output originated as JSON-compatible int/float values.
    # Decimal here is only DynamoDB transport; exact-decimal business values
    # such as money need a dedicated typed schema, not generic key_fields.
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)

        return float(value)

    if isinstance(value, list):
        return [_from_dynamodb_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _from_dynamodb_value(nested_value)
            for key, nested_value in value.items()
        }

    return value
