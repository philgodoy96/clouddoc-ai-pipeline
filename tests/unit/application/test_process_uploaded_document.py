"""Tests for the claim-aware document-processing workflow."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
    Clock,
    DocumentDependencyError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentProcessingOutcome,
    DocumentProcessingResult,
    DocumentTextLoader,
    DocumentValidationError,
    LoadedTextDocument,
    ProcessingFailureReason,
    ProcessingStartResult,
)
from clouddoc.application.process_uploaded_document import (
    ProcessUploadedDocument,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    ProcessingAttempt,
)
from clouddoc.providers import (
    AIProvider,
    AIProviderError,
    AIProviderInvalidResponseError,
    AIProviderRequest,
    AIProviderThrottledError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    JobAttemptMismatchError,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)
from clouddoc.schemas import (
    AIExtractionResult,
    DocumentType,
)

STARTED_AT = datetime(
    2026,
    7,
    26,
    12,
    0,
    tzinfo=UTC,
)
FINALIZED_AT = datetime(
    2026,
    7,
    26,
    12,
    1,
    tzinfo=UTC,
)
LEASE_EXPIRES_AT = STARTED_AT + timedelta(minutes=5)
CORRELATION_ID = "correlation-001"
ATTEMPT_ID = "attempt-001"
OBJECT_KEY = "documents/job-001/source.txt"
ETAG = "etag-001"
VERSION_ID = "version-001"
DOCUMENT_CONTENT = "Service contract between two companies."
DOCUMENT_SIZE = len(DOCUMENT_CONTENT.encode("utf-8"))


class FixedClock:
    """Deterministic clock returning one configured timestamp."""

    def __init__(
        self,
        current_time: datetime = FINALIZED_AT,
    ) -> None:
        """Initialize the clock."""
        self._current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        """Return the configured timestamp and count the call."""
        self.calls += 1
        return self._current_time


class RecordingDocumentJobRepository:
    """Repository double recording attempt-aware finalization calls."""

    def __init__(
        self,
        *,
        complete_error: Exception | None = None,
        fail_error: Exception | None = None,
        release_error: Exception | None = None,
    ) -> None:
        """Initialize recorded calls and optional operation failures."""
        self.complete_error = complete_error
        self.fail_error = fail_error
        self.release_error = release_error
        self.complete_calls: list[dict[str, object]] = []
        self.fail_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []

    def create_job(
        self,
        job: DocumentJob,
    ) -> None:
        """Unused by this workflow."""
        del job
        raise NotImplementedError

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob | None:
        """Unused by this workflow."""
        del job_id
        raise NotImplementedError

    def claim_job(
        self,
        job_id: str,
        attempt: ProcessingAttempt,
        *,
        claimed_at: datetime,
    ) -> DocumentJob:
        """Unused by this workflow."""
        del job_id, attempt, claimed_at
        raise NotImplementedError

    def complete_job(
        self,
        job_id: str,
        attempt_id: str,
        result: AIExtractionResult,
        *,
        completed_at: datetime,
    ) -> DocumentJob:
        """Record completion and optionally raise a configured error."""
        self.complete_calls.append(
            {
                "job_id": job_id,
                "attempt_id": attempt_id,
                "result": result,
                "completed_at": completed_at,
            }
        )
        if self.complete_error is not None:
            raise self.complete_error

        return make_document_job()

    def fail_job(
        self,
        job_id: str,
        attempt_id: str,
        reason: str,
        *,
        failed_at: datetime,
    ) -> DocumentJob:
        """Record terminal failure and optionally raise a configured error."""
        self.fail_calls.append(
            {
                "job_id": job_id,
                "attempt_id": attempt_id,
                "reason": reason,
                "failed_at": failed_at,
            }
        )
        if self.fail_error is not None:
            raise self.fail_error

        return make_document_job()

    def release_retryable_claim(
        self,
        job_id: str,
        attempt_id: str,
        *,
        released_at: datetime,
    ) -> DocumentJob:
        """Record release and optionally raise a configured error."""
        self.release_calls.append(
            {
                "job_id": job_id,
                "attempt_id": attempt_id,
                "released_at": released_at,
            }
        )
        if self.release_error is not None:
            raise self.release_error

        return make_document_job()

    def mark_dead(
        self,
        job_id: str,
        reason: str,
        *,
        marked_at: datetime,
    ) -> DocumentJob:
        """Unused by this workflow."""
        del job_id, reason, marked_at
        raise NotImplementedError


class RecordingStartProcessing:
    """Processing-start double returning one configured result."""

    def __init__(
        self,
        *,
        result: ProcessingStartResult,
    ) -> None:
        """Initialize the double."""
        self._result = result
        self.events: list[UploadedDocumentEvent] = []

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> ProcessingStartResult:
        """Record the event and return the configured result."""
        self.events.append(event)
        return self._result


class FailingStartProcessing:
    """Processing-start double raising one configured failure."""

    def __init__(
        self,
        *,
        error: Exception,
    ) -> None:
        """Initialize the double."""
        self._error = error
        self.calls = 0

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> ProcessingStartResult:
        """Raise the configured failure."""
        del event
        self.calls += 1
        raise self._error


class RecordingDocumentTextLoader:
    """Document-loader double returning one configured document."""

    def __init__(
        self,
        *,
        result: LoadedTextDocument,
    ) -> None:
        """Initialize the double."""
        self._result = result
        self.references: list[DocumentObjectReference] = []

    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Record the reference and return the document."""
        self.references.append(reference)
        return self._result


