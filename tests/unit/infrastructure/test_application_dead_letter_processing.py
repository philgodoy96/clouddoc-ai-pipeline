"""Tests for the application-backed dead-letter processor."""

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
