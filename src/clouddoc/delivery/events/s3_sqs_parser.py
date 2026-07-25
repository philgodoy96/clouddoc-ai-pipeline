"""Parser for SQS batches containing S3 event notifications."""

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote_plus

from pydantic import ValidationError

from clouddoc.delivery.events.errors import (
    InvalidDocumentObjectKeyError,
    MalformedQueueEventError,
    MalformedQueueMessageError,
    MalformedS3NotificationError,
    UnexpectedS3BucketError,
    UnsupportedS3EventError,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.schemas.document_keys import (
    extract_job_id_from_document_object_key,
)


def parse_sqs_wrapped_s3_event(
    event: object,
    *,
    expected_bucket_name: str,
) -> list[UploadedDocumentEvent]:
    """Parse a Lambda SQS batch containing serialized S3 notifications."""
    normalized_bucket_name = _normalize_expected_bucket_name(expected_bucket_name)

    queue_records = _extract_records(
        event,
        error_type=MalformedQueueEventError,
        container_name="queue event",
    )

    parsed_events: list[UploadedDocumentEvent] = []

    for queue_record in queue_records:
        parsed_events.extend(
            parse_sqs_record_with_s3_notification(
                queue_record,
                expected_bucket_name=normalized_bucket_name,
            )
        )

    return parsed_events


def parse_sqs_record_with_s3_notification(
    queue_record: object,
    *,
    expected_bucket_name: str,
) -> list[UploadedDocumentEvent]:
    """Parse one SQS record containing a serialized S3 notification."""
    normalized_bucket_name = _normalize_expected_bucket_name(expected_bucket_name)

    if not isinstance(queue_record, Mapping):
        raise MalformedQueueMessageError("SQS record must be an object")

    message_id = _require_non_empty_string(
        queue_record,
        field_name="messageId",
        error_type=MalformedQueueMessageError,
        container_name="SQS record",
    )
    body = _require_non_empty_string(
        queue_record,
        field_name="body",
        error_type=MalformedQueueMessageError,
        container_name="SQS record",
    )

    try:
        notification = json.loads(body)
    except json.JSONDecodeError as error:
        raise MalformedQueueMessageError("SQS body must contain valid JSON") from error

    s3_records = _extract_records(
        notification,
        error_type=MalformedS3NotificationError,
        container_name="S3 notification",
    )

    return [
        _parse_s3_record(
            s3_record,
            message_id=message_id,
            expected_bucket_name=normalized_bucket_name,
        )
        for s3_record in s3_records
    ]


def _normalize_expected_bucket_name(expected_bucket_name: str) -> str:
    normalized_bucket_name = expected_bucket_name.strip()

    if not normalized_bucket_name:
        raise ValueError("expected_bucket_name must not be empty")

    return normalized_bucket_name


def _parse_s3_record(
    s3_record: object,
    *,
    message_id: str,
    expected_bucket_name: str,
) -> UploadedDocumentEvent:
    if not isinstance(s3_record, Mapping):
        raise MalformedS3NotificationError("S3 record must be an object")

    event_name = _require_non_empty_string(
        s3_record,
        field_name="eventName",
        error_type=MalformedS3NotificationError,
        container_name="S3 record",
    )

    if not event_name.startswith("ObjectCreated:"):
        raise UnsupportedS3EventError(f"unsupported S3 event: {event_name}")

    s3_data = _require_mapping(
        s3_record,
        field_name="s3",
        error_type=MalformedS3NotificationError,
        container_name="S3 record",
    )
    bucket_data = _require_mapping(
        s3_data,
        field_name="bucket",
        error_type=MalformedS3NotificationError,
        container_name="S3 data",
    )
    object_data = _require_mapping(
        s3_data,
        field_name="object",
        error_type=MalformedS3NotificationError,
        container_name="S3 data",
    )

    bucket_name = _require_non_empty_string(
        bucket_data,
        field_name="name",
        error_type=MalformedS3NotificationError,
        container_name="S3 bucket",
    )

    if bucket_name != expected_bucket_name:
        raise UnexpectedS3BucketError(f"unexpected S3 bucket: {bucket_name}")

    encoded_object_key = _require_non_empty_string(
        object_data,
        field_name="key",
        error_type=MalformedS3NotificationError,
        container_name="S3 object",
    )
    object_key = unquote_plus(encoded_object_key)

    try:
        job_id = extract_job_id_from_document_object_key(object_key)
    except ValueError as error:
        raise InvalidDocumentObjectKeyError(
            "invalid canonical document object key"
        ) from error

    object_size = _require_non_negative_integer(
        object_data,
        field_name="size",
        error_type=MalformedS3NotificationError,
        container_name="S3 object",
    )

    etag = _optional_non_empty_string(
        object_data,
        field_name="eTag",
        error_type=MalformedS3NotificationError,
        container_name="S3 object",
    )
    sequencer = _optional_non_empty_string(
        object_data,
        field_name="sequencer",
        error_type=MalformedS3NotificationError,
        container_name="S3 object",
    )
    version_id = _optional_non_empty_string(
        object_data,
        field_name="versionId",
        error_type=MalformedS3NotificationError,
        container_name="S3 object",
    )

    try:
        return UploadedDocumentEvent(
            message_id=message_id,
            event_name=event_name,
            bucket_name=bucket_name,
            object_key=object_key,
            job_id=job_id,
            object_size=object_size,
            etag=etag,
            sequencer=sequencer,
            version_id=version_id,
        )
    except ValidationError as error:
        raise MalformedS3NotificationError(
            "S3 record contains invalid event data"
        ) from error


def _extract_records(
    value: object,
    *,
    error_type: type[Exception],
    container_name: str,
) -> list[object]:
    if not isinstance(value, Mapping):
        raise error_type(f"{container_name} must be an object")

    records = value.get("Records")

    if not isinstance(records, list):
        raise error_type(f"{container_name} Records must be a list")

    if not records:
        raise error_type(f"{container_name} Records must not be empty")

    return records


def _require_mapping(
    container: Mapping[str, Any],
    *,
    field_name: str,
    error_type: type[Exception],
    container_name: str,
) -> Mapping[str, Any]:
    value = container.get(field_name)

    if not isinstance(value, Mapping):
        raise error_type(f"{container_name} {field_name} must be an object")

    return value


def _require_non_empty_string(
    container: Mapping[str, Any],
    *,
    field_name: str,
    error_type: type[Exception],
    container_name: str,
) -> str:
    value = container.get(field_name)

    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{container_name} {field_name} must be a non-empty string")

    return value.strip()


def _optional_non_empty_string(
    container: Mapping[str, Any],
    *,
    field_name: str,
    error_type: type[Exception],
    container_name: str,
) -> str | None:
    value = container.get(field_name)

    if value is None:
        return None

    if not isinstance(value, str) or not value.strip():
        raise error_type(
            f"{container_name} {field_name} must be a non-empty string when present"
        )

    return value.strip()


def _require_non_negative_integer(
    container: Mapping[str, Any],
    *,
    field_name: str,
    error_type: type[Exception],
    container_name: str,
) -> int:
    value = container.get(field_name)

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise error_type(
            f"{container_name} {field_name} must be a non-negative integer"
        )

    return value