class FailingDocumentTextLoader:
    """Document-loader double raising one configured failure."""

    def __init__(
        self,
        *,
        error: Exception,
    ) -> None:
        """Initialize the double."""
        self._error = error
        self.calls = 0

    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Raise the configured failure."""
        del reference
        self.calls += 1
        raise self._error


class RecordingAIProvider:
    """AI-provider double returning one configured extraction."""

    provider_name = "recording"

    def __init__(
        self,
        *,
        result: AIExtractionResult,
    ) -> None:
        """Initialize the double."""
        self._result = result
        self.requests: list[AIProviderRequest] = []

    def extract(
        self,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Record the request and return the extraction."""
        self.requests.append(request)
        return self._result


class FailingAIProvider:
    """AI-provider double raising one configured failure."""

    provider_name = "recording"

    def __init__(
        self,
        *,
        error: Exception,
    ) -> None:
        """Initialize the double."""
        self._error = error
        self.requests: list[AIProviderRequest] = []

    def extract(
        self,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Record the request and raise the configured failure."""
        self.requests.append(request)
        raise self._error


def make_attempt() -> ProcessingAttempt:
    """Create one deterministic owned attempt."""
    return ProcessingAttempt(
        attempt_id=ATTEMPT_ID,
        started_at=STARTED_AT,
        lease_expires_at=LEASE_EXPIRES_AT,
    )


def make_document_job() -> DocumentJob:
    """Create one harmless document job for repository return values."""
    return DocumentJob(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id=CORRELATION_ID,
        ),
        created_at=STARTED_AT,
        updated_at=STARTED_AT,
    )


def make_event(
    *,
    etag: str | None = ETAG,
) -> UploadedDocumentEvent:
    """Create one deterministic uploaded-document event."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key=OBJECT_KEY,
        job_id="job-001",
        object_size=DOCUMENT_SIZE,
        etag=etag,
        sequencer="sequencer-001",
        version_id=VERSION_ID,
    )


def make_loaded_document(
    *,
    content: str = DOCUMENT_CONTENT,
) -> LoadedTextDocument:
    """Create one validated loaded document."""
    return LoadedTextDocument(
        object_key=OBJECT_KEY,
        content=content,
        content_type="text/plain",
        size_bytes=len(content.encode("utf-8")),
        etag=ETAG,
        version_id=VERSION_ID,
    )


def make_extraction_result() -> AIExtractionResult:
    """Create one deterministic validated AI result."""
    return AIExtractionResult(
        document_type=DocumentType.CONTRACT,
        summary=DOCUMENT_CONTENT,
        key_fields={
            "contract_number": "CONTRACT-001",
        },
        confidence=0.91,
        requires_human_review=False,
    )


