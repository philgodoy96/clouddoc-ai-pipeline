"""Application-backed uploaded-document processor adapter."""

from clouddoc.application.document_ports import (
    DocumentLoadError,
    DocumentObjectReference,
    DocumentTextLoader,
)
from clouddoc.application.errors import ApplicationError
from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
)
from clouddoc.application.processing_results import (
    ProcessingStartOutcome,
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
        document_loader: DocumentTextLoader,
    ) -> None:
        """Initialize the adapter with start and document-loading dependencies."""
        self._service = service
        self._document_loader = document_loader

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Start authoritative processing for one uploaded document."""
        try:
            start_result = self._service.execute(
                event=event,
            )
        except ApplicationError as error:
            raise UploadedDocumentProcessingError(
                "failed to start uploaded-document processing"
            ) from error

        if start_result.outcome is ProcessingStartOutcome.EFFECT_ALREADY_APPLIED:
            return

        reference = DocumentObjectReference(
            object_key=event.object_key,
            expected_size_bytes=event.object_size,
            expected_etag=event.etag,
            version_id=event.version_id,
        )

        try:
            self._document_loader.load(
                reference=reference,
            )
        except DocumentLoadError as error:
            raise UploadedDocumentProcessingError(
                "failed to load uploaded document"
            ) from error
