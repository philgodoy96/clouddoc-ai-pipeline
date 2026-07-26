"""Claim-aware uploaded-document processing workflow."""

from collections.abc import Callable
from datetime import datetime

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
from clouddoc.application.ports import Clock
from clouddoc.application.processing_failures import ProcessingFailureReason
from clouddoc.application.processing_results import (
    ProcessingStartOutcome,
)
from clouddoc.application.start_document_processing import (
    StartDocumentProcessing,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import ProcessingAttempt
from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.providers import (
    AIProvider,
    AIProviderError,
    AIProviderInvalidResponseError,
    AIProviderRequest,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    JobAttemptMismatchError,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
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
        repository: DocumentJobRepository,
        clock: Clock,
    ) -> None:
        """Initialize the workflow with explicit dependencies."""
        self._start_processing = start_processing
        self._document_loader = document_loader
        self._ai_provider = ai_provider
        self._repository = repository
        self._clock = clock

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

        if start_result.outcome is ProcessingStartOutcome.PROCESSING_ALREADY_ACTIVE:
            raise ApplicationConflictError(
                "document job already has an active processing attempt"
            )

        attempt = start_result.attempt
        correlation_id = start_result.correlation_id

        if attempt is None or correlation_id is None:
            raise ApplicationConflictError(
                "processing start result is missing continuation context"
            )

        if event.etag is None:
            return self._record_terminal_failure(
                event=event,
                attempt=attempt,
                reason=ProcessingFailureReason.INVALID_DOCUMENT_REFERENCE,
            )

        reference = self._build_document_reference(
            event=event,
        )

        try:
            document = self._load_document(
                reference=reference,
            )
        except DocumentNotFoundError:
            return self._record_terminal_failure(
                event=event,
                attempt=attempt,
                reason=ProcessingFailureReason.DOCUMENT_NOT_FOUND,
            )
        except DocumentValidationError:
            return self._record_terminal_failure(
                event=event,
                attempt=attempt,
                reason=ProcessingFailureReason.DOCUMENT_VALIDATION_FAILED,
            )
        except DocumentDependencyError as error:
            self._release_retryable_claim(
                event=event,
                attempt=attempt,
            )
            raise ApplicationDependencyError(
                "failed to load uploaded document",
                cause=error,
                context={
                    "job_id": event.job_id,
                    "attempt_id": attempt.attempt_id,
                    "object_key": event.object_key,
                },
            ) from error

        try:
            request = self._build_provider_request(
                document=document,
                attempt=attempt,
                correlation_id=correlation_id,
            )
        except InvalidDomainValueError:
            return self._record_terminal_failure(
                event=event,
                attempt=attempt,
                reason=ProcessingFailureReason.INVALID_PROVIDER_REQUEST,
            )

        try:
            extraction_result = self._invoke_provider(
                request=request,
            )
        except AIProviderInvalidResponseError:
            return self._record_terminal_failure(
                event=event,
                attempt=attempt,
                reason=ProcessingFailureReason.AI_PROVIDER_INVALID_RESPONSE,
            )
        except AIProviderError as error:
            self._release_retryable_claim(
                event=event,
                attempt=attempt,
            )
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

        return self._complete_processing(
            event=event,
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
            raise InvalidDomainValueError("uploaded document event requires an ETag")

        return DocumentObjectReference(
            object_key=event.object_key,
            expected_size_bytes=event.object_size,
            expected_etag=event.etag,
            version_id=event.version_id,
        )

    def _load_document(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Load one validated document through the application port."""
        return self._document_loader.load(
            reference=reference,
        )

    @staticmethod
    def _build_provider_request(
        *,
        document: LoadedTextDocument,
        attempt: ProcessingAttempt,
        correlation_id: str,
    ) -> AIProviderRequest:
        """Build a normalized request using owned workflow context."""
        return AIProviderRequest(
            document_text=document.content,
            correlation_id=correlation_id,
            processing_attempt_id=attempt.attempt_id,
        )

    def _invoke_provider(
        self,
        *,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Invoke the provider and return one validated extraction."""
        return self._ai_provider.extract(request)

    def _complete_processing(
        self,
        *,
        event: UploadedDocumentEvent,
        attempt: ProcessingAttempt,
        extraction_result: AIExtractionResult,
    ) -> DocumentProcessingResult:
        """Persist successful completion before returning PROCESSED."""
        self._persist_finalization(
            event=event,
            attempt=attempt,
            operation="complete",
            persist=lambda finalized_at: self._repository.complete_job(
                event.job_id,
                attempt.attempt_id,
                extraction_result,
                completed_at=finalized_at,
            ),
        )
        return DocumentProcessingResult.processed(
            attempt=attempt,
            extraction_result=extraction_result,
        )

    def _record_terminal_failure(
        self,
        *,
        event: UploadedDocumentEvent,
        attempt: ProcessingAttempt,
        reason: ProcessingFailureReason,
    ) -> DocumentProcessingResult:
        """Persist a deterministic terminal failure before returning."""
        self._persist_finalization(
            event=event,
            attempt=attempt,
            operation="fail",
            persist=lambda finalized_at: self._repository.fail_job(
                event.job_id,
                attempt.attempt_id,
                reason.value,
                failed_at=finalized_at,
            ),
        )
        return DocumentProcessingResult.terminal_failure_recorded(
            attempt=attempt,
            failure_reason=reason,
        )

    def _release_retryable_claim(
        self,
        *,
        event: UploadedDocumentEvent,
        attempt: ProcessingAttempt,
    ) -> None:
        """Release ownership after a retryable dependency failure."""
        self._persist_finalization(
            event=event,
            attempt=attempt,
            operation="release",
            persist=lambda finalized_at: self._repository.release_retryable_claim(
                event.job_id,
                attempt.attempt_id,
                released_at=finalized_at,
            ),
        )

    def _persist_finalization(
        self,
        *,
        event: UploadedDocumentEvent,
        attempt: ProcessingAttempt,
        operation: str,
        persist: Callable[[datetime], DocumentJob],
    ) -> None:
        """Run one attempt-aware repository transition with normalized errors."""
        try:
            persist(self._clock.now())
        except JobNotFoundError as error:
            raise ApplicationNotFoundError(
                "document job was not found during processing finalization"
            ) from error
        except (
            JobAttemptMismatchError,
            JobStateConflictError,
        ) as error:
            raise ApplicationConflictError(
                "document processing finalization was rejected"
            ) from error
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to persist document processing finalization",
                cause=error,
                context={
                    "job_id": event.job_id,
                    "attempt_id": attempt.attempt_id,
                    "operation": operation,
                },
            ) from error
