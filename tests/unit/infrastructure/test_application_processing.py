"""Tests for the application-backed uploaded-document processor."""

from datetime import UTC, datetime, timedelta
from typing import NamedTuple

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

SENSITIVE_FRAGMENTS = (
    "documents/job-001/source.txt",
    "clouddoc-documents",
    "etag-001",
    "Service contract between two companies.",
    "CONTRACT-001",
    "repository unavailable",
)


class RecordedOperationalEvent(NamedTuple):
    """One captured operational logger emission."""

    level: str
    event_name: str
    fields: dict[str, object]


class RecordingOperationalLogger:
    """Operational logger double that records every emission."""

    def __init__(self) -> None:
        """Initialize an empty event list."""
        self.events: list[RecordedOperationalEvent] = []

    def info(self, event_name: str, **fields: object) -> None:
        """Record an informational event."""
        self.events.append(
            RecordedOperationalEvent(
                level="info",
                event_name=event_name,
                fields=dict(fields),
            )
        )

    def warning(self, event_name: str, **fields: object) -> None:
        """Record a warning event."""
        self.events.append(
            RecordedOperationalEvent(
                level="warning",
                event_name=event_name,
                fields=dict(fields),
            )
        )

    def error(self, event_name: str, **fields: object) -> None:
        """Record an error event."""
        self.events.append(
            RecordedOperationalEvent(
                level="error",
                event_name=event_name,
                fields=dict(fields),
            )
        )


class RaisingOperationalLogger:
    """Operational logger double that fails every emission."""

    def info(self, event_name: str, **fields: object) -> None:
        """Fail informational emission."""
        del event_name, fields
        raise RuntimeError("logger info failure")

    def warning(self, event_name: str, **fields: object) -> None:
        """Fail warning emission."""
        del event_name, fields
        raise RuntimeError("logger warning failure")

    def error(self, event_name: str, **fields: object) -> None:
        """Fail error emission."""
        del event_name, fields
        raise RuntimeError("logger error failure")


class SequenceTimer:
    """Deterministic timer that returns a fixed sequence of values."""

    def __init__(self, *values: float) -> None:
        """Store the values that will be returned on successive calls."""
        self._values = list(values)
        self._index = 0

    def __call__(self) -> float:
        """Return the next configured timer value."""
        if self._index >= len(self._values):
            raise RuntimeError("SequenceTimer exhausted")

        value = self._values[self._index]
        self._index += 1
        return value


def assert_fields_exclude_sensitive_content(
    fields: dict[str, object],
) -> None:
    """Prove structured fields omit document content and payload details."""
    serialized = str(fields)

    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in serialized


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


def test_processed_emits_one_info_completion_event() -> None:
    """PROCESSED should emit exactly one safe info completion event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)
    event = make_event()
    processor = ApplicationUploadedDocumentProcessor(
        workflow=RecordingProcessUploadedDocument(
            result=make_processed_result(),
        ),
        logger=logger,
        timer=timer,
    )

    result = processor.process(event=event)

    assert result is None
    assert len(logger.events) == 1

    recorded = logger.events[0]

    assert recorded.level == "info"
    assert recorded.event_name == "processing.record_completed"
    assert recorded.fields == {
        "operation": "process_document",
        "outcome": "processed",
        "job_id": "job-001",
        "sqs_message_id": "message-001",
        "duration_ms": 125.0,
        "processing_attempt_id": "attempt-001",
    }
    assert "failure_reason" not in recorded.fields
    assert "extraction_result" not in recorded.fields
    assert "summary" not in recorded.fields
    assert "key_fields" not in recorded.fields
    assert_fields_exclude_sensitive_content(recorded.fields)


def test_effect_already_applied_emits_one_info_completion_event() -> None:
    """EFFECT_ALREADY_APPLIED should emit one info event without attempt IDs."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)
    processor = ApplicationUploadedDocumentProcessor(
        workflow=RecordingProcessUploadedDocument(
            result=make_already_applied_result(),
        ),
        logger=logger,
        timer=timer,
    )

    result = processor.process(event=make_event())

    assert result is None
    assert len(logger.events) == 1

    recorded = logger.events[0]

    assert recorded.level == "info"
    assert recorded.event_name == "processing.record_completed"
    assert recorded.fields == {
        "operation": "process_document",
        "outcome": "effect_already_applied",
        "job_id": "job-001",
        "sqs_message_id": "message-001",
        "duration_ms": 125.0,
    }
    assert "processing_attempt_id" not in recorded.fields
    assert "failure_reason" not in recorded.fields
    assert_fields_exclude_sensitive_content(recorded.fields)


