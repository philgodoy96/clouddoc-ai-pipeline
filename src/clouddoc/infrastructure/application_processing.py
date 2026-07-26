"""Application-backed uploaded-document processor adapter."""

from clouddoc.application.errors import ApplicationError
from clouddoc.application.process_uploaded_document import (
    ProcessUploadedDocument,
)
from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent


class ApplicationUploadedDocumentProcessor:
    """Delegate uploaded-document processing to an application service."""

    def __init__(
        self,
        *,
        workflow: ProcessUploadedDocument,
    ) -> None:
        """Initialize the adapter with the document-processing workflow."""
        self._workflow = workflow

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Process one uploaded-document event through the application workflow."""
        try:
            self._workflow.execute(
                event=event,
            )
        except ApplicationError as error:
            raise UploadedDocumentProcessingError(
                "failed to process uploaded document"
            ) from error
