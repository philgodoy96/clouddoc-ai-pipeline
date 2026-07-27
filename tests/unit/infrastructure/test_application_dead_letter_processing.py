"""Tests for the application-backed dead-letter processor."""

from typing import NamedTuple

import pytest

from clouddoc.application.dead_letter_processing_ports import (
    DeadLetteredDocumentProcessingError,
    DeadLetteredDocumentProcessor,
)
from clouddoc.application.dead_letter_results import (
    DeadLetterReconciliationResult,
)
from clouddoc.application.errors import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.infrastructure.application_dead_letter_processing import (
    ApplicationDeadLetteredDocumentProcessor,
)

JOB_ID = "job-001"

SENSITIVE_FRAGMENTS = (
    "documents/job-001/source.txt",
    "clouddoc-documents",
    "etag-001",
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
    """Prove structured fields omit document and payload details."""
    serialized = str(fields)

    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in serialized


def make_event() -> UploadedDocumentEvent:
    """Create one deterministic normalized dead-lettered event."""
    return UploadedDocumentEvent(
        message_id="dlq-message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key="documents/job-001/source.txt",
        job_id=JOB_ID,
        object_size=128,
        etag="etag-001",
        sequencer="sequencer-001",
        version_id="version-001",
    )


class RecordingReconcileDeadLetteredDocument:
    """Workflow double returning one configured result."""

    def __init__(
        self,
        *,
        result: DeadLetterReconciliationResult,
    ) -> None:
        """Initialize the workflow double."""
        self._result = result
        self.job_ids: list[str] = []

    def execute(
        self,
        *,
        job_id: str,
    ) -> DeadLetterReconciliationResult:
        """Record the job ID and return the configured result."""
        self.job_ids.append(job_id)
        return self._result


class FailingReconcileDeadLetteredDocument:
    """Workflow double raising one configured failure."""

    def __init__(
        self,
        *,
        error: Exception,
    ) -> None:
        """Initialize the workflow double."""
        self._error = error
        self.job_ids: list[str] = []

    def execute(
        self,
        *,
        job_id: str,
    ) -> DeadLetterReconciliationResult:
        """Record the job ID and raise the configured failure."""
        self.job_ids.append(job_id)
        raise self._error


def test_adapter_satisfies_dead_letter_processor_contract() -> None:
    """The adapter should satisfy the structural delivery contract."""
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=RecordingReconcileDeadLetteredDocument(
            result=DeadLetterReconciliationResult.dead_recorded(
                job_id=JOB_ID,
            ),
        ),
    )

    assert isinstance(
        processor,
        DeadLetteredDocumentProcessor,
    )


def test_returns_none_when_dead_state_is_recorded() -> None:
    """Durably recorded dead transitions should be acknowledged."""
    event = make_event()
    workflow = RecordingReconcileDeadLetteredDocument(
        result=DeadLetterReconciliationResult.dead_recorded(
            job_id=JOB_ID,
        ),
    )
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=workflow,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert workflow.job_ids == [
        JOB_ID,
    ]


def test_returns_none_when_terminal_effect_already_exists() -> None:
    """Existing terminal effects should be acknowledged."""
    event = make_event()
    workflow = RecordingReconcileDeadLetteredDocument(
        result=(
            DeadLetterReconciliationResult.effect_already_applied(
                job_id=JOB_ID,
            )
        ),
    )
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=workflow,
    )

    result = processor.process(
        event=event,
    )

    assert result is None
    assert workflow.job_ids == [
        JOB_ID,
    ]


@pytest.mark.parametrize(
    "application_error",
    [
        ApplicationNotFoundError(
            "document job was not found",
        ),
        ApplicationConflictError(
            "document job cannot be reconciled",
        ),
        ApplicationDependencyError(
            "repository unavailable",
        ),
    ],
)
def test_translates_known_application_errors(
    application_error: Exception,
) -> None:
    """Known application failures should remain retryable."""
    event = make_event()
    workflow = FailingReconcileDeadLetteredDocument(
        error=application_error,
    )
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=workflow,
    )

    with pytest.raises(
        DeadLetteredDocumentProcessingError,
        match=("failed to reconcile dead-lettered document"),
    ) as captured_error:
        processor.process(
            event=event,
        )

    assert captured_error.value.__cause__ is application_error
    assert workflow.job_ids == [
        JOB_ID,
    ]