def make_claim_result() -> ProcessingStartResult:
    """Create one successful owned processing-start result."""
    return ProcessingStartResult.claim_acquired(
        attempt=make_attempt(),
        correlation_id=CORRELATION_ID,
    )


def make_service(
    *,
    start_processing: Any | None = None,
    document_loader: Any | None = None,
    ai_provider: Any | None = None,
    repository: RecordingDocumentJobRepository | None = None,
    clock: FixedClock | None = None,
) -> tuple[
    ProcessUploadedDocument,
    RecordingDocumentJobRepository,
    FixedClock,
]:
    """Build the workflow with optional doubles."""
    resolved_repository = repository or RecordingDocumentJobRepository()
    resolved_clock = clock or FixedClock()
    service = ProcessUploadedDocument(
        start_processing=start_processing
        or RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=document_loader
        or RecordingDocumentTextLoader(
            result=make_loaded_document(),
        ),
        ai_provider=ai_provider
        or RecordingAIProvider(
            result=make_extraction_result(),
        ),
        repository=resolved_repository,
        clock=resolved_clock,
    )
    return service, resolved_repository, resolved_clock


def assert_no_finalization(
    repository: RecordingDocumentJobRepository,
    clock: FixedClock,
) -> None:
    """Assert that no finalization transition was attempted."""
    assert repository.complete_calls == []
    assert repository.fail_calls == []
    assert repository.release_calls == []
    assert clock.calls == 0


def test_doubles_satisfy_workflow_ports() -> None:
    """Workflow doubles should satisfy structural contracts."""
    loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    repository = RecordingDocumentJobRepository()
    clock = FixedClock()

    assert isinstance(
        loader,
        DocumentTextLoader,
    )
    assert isinstance(
        provider,
        AIProvider,
    )
    assert isinstance(
        repository,
        DocumentJobRepository,
    )
    assert isinstance(
        clock,
        Clock,
    )


def test_claim_owner_persists_successful_completion() -> None:
    """The owning worker should persist success before returning PROCESSED."""
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    extraction_result = make_extraction_result()
    ai_provider = RecordingAIProvider(
        result=extraction_result,
    )
    start_processing = RecordingStartProcessing(
        result=make_claim_result(),
    )
    service, repository, clock = make_service(
        start_processing=start_processing,
        document_loader=document_loader,
        ai_provider=ai_provider,
    )
    event = make_event()

    result = service.execute(
        event=event,
    )

    assert isinstance(
        result,
        DocumentProcessingResult,
    )
    assert result.outcome is DocumentProcessingOutcome.PROCESSED
    assert result.attempt == make_attempt()
    assert result.extraction_result is extraction_result
    assert result.failure_reason is None

    assert start_processing.events == [
        event,
    ]
    assert document_loader.references == [
        DocumentObjectReference(
            object_key=OBJECT_KEY,
            expected_size_bytes=DOCUMENT_SIZE,
            expected_etag=ETAG,
            version_id=VERSION_ID,
        )
    ]
    assert ai_provider.requests == [
        AIProviderRequest(
            document_text=DOCUMENT_CONTENT,
            correlation_id=CORRELATION_ID,
            processing_attempt_id=ATTEMPT_ID,
        )
    ]
    assert len(repository.complete_calls) == 1
    assert repository.complete_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "result": extraction_result,
        "completed_at": FINALIZED_AT,
    }
    assert repository.fail_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1


def test_already_applied_effect_skips_document_provider_and_finalization() -> None:
    """A duplicate should perform no downstream effect."""
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    start_processing = RecordingStartProcessing(
        result=(ProcessingStartResult.effect_already_applied()),
    )
    service, repository, clock = make_service(
        start_processing=start_processing,
        document_loader=document_loader,
        ai_provider=ai_provider,
    )
    event = make_event()

    result = service.execute(
        event=event,
    )

    assert result.outcome is DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED
    assert result.attempt is None
    assert result.extraction_result is None
    assert result.failure_reason is None
    assert start_processing.events == [
        event,
    ]
    assert document_loader.references == []
    assert ai_provider.requests == []
    assert_no_finalization(
        repository,
        clock,
    )


