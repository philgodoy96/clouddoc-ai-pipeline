"""Tests for normalized uploaded-document event models."""

import pytest
from pydantic import ValidationError

from clouddoc.delivery.events.models import UploadedDocumentEvent


def make_event(
    **overrides: object,
) -> UploadedDocumentEvent:
    """Create a deterministic uploaded-document event."""
    values: dict[str, object] = {
        "message_id": "message-001",
        "event_name": "ObjectCreated:Put",
        "bucket_name": "clouddoc-documents",
        "object_key": "documents/job-001/source.txt",
        "job_id": "job-001",
        "object_size": 128,
        "etag": "etag-001",
        "sequencer": "0055AED6DCD90281E5",
        "version_id": None,
    }
    values.update(overrides)

    return UploadedDocumentEvent(**values)


def test_creates_normalized_uploaded_document_event() -> None:
    """A valid S3 upload event should preserve normalized values."""
    event = make_event()

    assert event.message_id == "message-001"
    assert event.event_name == "ObjectCreated:Put"
    assert event.bucket_name == "clouddoc-documents"
    assert event.object_key == "documents/job-001/source.txt"
    assert event.job_id == "job-001"
    assert event.object_size == 128
    assert event.etag == "etag-001"
    assert event.sequencer == "0055AED6DCD90281E5"
    assert event.version_id is None


@pytest.mark.parametrize(
    "event_name",
    [
        "ObjectCreated:Put",
        "ObjectCreated:Post",
        "ObjectCreated:Copy",
        "ObjectCreated:CompleteMultipartUpload",
    ],
)
def test_accepts_object_created_event_family(
    event_name: str,
) -> None:
    """The model should accept all ObjectCreated subtypes."""
    event = make_event(
        event_name=event_name,
    )

    assert event.event_name == event_name


@pytest.mark.parametrize(
    "event_name",
    [
        "ObjectRemoved:Delete",
        "ObjectRestore:Completed",
        "ReducedRedundancyLostObject",
        "ObjectCreated:",
    ],
)
def test_rejects_unsupported_event_name(
    event_name: str,
) -> None:
    """Only concrete ObjectCreated event names are valid."""
    with pytest.raises(ValidationError):
        make_event(
            event_name=event_name,
        )


def test_accepts_optional_s3_metadata() -> None:
    """S3 metadata may be absent from a valid notification."""
    event = make_event(
        etag=None,
        sequencer=None,
        version_id=None,
    )

    assert event.etag is None
    assert event.sequencer is None
    assert event.version_id is None


@pytest.mark.parametrize(
    "field_name",
    [
        "message_id",
        "event_name",
        "bucket_name",
        "object_key",
        "job_id",
        "etag",
        "sequencer",
        "version_id",
    ],
)
def test_rejects_blank_string_values(
    field_name: str,
) -> None:
    """Present string values must contain meaningful content."""
    with pytest.raises(
        ValidationError,
        match="event string values must not be blank",
    ):
        make_event(
            **{
                field_name: "   ",
            }
        )


@pytest.mark.parametrize(
    "object_size",
    [
        -1,
        -128,
    ],
)
def test_rejects_negative_object_size(
    object_size: int,
) -> None:
    """S3 object size cannot be negative."""
    with pytest.raises(ValidationError):
        make_event(
            object_size=object_size,
        )


@pytest.mark.parametrize(
    "object_size",
    [
        True,
        False,
        128.0,
        "128",
        None,
    ],
)
def test_rejects_non_integer_object_size(
    object_size: object,
) -> None:
    """Object size should not be silently coerced."""
    with pytest.raises(ValidationError):
        make_event(
            object_size=object_size,
        )


def test_accepts_zero_byte_object_size() -> None:
    """Transport normalization may represent a zero-byte upload."""
    event = make_event(
        object_size=0,
    )

    assert event.object_size == 0


@pytest.mark.parametrize(
    "object_key",
    [
        "documents/job-001/other.txt",
        "documents/job-001/source.pdf",
        "uploads/job-001/source.txt",
        "documents/source.txt",
        "documents//source.txt",
        "documents/job-001/nested/source.txt",
    ],
)
def test_rejects_non_canonical_object_key(
    object_key: str,
) -> None:
    """Only the approved source-document key is accepted."""
    with pytest.raises(
        ValidationError,
        match="object_key must be a canonical document object key",
    ):
        make_event(
            object_key=object_key,
        )


def test_rejects_job_id_that_does_not_match_object_key() -> None:
    """The event job identity must agree with key ownership."""
    with pytest.raises(
        ValidationError,
        match="job_id must match the canonical document object key",
    ):
        make_event(
            object_key="documents/job-001/source.txt",
            job_id="job-002",
        )


def test_event_is_immutable() -> None:
    """Normalized delivery events should not change after parsing."""
    event = make_event()

    with pytest.raises(ValidationError):
        event.job_id = "job-002"


def test_serializes_to_json_compatible_payload() -> None:
    """The normalized event should serialize deterministically."""
    event = make_event()

    assert event.model_dump(mode="json") == {
        "message_id": "message-001",
        "event_name": "ObjectCreated:Put",
        "bucket_name": "clouddoc-documents",
        "object_key": "documents/job-001/source.txt",
        "job_id": "job-001",
        "object_size": 128,
        "etag": "etag-001",
        "sequencer": "0055AED6DCD90281E5",
        "version_id": None,
    }
