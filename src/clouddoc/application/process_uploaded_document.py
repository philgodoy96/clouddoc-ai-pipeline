"""Claim-aware uploaded-document processing workflow."""

from clouddoc.application.document_ports import (
    DocumentDependencyError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentTextLoader,
    DocumentValidationError,
    LoadedTextDocument,
)
from clouddoc.application.document_processing_results import (
    DocumentProcessingResult,
)
from clouddoc.application.errors import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.application.processing_results import (
    ProcessingStartOutcome,
)
from clouddoc.application.start_document_processing import (
    StartDocumentProcessing,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import ProcessingAttempt
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.providers import (
    AIProvider,
    AIProviderError,
    AIProviderRequest,
)
from clouddoc.schemas import AIExtractionResult


class ProcessUploadedDocument:
    """Run claim-aware document retrieval and AI extraction."""

    def __init__(
        self,
        *,
        start_processing: StartDocumentProcessing,
        document_loader: DocumentTextLoader,
        ai_provider: AIProvider,
    ) -> None:
        """Initialize the workflow with explicit dependencies."""
        self._start_processing = start_processing
        self._document_loader = document_loader
        self._ai_provider = ai_provider

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> DocumentProcessingResult:
        """Process one uploaded document when this worker owns the claim."""
        start_result = self._start_processing.execute(
            event=event,
        )

        if start_result.outcome is ProcessingStartOutcome.EFFECT_ALREADY_APPLIED:
            return DocumentProcessingResult.effect_already_applied()

        attempt = start_result.attempt
        correlation_id = start_result.correlation_id

        if attempt is None or correlation_id is None:
            raise ApplicationConflictError(
                "processing start result is missing continuation context"
            )

        reference = self._build_document_reference(
            event=event,
        )
        document = self._load_document(
            event=event,
            attempt=attempt,
            reference=reference,
        )
        request = self._build_provider_request(
            document=document,
            attempt=attempt,
            correlation_id=correlation_id,
        )
        extraction_result = self._invoke_provider(
            event=event,
            attempt=attempt,
            request=request,
        )

        return DocumentProcessingResult.processed(
            attempt=attempt,
            extraction_result=extraction_result,
        )

    @staticmethod
    def _build_document_reference(
        *,
        event: UploadedDocumentEvent,
    ) -> DocumentObjectReference:
        """Build a trusted object reference from normalized event data."""
        if event.etag is None:
            raise ApplicationConflictError("uploaded document event requires an ETag")

        return DocumentObjectReference(
            object_key=event.object_key,
            expected_size_bytes=event.object_size,
            expected_etag=event.etag,
            version_id=event.version_id,
        )

    def _load_document(
        self,
        *,
        event: UploadedDocumentEvent,
        attempt: ProcessingAttempt,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Load one validated document through the application port."""
        try:
            return self._document_loader.load(
                reference=reference,
            )
        except DocumentNotFoundError as error:
            raise ApplicationNotFoundError("uploaded document was not found") from error
        except DocumentValidationError as error:
            raise ApplicationConflictError(
                "uploaded document failed validation"
            ) from error
        except DocumentDependencyError as error:
            raise ApplicationDependencyError(
                "failed to load uploaded document",
                cause=error,
                context={
                    "job_id": event.job_id,
                    "attempt_id": attempt.attempt_id,
                    "object_key": event.object_key,
                },
            ) from error

    @staticmethod
    def _build_provider_request(
        *,
        document: LoadedTextDocument,
        attempt: ProcessingAttempt,
        correlation_id: str,
    ) -> AIProviderRequest:
        """Build a normalized request using owned workflow context."""
        try:
            return AIProviderRequest(
                document_text=document.content,
                correlation_id=correlation_id,
                processing_attempt_id=attempt.attempt_id,
            )
        except InvalidDomainValueError as error:
            raise ApplicationConflictError(
                "uploaded document cannot be processed"
            ) from error

    def _invoke_provider(
        self,
        *,
        event: UploadedDocumentEvent,
        attempt: ProcessingAttempt,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Invoke the provider and normalize known dependency failures."""
        try:
            return self._ai_provider.extract(request)
        except AIProviderError as error:
            provider_name = error.provider_name or self._ai_provider.provider_name

            raise ApplicationDependencyError(
                "failed to extract uploaded document",
                cause=error,
                context={
                    "job_id": event.job_id,
                    "attempt_id": attempt.attempt_id,
                    "provider_name": provider_name,
                },
            ) from error