def test_active_processing_claim_raises_conflict_without_finalization() -> None:
    """An active competing claim must remain retryable."""
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    start_processing = RecordingStartProcessing(
        result=(ProcessingStartResult.processing_already_active()),
    )
    service, repository, clock = make_service(
        start_processing=start_processing,
        document_loader=document_loader,
        ai_provider=ai_provider,
    )
    event = make_event()

    with pytest.raises(
        ApplicationConflictError,
        match="document job already has an active processing attempt",
    ):
        service.execute(
            event=event,
        )

    assert start_processing.events == [
        event,
    ]
    assert document_loader.references == []
    assert ai_provider.requests == []
    assert_no_finalization(
        repository,
        clock,
    )


@pytest.mark.parametrize(
    "error",
    [
        ApplicationNotFoundError("document job was not found"),
        ApplicationConflictError("processing ownership conflict"),
        ApplicationDependencyError("repository unavailable"),
    ],
)
def test_preserves_processing_start_errors(
    error: Exception,
) -> None:
    """Processing-start application failures should remain unchanged."""
    start_processing = FailingStartProcessing(
        error=error,
    )
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service, repository, clock = make_service(
        start_processing=start_processing,
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    with pytest.raises(
        type(error),
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value is error
    assert start_processing.calls == 1
    assert document_loader.references == []
    assert ai_provider.requests == []
    assert_no_finalization(
        repository,
        clock,
    )


def test_missing_etag_records_terminal_failure() -> None:
    """Missing ETag should fail the owned attempt without loading."""
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    result = service.execute(
        event=make_event(
            etag=None,
        ),
    )

    assert result.outcome is (DocumentProcessingOutcome.TERMINAL_FAILURE_RECORDED)
    assert result.attempt == make_attempt()
    assert result.extraction_result is None
    assert result.failure_reason is (ProcessingFailureReason.INVALID_DOCUMENT_REFERENCE)
    assert document_loader.references == []
    assert ai_provider.requests == []
    assert len(repository.fail_calls) == 1
    assert repository.fail_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "reason": ProcessingFailureReason.INVALID_DOCUMENT_REFERENCE.value,
        "failed_at": FINALIZED_AT,
    }
    assert repository.complete_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1


@pytest.mark.parametrize(
    (
        "document_error",
        "expected_reason",
    ),
    [
        (
            DocumentNotFoundError("object missing"),
            ProcessingFailureReason.DOCUMENT_NOT_FOUND,
        ),
        (
            DocumentValidationError("invalid UTF-8"),
            ProcessingFailureReason.DOCUMENT_VALIDATION_FAILED,
        ),
    ],
)
def test_terminal_document_load_failures_are_persisted(
    document_error: Exception,
    expected_reason: ProcessingFailureReason,
) -> None:
    """Deterministic loading failures should fail the owned attempt."""
    document_loader = FailingDocumentTextLoader(
        error=document_error,
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    result = service.execute(
        event=make_event(),
    )

    assert result.outcome is (DocumentProcessingOutcome.TERMINAL_FAILURE_RECORDED)
    assert result.attempt == make_attempt()
    assert result.extraction_result is None
    assert result.failure_reason is expected_reason
    assert document_loader.calls == 1
    assert ai_provider.requests == []
    assert len(repository.fail_calls) == 1
    assert repository.fail_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "reason": expected_reason.value,
        "failed_at": FINALIZED_AT,
    }
    assert repository.complete_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1


def test_invalid_provider_request_records_terminal_failure() -> None:
    """Empty document text should fail before provider invocation."""
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(
            content="",
        ),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    result = service.execute(
        event=make_event(),
    )

    assert result.outcome is (DocumentProcessingOutcome.TERMINAL_FAILURE_RECORDED)
    assert result.attempt == make_attempt()
    assert result.extraction_result is None
    assert result.failure_reason is (ProcessingFailureReason.INVALID_PROVIDER_REQUEST)
    assert len(document_loader.references) == 1
    assert ai_provider.requests == []
    assert len(repository.fail_calls) == 1
    assert repository.fail_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "reason": ProcessingFailureReason.INVALID_PROVIDER_REQUEST.value,
        "failed_at": FINALIZED_AT,
    }
    assert repository.complete_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1


