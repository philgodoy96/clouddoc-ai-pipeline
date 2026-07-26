"""Tests for the application-backed uploaded-document processor."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.application import ProcessingFailureReason
from clouddoc.application.document_processing_results import (
    DocumentProcessingResult,
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
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import ProcessingAttempt
from clouddoc.infrastructure.application_processing import (
    ApplicationUploadedDocumentProcessor,
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


def make_event() -> UploadedDocumentEvent:
    """Create one deterministic uploaded-document event."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key="documents/job-001/source.txt",
        job_id="job-001",
        object_size=21,
        etag="etag-001",
        sequencer="sequencer-001",
        version_id="version-001",
    )


def make_attempt() -> ProcessingAttempt:
    """Create one deterministic owned attempt."""
    return ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=STARTED_AT,
        lease_expires_at=LEASE_EXPIRES_AT,
    )


def make_extraction_result() -> AIExtractionResult:
    """Create one deterministic validated AI result."""
    return AIExtractionResult(
        document_type=DocumentType.CONTRACT,
        summary="Service contract between two companies.",
        key_fields={
            "contract_number": "CONTRACT-001",
        },
        confidence=0.91,
        requires_human_review=False,
    )


def make_processed_result() -> DocumentProcessingResult:
    """Create one deterministic processed workflow result."""
    return DocumentProcessingResult.processed(
        attempt=make_attempt(),
        extraction_result=make_extraction_result(),
    )


def make_already_applied_result() -> DocumentProcessingResult:
    """Create one deterministic already-applied workflow result."""
    return DocumentProcessingResult.effect_already_applied()


def make_terminal_failure_result() -> DocumentProcessingResult:
    """Create one deterministic durably recorded terminal result."""
    return DocumentProcessingResult.terminal_failure_recorded(
        attempt=make_attempt(),
        failure_reason=(ProcessingFailureReason.DOCUMENT_VALIDATION_FAILED),
    )


class RecordingProcessUploadedDocument:
    """Workflow double that records events and returns one configured result."""

    def __init__(
        self,
        *,
        result: DocumentProcessingResult,
    ) -> None:
        """Initialize call tracking with one configured result."""
        self._result = result
        self.events: list[UploadedDocumentEvent] = []

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> DocumentProcessingResult:
        """Record one uploaded-document event and return the configured result."""
        self.events.append(event)
        return self._result


class FailingProcessUploadedDocument:
    """Workflow double that raises one configured exception."""

    def __init__(
        self,
        error: Exception,
    ) -> None:
        """Store the configured failure."""
        self._error = error
        self.calls = 0

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> DocumentProcessingResult:
        """Raise the configured failure."""
        del event
        self.calls += 1
        raise self._error


def test_adapter_satisfies_uploaded_document_processor_contract() -> None:
    """The adapter should satisfy the structural processing port."""
    processor = ApplicationUploadedDocumentProcessor(
        workflow=RecordingProcessUploadedDocument(
            result=make_processed_result(),
        ),
    )

    assert isinstance(
        processor,
        UploadedDocumentProcessor,
    )


def test_returns_none_when_workflow_processes_document() -> None:
    """Processed workflow results should be absorbed by the adapter."""
    event = make_event()
    workflow = RecordingProcessUploadedDocument(
        result=make_processed_result(),
    )
    processor = ApplicationUploadedDocumentProcessor(
        workflow=workflow,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert workflow.events == [
        event,
    ]


def test_returns_none_when_effect_already_applied() -> None:
    """Already-applied workflow results should be absorbed by the adapter."""
    event = make_event()
    workflow = RecordingProcessUploadedDocument(
        result=make_already_applied_result(),
    )
    processor = ApplicationUploadedDocumentProcessor(
        workflow=workflow,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert workflow.events == [
        event,
    ]


def test_returns_none_when_terminal_failure_is_recorded() -> None:
    """Durably recorded terminal failures should be acknowledged."""
    event = make_event()
    workflow = RecordingProcessUploadedDocument(
        result=make_terminal_failure_result(),
    )
    processor = ApplicationUploadedDocumentProcessor(
        workflow=workflow,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert workflow.events == [
        event,
    ]


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
    """Known application failures should use the processor retry contract."""
    event = make_event()
    workflow = FailingProcessUploadedDocument(application_error)
    processor = ApplicationUploadedDocumentProcessor(
        workflow=workflow,
    )

    with pytest.raises(
        UploadedDocumentProcessingError,
        match="failed to process uploaded document",
    ) as captured_error:
        processor.process(
            event=event,
        )

    assert captured_error.value.__cause__ is application_error
    assert workflow.calls == 1


def test_does_not_translate_unexpected_workflow_exceptions() -> None:
    """Programming defects from the workflow should propagate unchanged."""
    event = make_event()
    workflow = FailingProcessUploadedDocument(
        RuntimeError("unexpected workflow defect"),
    )
    processor = ApplicationUploadedDocumentProcessor(
        workflow=workflow,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected workflow defect",
    ):
        processor.process(
            event=event,
        )

    assert workflow.calls == 1
