"""Tests for the application-backed uploaded-document processor."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.application.document_ports import (
    DocumentDependencyError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentTextLoader,
    DocumentValidationError,
    LoadedTextDocument,
)
from clouddoc.application.errors import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
    UploadedDocumentProcessor,
)
from clouddoc.application.processing_results import ProcessingStartResult
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import ProcessingAttempt
from clouddoc.infrastructure.application_processing import (
    ApplicationUploadedDocumentProcessor,
)

DOCUMENT_CONTENT = "hello cloud document"


def make_event(
    *,
    version_id: str | None = None,
) -> UploadedDocumentEvent:
    """Create one deterministic uploaded-document event."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key="documents/job-001/source.txt",
        job_id="job-001",
        object_size=len(DOCUMENT_CONTENT.encode("utf-8")),
        etag="etag-001",
        sequencer="sequencer-001",
        version_id=version_id,
    )


def claim_acquired_result() -> ProcessingStartResult:
    """Create one deterministic claim-acquired processing result."""
    started_at = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    return ProcessingStartResult.claim_acquired(
        attempt=ProcessingAttempt(
            attempt_id="attempt-001",
            started_at=started_at,
            lease_expires_at=started_at + timedelta(minutes=5),
        ),
    )


def effect_already_applied_result() -> ProcessingStartResult:
    """Create one deterministic already-applied processing result."""
    return ProcessingStartResult.effect_already_applied()


def make_loaded_document(
    *,
    event: UploadedDocumentEvent,
) -> LoadedTextDocument:
    """Create one loaded document matching the uploaded-document event."""
    return LoadedTextDocument(
        object_key=event.object_key,
        content=DOCUMENT_CONTENT,
        content_type="text/plain",
        size_bytes=event.object_size,
        etag=event.etag,
        version_id=event.version_id,
    )


class RecordingStartDocumentProcessing:
    """Application-service double that records execution requests."""

    def __init__(
        self,
        *,
        result: ProcessingStartResult,
    ) -> None:
        """Initialize call tracking with one configured result."""
        self._result = result
        self.events: list[UploadedDocumentEvent] = []

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> ProcessingStartResult:
        """Record one processing-start request and return the configured result."""
        self.events.append(event)
        return self._result


class FailingStartDocumentProcessing:
    """Application-service double that raises one configured error."""

    def __init__(
        self,
        error: Exception,
    ) -> None:
        """Store the configured application failure."""
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


class UnexpectedFailingStartDocumentProcessing:
    """Application-service double that raises a programming error."""

    def __init__(self) -> None:
        """Initialize call tracking."""
        self.calls = 0

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> ProcessingStartResult:
        """Raise an unexpected exception."""
        del event
        self.calls += 1
        raise RuntimeError("unexpected defect")


class RecordingDocumentTextLoader:
    """Document-loader double that records references and returns content."""

    def __init__(
        self,
        *,
        document: LoadedTextDocument,
    ) -> None:
        """Initialize call tracking with one configured document."""
        self._document = document
        self.references: list[DocumentObjectReference] = []

    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Record one document reference and return the configured document."""
        self.references.append(reference)
        return self._document


class FailingDocumentTextLoader:
    """Document-loader double that raises one configured error."""

    def __init__(
        self,
        error: Exception,
    ) -> None:
        """Store the configured document-loading failure."""
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


def test_adapter_satisfies_uploaded_document_processor_contract() -> None:
    """The adapter should satisfy the structural processing port."""
    event = make_event()
    document_loader = RecordingDocumentTextLoader(
        document=make_loaded_document(
            event=event,
        ),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=RecordingStartDocumentProcessing(
            result=claim_acquired_result(),
        ),
        document_loader=document_loader,
    )

    assert isinstance(
        processor,
        UploadedDocumentProcessor,
    )
    assert isinstance(
        document_loader,
        DocumentTextLoader,
    )


def test_loads_document_when_claim_is_acquired() -> None:
    """Claim-acquired outcomes should load the uploaded document once."""
    event = make_event(
        version_id="version-001",
    )
    service = RecordingStartDocumentProcessing(
        result=claim_acquired_result(),
    )
    loader = RecordingDocumentTextLoader(
        document=make_loaded_document(
            event=event,
        ),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
        document_loader=loader,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert service.events == [
        event,
    ]
    assert loader.references == [
        DocumentObjectReference(
            object_key=event.object_key,
            expected_size_bytes=event.object_size,
            expected_etag=event.etag,
            version_id=event.version_id,
        ),
    ]


def test_skips_document_loading_when_effect_already_applied() -> None:
    """Already-applied outcomes should skip document loading."""
    event = make_event()
    service = RecordingStartDocumentProcessing(
        result=effect_already_applied_result(),
    )
    loader = RecordingDocumentTextLoader(
        document=make_loaded_document(
            event=event,
        ),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
        document_loader=loader,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert service.events == [
        event,
    ]
    assert loader.references == []


@pytest.mark.parametrize(
    "application_error",
    [
        ApplicationNotFoundError("document job was not found"),
        ApplicationConflictError("processing ownership conflict"),
        ApplicationDependencyError("repository unavailable"),
    ],
)
def test_translates_application_errors_to_retryable_processor_error(
    application_error: Exception,
) -> None:
    """Application failures should use the processor retry contract."""
    event = make_event()
    service = FailingStartDocumentProcessing(application_error)
    loader = RecordingDocumentTextLoader(
        document=make_loaded_document(
            event=event,
        ),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
        document_loader=loader,
    )

    with pytest.raises(
        UploadedDocumentProcessingError,
        match="failed to start uploaded-document processing",
    ) as captured_error:
        processor.process(
            event=event,
        )

    assert captured_error.value.__cause__ is application_error
    assert service.calls == 1
    assert loader.references == []


@pytest.mark.parametrize(
    "document_error",
    [
        DocumentNotFoundError("document object was not found"),
        DocumentValidationError("document content is invalid"),
        DocumentDependencyError("document storage unavailable"),
    ],
)
def test_translates_document_errors_to_retryable_processor_error(
    document_error: Exception,
) -> None:
    """Known document-loading failures should use the processor retry contract."""
    event = make_event()
    service = RecordingStartDocumentProcessing(
        result=claim_acquired_result(),
    )
    loader = FailingDocumentTextLoader(document_error)
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
        document_loader=loader,
    )

    with pytest.raises(
        UploadedDocumentProcessingError,
        match="failed to load uploaded document",
    ) as captured_error:
        processor.process(
            event=event,
        )

    assert captured_error.value.__cause__ is document_error
    assert service.events == [
        event,
    ]
    assert loader.calls == 1


def test_does_not_translate_unexpected_start_exceptions() -> None:
    """Programming defects from start should reach the outer Lambda boundary."""
    event = make_event()
    service = UnexpectedFailingStartDocumentProcessing()
    loader = RecordingDocumentTextLoader(
        document=make_loaded_document(
            event=event,
        ),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
        document_loader=loader,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected defect",
    ):
        processor.process(
            event=event,
        )

    assert service.calls == 1
    assert loader.references == []


def test_does_not_translate_unexpected_loader_exceptions() -> None:
    """Programming defects from loading should reach the outer Lambda boundary."""
    event = make_event()
    service = RecordingStartDocumentProcessing(
        result=claim_acquired_result(),
    )
    loader_error = RuntimeError("unexpected loader defect")
    loader = FailingDocumentTextLoader(loader_error)
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
        document_loader=loader,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected loader defect",
    ) as captured_error:
        processor.process(
            event=event,
        )

    assert captured_error.value is loader_error
    assert service.events == [
        event,
    ]
    assert loader.calls == 1
