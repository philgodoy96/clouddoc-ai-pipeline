"""Tests for the claim-aware document-processing workflow."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
    DocumentDependencyError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentProcessingOutcome,
    DocumentProcessingResult,
    DocumentTextLoader,
    DocumentValidationError,
    LoadedTextDocument,
    ProcessingStartResult,
)
from clouddoc.application.process_uploaded_document import (
    ProcessUploadedDocument,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import ProcessingAttempt
from clouddoc.providers import (
    AIProvider,
    AIProviderError,
    AIProviderInvalidResponseError,
    AIProviderRequest,
    AIProviderThrottledError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
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
LEASE_EXPIRES_AT = STARTED_AT + timedelta(minutes=5)
CORRELATION_ID = "correlation-001"
ATTEMPT_ID = "attempt-001"
OBJECT_KEY = "documents/job-001/source.txt"
ETAG = "etag-001"
VERSION_ID = "version-001"
DOCUMENT_CONTENT = "Service contract between two companies."
DOCUMENT_SIZE = len(DOCUMENT_CONTENT.encode("utf-8"))


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


def test_doubles_satisfy_workflow_ports() -> None:
    """Workflow doubles should satisfy structural contracts."""
    loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    provider = RecordingAIProvider(
        result=make_extraction_result(),
    )

    assert isinstance(
        loader,
        DocumentTextLoader,
    )
    assert isinstance(
        provider,
        AIProvider,
    )


def test_claim_owner_loads_document_and_invokes_provider() -> None:
    """The owning worker should run retrieval and extraction once."""
    start_processing = RecordingStartProcessing(
        result=make_claim_result(),
    )
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    extraction_result = make_extraction_result()
    ai_provider = RecordingAIProvider(
        result=extraction_result,
    )
    service = ProcessUploadedDocument(
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


def test_already_applied_effect_skips_document_and_provider() -> None:
    """A duplicate should perform no downstream effect."""
    start_processing = RecordingStartProcessing(
        result=(ProcessingStartResult.effect_already_applied()),
    )
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service = ProcessUploadedDocument(
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
    assert start_processing.events == [
        event,
    ]
    assert document_loader.references == []
    assert ai_provider.requests == []


def test_active_processing_claim_raises_conflict() -> None:
    """An active competing claim must remain retryable."""
    start_processing = RecordingStartProcessing(
        result=(ProcessingStartResult.processing_already_active()),
    )
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service = ProcessUploadedDocument(
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
    service = ProcessUploadedDocument(
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


@pytest.mark.parametrize(
    (
        "document_error",
        "expected_error_type",
        "expected_message",
    ),
    [
        (
            DocumentNotFoundError("object missing"),
            ApplicationNotFoundError,
            "uploaded document was not found",
        ),
        (
            DocumentValidationError("invalid UTF-8"),
            ApplicationConflictError,
            "uploaded document failed validation",
        ),
        (
            DocumentDependencyError("S3 unavailable"),
            ApplicationDependencyError,
            "failed to load uploaded document",
        ),
    ],
)
def test_translates_known_document_load_failures(
    document_error: Exception,
    expected_error_type: type[Exception],
    expected_message: str,
) -> None:
    """Known loading failures should use application errors."""
    document_loader = FailingDocumentTextLoader(
        error=document_error,
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service = ProcessUploadedDocument(
        start_processing=RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    with pytest.raises(
        expected_error_type,
        match=expected_message,
    ) as captured_error:
        service.execute(
            event=make_event(),
        )

    assert captured_error.value.__cause__ is document_error
    assert document_loader.calls == 1
    assert ai_provider.requests == []

    if isinstance(
        captured_error.value,
        ApplicationDependencyError,
    ):
        assert captured_error.value.cause is document_error
        assert captured_error.value.context == {
            "job_id": "job-001",
            "attempt_id": ATTEMPT_ID,
            "object_key": OBJECT_KEY,
        }


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
        AIProviderInvalidResponseError(
            "provider returned invalid output",
            provider_name="recording",
        ),
    ],
)
def test_translates_known_provider_failures(
    provider_error: AIProviderError,
) -> None:
    """Normalized provider failures should become dependency errors."""
    ai_provider = FailingAIProvider(
        error=provider_error,
    )
    service = ProcessUploadedDocument(
        start_processing=RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=RecordingDocumentTextLoader(
            result=make_loaded_document(),
        ),
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


def test_rejects_empty_document_before_provider_invocation() -> None:
    """Provider requests must not receive empty text."""
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service = ProcessUploadedDocument(
        start_processing=RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=RecordingDocumentTextLoader(
            result=make_loaded_document(
                content="",
            ),
        ),
        ai_provider=ai_provider,
    )

    with pytest.raises(
        ApplicationConflictError,
        match="uploaded document cannot be processed",
    ):
        service.execute(
            event=make_event(),
        )

    assert ai_provider.requests == []


def test_rejects_event_without_etag_before_loading() -> None:
    """The workflow requires stable object identity."""
    document_loader = RecordingDocumentTextLoader(
        result=make_loaded_document(),
    )
    ai_provider = RecordingAIProvider(
        result=make_extraction_result(),
    )
    service = ProcessUploadedDocument(
        start_processing=RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=document_loader,
        ai_provider=ai_provider,
    )

    with pytest.raises(
        ApplicationConflictError,
        match="uploaded document event requires an ETag",
    ):
        service.execute(
            event=make_event(
                etag=None,
            ),
        )

    assert document_loader.references == []
    assert ai_provider.requests == []


def test_does_not_translate_unexpected_loader_failure() -> None:
    """Unexpected loader defects should reach the outer boundary."""
    unexpected_error = RuntimeError("unexpected loader defect")
    service = ProcessUploadedDocument(
        start_processing=RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=FailingDocumentTextLoader(
            error=unexpected_error,
        ),
        ai_provider=RecordingAIProvider(
            result=make_extraction_result(),
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected loader defect",
    ):
        service.execute(
            event=make_event(),
        )


def test_does_not_translate_unexpected_provider_failure() -> None:
    """Unexpected provider defects should reach the outer boundary."""
    unexpected_error = RuntimeError("unexpected provider defect")
    service = ProcessUploadedDocument(
        start_processing=RecordingStartProcessing(
            result=make_claim_result(),
        ),
        document_loader=RecordingDocumentTextLoader(
            result=make_loaded_document(),
        ),
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
