"""SQS-triggered Lambda handler for uploaded-document processing."""

from collections.abc import Mapping

from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
    UploadedDocumentProcessor,
)
from clouddoc.delivery.events.errors import (
    EventParsingError,
    MalformedQueueEventError,
    MalformedQueueMessageError,
)
from clouddoc.delivery.events.s3_sqs_parser import (
    parse_sqs_record_with_s3_notification,
)
from clouddoc.runtime import (
    RuntimeSettings,
    build_uploaded_document_processor,
)

_PROCESSOR: UploadedDocumentProcessor | None = None


def _get_processor(
    *,
    settings: RuntimeSettings,
) -> UploadedDocumentProcessor:
    """Build and cache the uploaded-document processor."""
    global _PROCESSOR

    if _PROCESSOR is None:
        _PROCESSOR = build_uploaded_document_processor(
            settings=settings,
        )

    return _PROCESSOR


def lambda_handler(
    event: object,
    context: object,
) -> dict[str, list[dict[str, str]]]:
    """Handle an SQS batch delivered by AWS Lambda."""
    settings = RuntimeSettings.from_environment()

    return handle(
        event,
        context,
        processor=_get_processor(
            settings=settings,
        ),
        expected_bucket_name=settings.documents_bucket_name,
    )


def handle(
    event: object,
    context: object,
    *,
    processor: UploadedDocumentProcessor,
    expected_bucket_name: str,
) -> dict[str, list[dict[str, str]]]:
    """Process each SQS record independently."""
    del context

    queue_records = _extract_queue_records(event)
    failed_message_ids: list[str] = []
    failed_message_ids_seen: set[str] = set()

    for queue_record in queue_records:
        message_id = _extract_message_id(queue_record)

        try:
            uploaded_events = parse_sqs_record_with_s3_notification(
                queue_record,
                expected_bucket_name=expected_bucket_name,
            )

            for uploaded_event in uploaded_events:
                processor.process(
                    event=uploaded_event,
                )
        except (
            EventParsingError,
            UploadedDocumentProcessingError,
            Exception,
        ):
            _append_failure(
                message_id=message_id,
                failures=failed_message_ids,
                seen=failed_message_ids_seen,
            )

    return {
        "batchItemFailures": [
            {
                "itemIdentifier": message_id,
            }
            for message_id in failed_message_ids
        ]
    }


def _extract_queue_records(
    event: object,
) -> list[object]:
    """Extract records from the outer Lambda SQS event."""
    if not isinstance(event, Mapping):
        raise MalformedQueueEventError("queue event must be an object")

    records = event.get("Records")

    if not isinstance(records, list):
        raise MalformedQueueEventError("queue event Records must be a list")

    return records


def _extract_message_id(
    queue_record: object,
) -> str:
    """Extract the SQS message ID required by partial failures."""
    if not isinstance(queue_record, Mapping):
        raise MalformedQueueMessageError("SQS record must be an object")

    message_id = queue_record.get("messageId")

    if not isinstance(message_id, str) or not message_id.strip():
        raise MalformedQueueMessageError(
            "SQS record messageId must be a non-empty string"
        )

    return message_id.strip()


def _append_failure(
    *,
    message_id: str,
    failures: list[str],
    seen: set[str],
) -> None:
    """Add one SQS failure without duplicating identifiers."""
    if message_id in seen:
        return

    seen.add(message_id)
    failures.append(message_id)
