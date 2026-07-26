"""Application-backed uploaded-document processor adapter."""

from clouddoc.application.errors import ApplicationError
from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
)
from clouddoc.application.start_document_processing import (
    StartDocumentProcessing,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent


class ApplicationUploadedDocumentProcessor:
    """Delegate uploaded-document processing to an application service."""

    def __init__(
        self,
        *,
        service: StartDocumentProcessing,
    ) -> None:
        """Initialize the adapter with the processing-start service."""
        self._service = service

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Start authoritative processing for one uploaded document."""
        try:
            self._service.execute(
                event=event,
            )
        except ApplicationError as error:
            raise UploadedDocumentProcessingError(
                "failed to start uploaded-document processing"
            ) from error
