"""Application-layer contract for uploaded-document processing."""

from typing import Protocol, runtime_checkable

from clouddoc.delivery.events.models import UploadedDocumentEvent


class UploadedDocumentProcessingError(Exception):
    """Raised when uploaded-document processing should be retried."""


@runtime_checkable
class UploadedDocumentProcessor(Protocol):
    """Process one normalized uploaded-document event."""

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Process one uploaded document event."""
        ...