def test_preserves_unexpected_workflow_exception() -> None:
    """Unexpected workflow defects should reach the Lambda boundary."""
    event = make_event()
    unexpected_error = RuntimeError(
        "unexpected reconciliation defect",
    )
    workflow = FailingReconcileDeadLetteredDocument(
        error=unexpected_error,
    )
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=workflow,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected reconciliation defect",
    ) as captured_error:
        processor.process(
            event=event,
        )

    assert captured_error.value is unexpected_error
    assert workflow.job_ids == [
        JOB_ID,
    ]


def test_dead_recorded_emits_one_warning_completion_event() -> None:
    """DEAD_RECORDED should emit one warning completion event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=RecordingReconcileDeadLetteredDocument(
            result=DeadLetterReconciliationResult.dead_recorded(
                job_id=JOB_ID,
            ),
        ),
        logger=logger,
        timer=timer,
    )

    result = processor.process(event=make_event())

    assert result is None
    assert len(logger.events) == 1

    recorded = logger.events[0]

    assert recorded.level == "warning"
    assert recorded.event_name == "reconciliation.record_completed"
    assert recorded.fields == {
        "operation": "reconcile_dead_lettered_document",
        "outcome": "dead_recorded",
        "job_id": JOB_ID,
        "sqs_message_id": "dlq-message-001",
        "duration_ms": 125.0,
        "failure_reason": "processing_retries_exhausted",
    }
    assert_fields_exclude_sensitive_content(recorded.fields)


def test_effect_already_applied_emits_one_info_completion_event() -> None:
    """EFFECT_ALREADY_APPLIED should emit one info event without failure reason."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=RecordingReconcileDeadLetteredDocument(
            result=DeadLetterReconciliationResult.effect_already_applied(
                job_id=JOB_ID,
            ),
        ),
        logger=logger,
        timer=timer,
    )

    result = processor.process(event=make_event())

    assert result is None
    assert len(logger.events) == 1

    recorded = logger.events[0]

    assert recorded.level == "info"
    assert recorded.event_name == "reconciliation.record_completed"
    assert recorded.fields == {
        "operation": "reconcile_dead_lettered_document",
        "outcome": "effect_already_applied",
        "job_id": JOB_ID,
        "sqs_message_id": "dlq-message-001",
        "duration_ms": 125.0,
    }
    assert "failure_reason" not in recorded.fields
    assert_fields_exclude_sensitive_content(recorded.fields)


@pytest.mark.parametrize(
    "application_error",
    [
        ApplicationNotFoundError("document job was not found"),
        ApplicationConflictError("document job cannot be reconciled"),
        ApplicationDependencyError("repository unavailable"),
    ],
)
def test_application_errors_emit_no_adapter_event(
    application_error: Exception,
) -> None:
    """Known application errors should not emit adapter completion events."""
    logger = RecordingOperationalLogger()
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=FailingReconcileDeadLetteredDocument(
            error=application_error,
        ),
        logger=logger,
        timer=SequenceTimer(10.0),
    )

    with pytest.raises(DeadLetteredDocumentProcessingError):
        processor.process(event=make_event())

    assert logger.events == []


def test_raising_logger_does_not_change_acknowledgement() -> None:
    """Logger failures must not prevent successful acknowledgement."""
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=RecordingReconcileDeadLetteredDocument(
            result=DeadLetterReconciliationResult.dead_recorded(
                job_id=JOB_ID,
            ),
        ),
        logger=RaisingOperationalLogger(),
        timer=SequenceTimer(10.0, 10.125),
    )

    result = processor.process(event=make_event())

    assert result is None


@pytest.mark.parametrize(
    ("result", "level", "outcome"),
    [
        (
            DeadLetterReconciliationResult.dead_recorded(job_id=JOB_ID),
            "warning",
            "dead_recorded",
        ),
        (
            DeadLetterReconciliationResult.effect_already_applied(
                job_id=JOB_ID,
            ),
            "info",
            "effect_already_applied",
        ),
    ],
)
def test_completed_workflow_result_emits_exactly_one_event(
    result: DeadLetterReconciliationResult,
    level: str,
    outcome: str,
) -> None:
    """Every completed workflow result should emit exactly one event."""
    logger = RecordingOperationalLogger()
    processor = ApplicationDeadLetteredDocumentProcessor(
        workflow=RecordingReconcileDeadLetteredDocument(result=result),
        logger=logger,
        timer=SequenceTimer(10.0, 10.125),
    )

    assert processor.process(event=make_event()) is None
    assert len(logger.events) == 1
    assert logger.events[0].level == level
    assert logger.events[0].event_name == "reconciliation.record_completed"
    assert logger.events[0].fields["outcome"] == outcome
