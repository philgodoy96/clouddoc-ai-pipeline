"""Testable SQS batch handler for dead-letter reconciliation."""

from collections.abc import Callable, Mapping
from time import perf_counter

from clouddoc.application.dead_letter_processing_ports import (
    DeadLetteredDocumentProcessingError,
    DeadLetteredDocumentProcessor,
)
from clouddoc.delivery.events.errors import (
    EventParsingError,
    MalformedQueueEventError,
    MalformedQueueMessageError,
)
from clouddoc.delivery.events.s3_sqs_parser import (
    parse_sqs_record_with_s3_notification,
)
from clouddoc.observability import (
    NullOperationalLogger,
    OperationalLogger,
    StandardOperationalLogger,
)
from clouddoc.runtime import (
    RuntimeSettings,
    build_dead_lettered_document_processor,
)

Timer = Callable[[], float]

_NULL_LOGGER = NullOperationalLogger()
_LOGGER = StandardOperationalLogger(component="dead-letter-reconciler")
_PROCESSOR: DeadLetteredDocumentProcessor | None = None


def _get_processor(
    *,
    settings: RuntimeSettings,
    logger: OperationalLogger,
) -> DeadLetteredDocumentProcessor:
    """Build and cache the dead-letter reconciliation processor."""
    global _PROCESSOR

    if _PROCESSOR is None:
        _PROCESSOR = build_dead_lettered_document_processor(
            settings=settings,
            operational_logger=logger,
        )

    return _PROCESSOR


def lambda_handler(
    event: object,
    context: object,
) -> dict[str, list[dict[str, str]]]:
    """Handle a dead-letter SQS batch delivered by AWS Lambda."""
    settings = RuntimeSettings.from_environment()

    return handle(
        event,
        context,
        processor=_get_processor(
            settings=settings,
            logger=_LOGGER,
        ),
        expected_bucket_name=settings.documents_bucket_name,
        logger=_LOGGER,
    )


def handle(
    event: object,
    context: object,
    *,
    processor: DeadLetteredDocumentProcessor,
    expected_bucket_name: str,
    logger: OperationalLogger = _NULL_LOGGER,
    timer: Timer = perf_counter,
) -> dict[str, list[dict[str, str]]]:
    """Reconcile each dead-lettered SQS record independently.

    Handlers own failed-record and batch-summary telemetry. Authoritative
    successful completions are emitted by the production adapter.
    """
    del context
    batch_started_at = timer()

    try:
        queue_records = _extract_queue_records(event)
    except MalformedQueueEventError as error:
        _emit_safely(
            logger=logger,
            level="error",
            event_name="reconciliation.batch_completed",
            operation="reconcile_dead_letter_batch",
            outcome="event_rejected",
            error_code="malformed_queue_event",
            exception_type=type(error).__name__,
            processed_record_count=0,
            failed_record_count=0,
            duration_ms=_duration_ms(
                timer=timer,
                started_at=batch_started_at,
            ),
        )
        raise

    failed_message_ids: list[str] = []
    failed_message_ids_seen: set[str] = set()

    for handled_record_count, queue_record in enumerate(queue_records):
        try:
            message_id = _extract_message_id(queue_record)
        except MalformedQueueMessageError as error:
            _emit_safely(
                logger=logger,
                level="error",
                event_name="reconciliation.batch_completed",
                operation="reconcile_dead_letter_batch",
                outcome="event_rejected",
                error_code="malformed_queue_message",
                exception_type=type(error).__name__,
                batch_size=len(queue_records),
                processed_record_count=(handled_record_count - len(failed_message_ids)),
                failed_record_count=len(failed_message_ids),
                duration_ms=_duration_ms(
                    timer=timer,
                    started_at=batch_started_at,
                ),
            )
            raise

        record_started_at = timer()
        job_id: str | None = None

        try:
            uploaded_events = parse_sqs_record_with_s3_notification(
                queue_record,
                expected_bucket_name=expected_bucket_name,
            )

            for uploaded_event in uploaded_events:
                job_id = uploaded_event.job_id
                processor.process(
                    event=uploaded_event,
                )
        except EventParsingError as error:
            _emit_record_failed(
                logger=logger,
                timer=timer,
                started_at=record_started_at,
                level="warning",
                outcome="event_rejected",
                error_code="dead_letter_event_parsing_error",
                error=error,
                sqs_message_id=message_id,
                job_id=None,
            )
            _append_failure(
                message_id=message_id,
                failures=failed_message_ids,
                seen=failed_message_ids_seen,
            )
        except DeadLetteredDocumentProcessingError as error:
            _emit_record_failed(
                logger=logger,
                timer=timer,
                started_at=record_started_at,
                level="error",
                outcome="retryable_failure",
                error_code="dead_lettered_document_processing_error",
                error=error,
                sqs_message_id=message_id,
                job_id=job_id,
            )
            _append_failure(
                message_id=message_id,
                failures=failed_message_ids,
                seen=failed_message_ids_seen,
            )
        except Exception as error:
            _emit_record_failed(
                logger=logger,
                timer=timer,
                started_at=record_started_at,
                level="error",
                outcome="retryable_failure",
                error_code="unexpected_reconciliation_error",
                error=error,
                sqs_message_id=message_id,
                job_id=job_id,
            )
            _append_failure(
                message_id=message_id,
                failures=failed_message_ids,
                seen=failed_message_ids_seen,
            )

    failed_record_count = len(failed_message_ids)
    processed_record_count = len(queue_records) - failed_record_count
    batch_outcome = "completed_with_failures" if failed_record_count else "succeeded"
    _emit_safely(
        logger=logger,
        level="warning" if failed_record_count else "info",
        event_name="reconciliation.batch_completed",
        operation="reconcile_dead_letter_batch",
        outcome=batch_outcome,
        batch_size=len(queue_records),
        processed_record_count=processed_record_count,
        failed_record_count=failed_record_count,
        duration_ms=_duration_ms(
            timer=timer,
            started_at=batch_started_at,
        ),
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


def _duration_ms(
    *,
    timer: Timer,
    started_at: float,
) -> float:
    """Calculate a non-negative millisecond duration from an injectable timer."""
    return round(max(0.0, timer() - started_at) * 1_000, 3)


def _emit_safely(
    logger: OperationalLogger,
    *,
    level: str,
    event_name: str,
    **fields: object,
) -> None:
    """Emit one operational event without affecting processing behavior."""
    try:
        if level == "info":
            logger.info(event_name, **fields)
        elif level == "warning":
            logger.warning(event_name, **fields)
        else:
            logger.error(event_name, **fields)
    except Exception:
        # Operational telemetry must never change acknowledgement behavior.
        return


def _emit_record_failed(
    *,
    logger: OperationalLogger,
    timer: Timer,
    started_at: float,
    level: str,
    outcome: str,
    error_code: str,
    error: BaseException,
    sqs_message_id: str,
    job_id: str | None,
) -> None:
    """Emit one safe failed-record event for a reportable SQS message."""
    fields: dict[str, object] = {
        "operation": "reconcile_dead_lettered_document",
        "outcome": outcome,
        "error_code": error_code,
        "exception_type": type(error).__name__,
        "retryable": True,
        "sqs_message_id": sqs_message_id,
        "duration_ms": _duration_ms(
            timer=timer,
            started_at=started_at,
        ),
    }
    if job_id is not None:
        fields["job_id"] = job_id

    _emit_safely(
        logger,
        level=level,
        event_name="reconciliation.record_failed",
        **fields,
    )