def test_terminal_failure_emits_one_warning_completion_event() -> None:
    """TERMINAL_FAILURE_RECORDED should emit one warning completion event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)
    processor = ApplicationUploadedDocumentProcessor(
        workflow=RecordingProcessUploadedDocument(
            result=make_terminal_failure_result(),
        ),
        logger=logger,
        timer=timer,
    )

    result = processor.process(event=make_event())

    assert result is None
    assert len(logger.events) == 1

    recorded = logger.events[0]

    assert recorded.level == "warning"
    assert recorded.event_name == "processing.record_completed"
    assert recorded.fields == {
        "operation": "process_document",
        "outcome": "terminal_failure_recorded",
        "job_id": "job-001",
        "sqs_message_id": "message-001",
        "duration_ms": 125.0,
        "processing_attempt_id": "attempt-001",
        "failure_reason": "document_validation_failed",
    }
    assert_fields_exclude_sensitive_content(recorded.fields)


@pytest.mark.parametrize(
    "application_error",
    [
        ApplicationNotFoundError("document job was not found"),
        ApplicationConflictError("processing ownership conflict"),
        ApplicationDependencyError("repository unavailable"),
    ],
)
def test_application_errors_emit_no_adapter_event(
    application_error: Exception,
) -> None:
    """Adapter failures are owned by the SQS handler, not adapter telemetry."""
    logger = RecordingOperationalLogger()
    processor = ApplicationUploadedDocumentProcessor(
        workflow=FailingProcessUploadedDocument(application_error),
        logger=logger,
        timer=SequenceTimer(10.0),
    )

    with pytest.raises(UploadedDocumentProcessingError):
        processor.process(event=make_event())

    assert logger.events == []


def test_raising_logger_does_not_change_successful_none_return() -> None:
    """Logger failures must not prevent successful acknowledgement."""
    processor = ApplicationUploadedDocumentProcessor(
        workflow=RecordingProcessUploadedDocument(
            result=make_processed_result(),
        ),
        logger=RaisingOperationalLogger(),
        timer=SequenceTimer(10.0, 10.125),
    )

    result = processor.process(event=make_event())

    assert result is None


@pytest.mark.parametrize(
    ("result", "level", "outcome"),
    [
        (make_processed_result(), "info", "processed"),
        (make_already_applied_result(), "info", "effect_already_applied"),
        (
            make_terminal_failure_result(),
            "warning",
            "terminal_failure_recorded",
        ),
    ],
)
def test_completed_workflow_result_emits_exactly_one_event(
    result: DocumentProcessingResult,
    level: str,
    outcome: str,
) -> None:
    """Every completed workflow result should emit exactly one event."""
    logger = RecordingOperationalLogger()
    processor = ApplicationUploadedDocumentProcessor(
        workflow=RecordingProcessUploadedDocument(result=result),
        logger=logger,
        timer=SequenceTimer(10.0, 10.125),
    )

    assert processor.process(event=make_event()) is None
    assert len(logger.events) == 1
    assert logger.events[0].level == level
    assert logger.events[0].event_name == "processing.record_completed"
    assert logger.events[0].fields["outcome"] == outcome
