"""Tests for the application-backed uploaded-document processor."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.application import ProcessingStartResult
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


def make_event() -> UploadedDocumentEvent:
    """Create one deterministic uploaded-document event."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key="documents/job-001/source.txt",
        job_id="job-001",
        object_size=128,
        etag="etag-001",
        sequencer="sequencer-001",
        version_id=None,
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
    ) -> None:
        """Raise the configured failure."""
        del event
        self.calls += 1
        raise self._error


class UnexpectedFailingStartDocumentProcessing:
    """Application-service double that raises a programming error."""

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Raise an unexpected exception."""
        del event
        raise RuntimeError("unexpected defect")


def test_adapter_satisfies_uploaded_document_processor_contract() -> None:
    """The adapter should satisfy the structural processing port."""
    processor = ApplicationUploadedDocumentProcessor(
        service=RecordingStartDocumentProcessing(
            result=claim_acquired_result(),
        ),
    )

    assert isinstance(
        processor,
        UploadedDocumentProcessor,
    )


def test_delegates_event_exactly_once() -> None:
    """The adapter should invoke the application service once."""
    service = RecordingStartDocumentProcessing(
        result=claim_acquired_result(),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
    )
    event = make_event()

    result = processor.process(
        event=event,
    )

    assert result is None
    assert service.events == [
        event,
    ]


def test_absorbs_effect_already_applied_result() -> None:
    """Already-applied outcomes should still satisfy the delivery None contract."""
    service = RecordingStartDocumentProcessing(
        result=effect_already_applied_result(),
    )
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
    )
    event = make_event()

    result = processor.process(
        event=event,
    )

    assert result is None
    assert service.events == [
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
    """Application failures should use the processor retry contract."""
    service = FailingStartDocumentProcessing(application_error)
    processor = ApplicationUploadedDocumentProcessor(
        service=service,
    )

    with pytest.raises(
        UploadedDocumentProcessingError,
        match="failed to start uploaded-document processing",
    ) as captured_error:
        processor.process(
            event=make_event(),
        )

    assert captured_error.value.__cause__ is application_error
    assert service.calls == 1


def test_does_not_translate_unexpected_exceptions() -> None:
    """Programming defects should reach the outer Lambda boundary."""
    processor = ApplicationUploadedDocumentProcessor(
        service=UnexpectedFailingStartDocumentProcessing(),
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected defect",
    ):
        processor.process(
            event=make_event(),
        )
