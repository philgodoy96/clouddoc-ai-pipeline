"""Tests for the no-op uploaded-document processor."""

from clouddoc.application.processing_ports import (
    UploadedDocumentProcessor,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.infrastructure.no_op_processing import (
    NoOpUploadedDocumentProcessor,
)


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


def test_no_op_processor_satisfies_application_contract() -> None:
    """The adapter should implement the processing port."""
    assert isinstance(
        NoOpUploadedDocumentProcessor(),
        UploadedDocumentProcessor,
    )


def test_no_op_processor_accepts_normalized_event() -> None:
    """The adapter should complete without producing a result."""
    processor = NoOpUploadedDocumentProcessor()

    result = processor.process(
        event=make_event(),
    )

    assert result is None


def test_no_op_processor_is_stateless() -> None:
    """Repeated calls should not accumulate processing state."""
    processor = NoOpUploadedDocumentProcessor()

    processor.process(
        event=make_event(),
    )
    processor.process(
        event=make_event().model_copy(
            update={
                "message_id": "message-002",
                "object_key": "documents/job-002/source.txt",
                "job_id": "job-002",
            }
        ),
    )

    assert vars(processor) == {}
