"""Application-facing delivery contract for dead-letter reconciliation."""

from typing import Protocol, runtime_checkable

from clouddoc.delivery.events.models import UploadedDocumentEvent


class DeadLetteredDocumentProcessingError(Exception):
    """Raised when dead-letter reconciliation should be retried."""


@runtime_checkable
class DeadLetteredDocumentProcessor(Protocol):
    """Reconcile one normalized dead-lettered document event."""

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Process one dead-lettered document event."""
        ...
