"""No-op implementation of uploaded-document processing."""

from clouddoc.application.processing_ports import (
    UploadedDocumentProcessor,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent


class NoOpUploadedDocumentProcessor:
    """Accept uploaded-document events without producing side effects."""

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Accept one normalized event without processing it."""
        del event


_processor_contract_check: UploadedDocumentProcessor
_processor_contract_check = NoOpUploadedDocumentProcessor()