def test_invalid_provider_response_records_terminal_failure() -> None:
    """Invalid provider output should fail the owned attempt."""
    provider_error = AIProviderInvalidResponseError(
        "provider returned invalid output",
        provider_name="recording",
    )
    ai_provider = FailingAIProvider(
        error=provider_error,
    )
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    result = service.execute(
        event=make_event(),
    )

    assert result.outcome is (DocumentProcessingOutcome.TERMINAL_FAILURE_RECORDED)
    assert result.attempt == make_attempt()
    assert result.extraction_result is None
    assert result.failure_reason is (
        ProcessingFailureReason.AI_PROVIDER_INVALID_RESPONSE
    )
    assert len(document_loader.references) == 1
    assert len(ai_provider.requests) == 1
    assert len(repository.fail_calls) == 1
    assert repository.fail_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "reason": (ProcessingFailureReason.AI_PROVIDER_INVALID_RESPONSE.value),
        "failed_at": FINALIZED_AT,
    }
    assert repository.complete_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1


def test_retryable_document_dependency_releases_claim() -> None:
    """Retryable document loading failures should release ownership."""
    document_error = DocumentDependencyError("S3 unavailable")
    document_loader = FailingDocumentTextLoader(
        error=document_error,
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to load uploaded document",
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value.cause is document_error
    assert captured_error.value.__cause__ is document_error
    assert captured_error.value.context == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "object_key": OBJECT_KEY,
    }
    assert document_loader.calls == 1
    assert ai_provider.requests == []
    assert len(repository.release_calls) == 1
    assert repository.release_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "released_at": FINALIZED_AT,
    }
    assert repository.complete_calls == []
    assert repository.fail_calls == []
    assert clock.calls == 1


@pytest.mark.parametrize(
    "provider_error",
    [
        AIProviderTimeoutError(
            "provider timed out",
            provider_name="recording",
        ),
        AIProviderThrottledError(
            "provider throttled request",
            provider_name="recording",
        ),
        AIProviderUnavailableError(
            "provider unavailable",
            provider_name="recording",
        ),
        AIProviderError(
            "generic provider failure",
            provider_name="recording",
        ),
    ],
)
def test_retryable_provider_failures_release_claim(
    provider_error: AIProviderError,
) -> None:
    """Retryable provider failures should release ownership."""
    ai_provider = FailingAIProvider(
        error=provider_error,
    )
    service, repository, clock = make_service(
        ai_provider=ai_provider,
    )

    with pytest.raises(
        ApplicationDependencyError,
        match="failed to extract uploaded document",
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value.cause is provider_error
    assert captured_error.value.__cause__ is provider_error
    assert captured_error.value.context == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "provider_name": "recording",
    }
    assert len(ai_provider.requests) == 1
    assert len(repository.release_calls) == 1
    assert repository.release_calls[0] == {
        "job_id": "job-001",
        "attempt_id": ATTEMPT_ID,
        "released_at": FINALIZED_AT,
    }
    assert repository.complete_calls == []
    assert repository.fail_calls == []
    assert clock.calls == 1


