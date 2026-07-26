"""Application-backed dead-letter reconciliation processor."""

from clouddoc.application.dead_letter_processing_ports import (
    DeadLetteredDocumentProcessingError,
)
from clouddoc.application.errors import ApplicationError
from clouddoc.application.reconcile_dead_lettered_document import (
    ReconcileDeadLetteredDocument,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent


class ApplicationDeadLetteredDocumentProcessor:
    """Delegate dead-letter reconciliation to an application service."""

    def __init__(
        self,
        *,
        workflow: ReconcileDeadLetteredDocument,
    ) -> None:
        """Initialize the adapter with the reconciliation workflow."""
        self._workflow = workflow

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Reconcile one normalized dead-lettered document event."""
        try:
            self._workflow.execute(
                job_id=event.job_id,
            )
        except ApplicationError as error:
            raise DeadLetteredDocumentProcessingError(
                "failed to reconcile dead-lettered document"
            ) from error
