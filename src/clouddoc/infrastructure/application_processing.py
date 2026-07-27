"""Application-backed uploaded-document processor adapter."""

from collections.abc import Callable
from time import perf_counter

from clouddoc.application.document_processing_results import (
    DocumentProcessingOutcome,
)
from clouddoc.application.errors import ApplicationError
from clouddoc.application.process_uploaded_document import (
    ProcessUploadedDocument,
)
from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.observability import (
    NullOperationalLogger,
    OperationalLogger,
)

Timer = Callable[[], float]

_NULL_LOGGER = NullOperationalLogger()


class ApplicationUploadedDocumentProcessor:
    """Delegate uploaded-document processing to an application service."""

    def __init__(
        self,
        *,
        workflow: ProcessUploadedDocument,
        logger: OperationalLogger = _NULL_LOGGER,
        timer: Timer = perf_counter,
    ) -> None:
        """Initialize the adapter with the document-processing workflow."""
        self._workflow = workflow
        self._logger = logger
        self._timer = timer

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Process one uploaded-document event through the application workflow.

        Emits ``processing.record_completed`` for authoritative workflow
        outcomes. Retryable ``ApplicationError`` failures are translated only;
        the SQS handler owns failed-record telemetry.
        """
        started_at = self._timer()

        try:
            result = self._workflow.execute(
                event=event,
            )
        except ApplicationError as error:
            raise UploadedDocumentProcessingError(
                "failed to process uploaded document"
            ) from error

        duration_ms = round(max(0.0, self._timer() - started_at) * 1_000, 3)
        fields: dict[str, object] = {
            "operation": "process_document",
            "outcome": result.outcome.value,
            "job_id": event.job_id,
            "sqs_message_id": event.message_id,
            "duration_ms": duration_ms,
        }
        if result.attempt is not None:
            fields["processing_attempt_id"] = result.attempt.attempt_id
        if result.failure_reason is not None:
            fields["failure_reason"] = result.failure_reason.value

        if result.outcome is DocumentProcessingOutcome.PROCESSED or (
            result.outcome is DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED
        ):
            self._emit_completed(level="info", fields=fields)
        elif result.outcome is DocumentProcessingOutcome.TERMINAL_FAILURE_RECORDED:
            self._emit_completed(level="warning", fields=fields)
        else:
            raise ValueError(
                f"unsupported document processing outcome: {result.outcome!r}"
            )

    def _emit_completed(
        self,
        *,
        level: str,
        fields: dict[str, object],
    ) -> None:
        """Emit one completion event without altering acknowledgement."""
        try:
            if level == "info":
                self._logger.info(
                    "processing.record_completed",
                    **fields,
                )
            else:
                self._logger.warning(
                    "processing.record_completed",
                    **fields,
                )
        except Exception:
            # Operational telemetry must never change acknowledgement behavior.
            return
