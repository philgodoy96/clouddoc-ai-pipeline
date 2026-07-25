"""Tests for uploaded-document processing application contracts."""

from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
    UploadedDocumentProcessor,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent


def make_event() -> UploadedDocumentEvent:
    """Create a deterministic normalized upload event."""
    return UploadedDocumentEvent(
        message_id="message-001",
        event_name="ObjectCreated:Put",
        bucket_name="clouddoc-documents",
        object_key="documents/job-001/source.txt",
        job_id="job-001",
        object_size=128,
        etag="etag-001",
        sequencer="0055AED6DCD90281E5",
        version_id=None,
    )


class RecordingProcessor:
    """Processor double that records normalized events."""

    def __init__(self) -> None:
        """Initialize the processor double."""
        self.events: list[UploadedDocumentEvent] = []

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Record one processing request."""
        self.events.append(event)


class FailingProcessor:
    """Processor double that raises a retryable failure."""

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Simulate a retryable processing failure."""
        raise UploadedDocumentProcessingError(f"failed to process {event.job_id}")


def test_processor_satisfies_application_contract() -> None:
    """A structural processor should satisfy the application port."""
    assert isinstance(
        RecordingProcessor(),
        UploadedDocumentProcessor,
    )


def test_processor_receives_normalized_event() -> None:
    """The port should accept one uploaded-document event."""
    processor = RecordingProcessor()
    event = make_event()

    result = processor.process(
        event=event,
    )

    assert result is None
    assert processor.events == [
        event,
    ]


def test_processing_error_is_explicit_retryable_contract() -> None:
    """Retryable processing failures should use the port error."""
    error = UploadedDocumentProcessingError("temporary processing failure")

    assert str(error) == "temporary processing failure"
    assert isinstance(error, Exception)


def test_failing_processor_raises_processing_error() -> None:
    """A processor may signal retry through the application error."""
    processor = FailingProcessor()
    event = make_event()

    try:
        processor.process(
            event=event,
        )
    except UploadedDocumentProcessingError as error:
        assert str(error) == "failed to process job-001"
    else:
        raise AssertionError("expected UploadedDocumentProcessingError")