@pytest.mark.parametrize(
    (
        "repository_error",
        "expected_error_type",
        "expected_message",
    ),
    [
        (
            JobAttemptMismatchError("stale attempt"),
            ApplicationConflictError,
            "document processing finalization was rejected",
        ),
        (
            JobStateConflictError("state conflict"),
            ApplicationConflictError,
            "document processing finalization was rejected",
        ),
        (
            JobNotFoundError("missing job"),
            ApplicationNotFoundError,
            "document job was not found during processing finalization",
        ),
        (
            RepositoryError("DynamoDB unavailable"),
            ApplicationDependencyError,
            "failed to persist document processing finalization",
        ),
    ],
)
def test_completion_persistence_failures_are_normalized(
    repository_error: Exception,
    expected_error_type: type[Exception],
    expected_message: str,
) -> None:
    """Successful extraction must not return PROCESSED when complete fails."""
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        ai_provider=ai_provider,
        repository=RecordingDocumentJobRepository(
            complete_error=repository_error,
        ),
    )

    with pytest.raises(
        expected_error_type,
        match=expected_message,
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value.__cause__ is repository_error
    assert len(document_loader.references) == 1
    assert len(ai_provider.requests) == 1
    assert len(repository.complete_calls) == 1
    assert repository.fail_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1

    if isinstance(
        captured_error.value,
        ApplicationDependencyError,
    ):
        assert captured_error.value.cause is repository_error
        assert captured_error.value.context == {
            "job_id": "job-001",
            "attempt_id": ATTEMPT_ID,
            "operation": "complete",
        }


@pytest.mark.parametrize(
    (
        "repository_error",
        "expected_error_type",
        "expected_message",
    ),
    [
        (
            JobAttemptMismatchError("stale attempt"),
            ApplicationConflictError,
            "document processing finalization was rejected",
        ),
        (
            RepositoryError("DynamoDB unavailable"),
            ApplicationDependencyError,
            "failed to persist document processing finalization",
        ),
    ],
)
def test_terminal_failure_persistence_failures_are_normalized(
    repository_error: Exception,
    expected_error_type: type[Exception],
    expected_message: str,
) -> None:
    """Terminal results must not escape when fail_job cannot persist."""
    document_loader = FailingDocumentTextLoader(
        error=DocumentNotFoundError("object missing"),
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        repository=RecordingDocumentJobRepository(
            fail_error=repository_error,
        ),
    )

    with pytest.raises(
        expected_error_type,
        match=expected_message,
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value.__cause__ is repository_error
    assert document_loader.calls == 1
    assert len(repository.fail_calls) == 1
    assert repository.complete_calls == []
    assert repository.release_calls == []
    assert clock.calls == 1

    if isinstance(
        captured_error.value,
        ApplicationDependencyError,
    ):
        assert captured_error.value.cause is repository_error
        assert captured_error.value.context == {
            "job_id": "job-001",
            "attempt_id": ATTEMPT_ID,
            "operation": "fail",
        }


@pytest.mark.parametrize(
    (
        "repository_error",
        "expected_error_type",
        "expected_message",
    ),
    [
        (
            JobAttemptMismatchError("stale attempt"),
            ApplicationConflictError,
            "document processing finalization was rejected",
        ),
        (
            RepositoryError("DynamoDB unavailable"),
            ApplicationDependencyError,
            "failed to persist document processing finalization",
        ),
    ],
)
def test_release_persistence_failures_take_precedence(
    repository_error: Exception,
    expected_error_type: type[Exception],
    expected_message: str,
) -> None:
    """Release failures must supersede the original retryable failure."""
    document_error = DocumentDependencyError("S3 unavailable")
    document_loader = FailingDocumentTextLoader(
        error=document_error,
    )
    service, repository, clock = make_service(
        document_loader=document_loader,
        repository=RecordingDocumentJobRepository(
            release_error=repository_error,
        ),
    )

    with pytest.raises(
        expected_error_type,
        match=expected_message,
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value.__cause__ is repository_error
    assert document_loader.calls == 1
    assert len(repository.release_calls) == 1
    assert repository.complete_calls == []
    assert repository.fail_calls == []
    assert clock.calls == 1

    if isinstance(
        captured_error.value,
        ApplicationDependencyError,
    ):
        assert captured_error.value.cause is repository_error
        assert captured_error.value.context == {
            "job_id": "job-001",
            "attempt_id": ATTEMPT_ID,
            "operation": "release",
        }


def test_does_not_translate_unexpected_loader_failure() -> None:
    """Unexpected loader defects should reach the outer boundary."""
    unexpected_error = RuntimeError("unexpected loader defect")
    service, repository, clock = make_service(
        document_loader=FailingDocumentTextLoader(
            error=unexpected_error,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected loader defect",
    ):
        service.execute(
            event=make_event(),
        )

    assert_no_finalization(
        repository,
        clock,
    )


def test_does_not_translate_unexpected_provider_failure() -> None:
    """Unexpected provider defects should reach the outer boundary."""
    unexpected_error = RuntimeError("unexpected provider defect")
    service, repository, clock = make_service(
        ai_provider=FailingAIProvider(
            error=unexpected_error,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected provider defect",
    ):
        service.execute(
            event=make_event(),
        )

    assert_no_finalization(
        repository,
        clock,
    )
