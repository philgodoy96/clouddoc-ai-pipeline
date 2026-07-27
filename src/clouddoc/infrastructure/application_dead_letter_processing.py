"""Application-backed dead-letter reconciliation processor."""

from collections.abc import Callable
from time import perf_counter

from clouddoc.application.dead_letter_processing_ports import (
    DeadLetteredDocumentProcessingError,
)
from clouddoc.application.dead_letter_reasons import DeadLetterReason
from clouddoc.application.dead_letter_results import (
    DeadLetterReconciliationOutcome,
)
from clouddoc.application.errors import ApplicationError
from clouddoc.application.reconcile_dead_lettered_document import (
    ReconcileDeadLetteredDocument,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.observability import (
    NullOperationalLogger,
    OperationalLogger,
)

Timer = Callable[[], float]

_NULL_LOGGER = NullOperationalLogger()


class ApplicationDeadLetteredDocumentProcessor:
    """Delegate dead-letter reconciliation to an application service."""

    def __init__(
        self,
        *,
        workflow: ReconcileDeadLetteredDocument,
        logger: OperationalLogger = _NULL_LOGGER,
        timer: Timer = perf_counter,
    ) -> None:
        """Initialize the adapter with the reconciliation workflow."""
        self._workflow = workflow
        self._logger = logger
        self._timer = timer

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Reconcile one normalized dead-lettered document event.

        Emits ``reconciliation.record_completed`` for authoritative workflow
        outcomes. Retryable ``ApplicationError`` failures are translated only;
        the SQS handler owns failed-record telemetry.
        """
        started_at = self._timer()

        try:
            result = self._workflow.execute(
                job_id=event.job_id,
            )
        except ApplicationError as error:
            raise DeadLetteredDocumentProcessingError(
                "failed to reconcile dead-lettered document"
            ) from error

        duration_ms = round(max(0.0, self._timer() - started_at) * 1_000, 3)
        fields: dict[str, object] = {
            "operation": "reconcile_dead_lettered_document",
            "outcome": result.outcome.value,
            "job_id": result.job_id,
            "sqs_message_id": event.message_id,
            "duration_ms": duration_ms,
        }

        if result.outcome is DeadLetterReconciliationOutcome.DEAD_RECORDED:
            fields["failure_reason"] = (
                DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value
            )
            self._emit_completed(level="warning", fields=fields)
        elif result.outcome is (DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED):
            self._emit_completed(level="info", fields=fields)
        else:
            raise ValueError(
                f"unsupported dead-letter reconciliation outcome: {result.outcome!r}"
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
                    "reconciliation.record_completed",
                    **fields,
                )
            else:
                self._logger.warning(
                    "reconciliation.record_completed",
                    **fields,
                )
        except Exception:
            # Operational telemetry must never change acknowledgement behavior.
            return
