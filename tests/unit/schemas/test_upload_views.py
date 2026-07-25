"""Tests for document upload application views."""

import pytest
from pydantic import ValidationError

from clouddoc.schemas.upload_views import (
    DOCUMENT_UPLOAD_CONTENT_TYPE,
    PresignedDocumentUpload,
    build_document_object_key,
)


def test_builds_canonical_document_object_key() -> None:
    """A document job should own one canonical source object."""
    assert build_document_object_key("job-001") == "documents/job-001/source.txt"


def test_trims_job_id_when_building_object_key() -> None:
    """Surrounding whitespace should not enter the object key."""
    assert build_document_object_key("  job-001  ") == "documents/job-001/source.txt"


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        " ",
        "   ",
        "\t",
    ],
)
def test_rejects_blank_job_id(
    job_id: str,
) -> None:
    """A document object key requires a valid job identity."""
    with pytest.raises(
        ValueError,
        match="job_id must not be empty",
    ):
        build_document_object_key(job_id)


def test_creates_approved_upload_instructions() -> None:
    """Upload instructions should use the approved V1 contract."""
    upload = PresignedDocumentUpload.create(
        url="https://example.com/presigned-upload",
        object_key="documents/job-001/source.txt",
        expires_in_seconds=900,
    )

    assert upload.method == "PUT"
    assert upload.url == "https://example.com/presigned-upload"
    assert upload.headers == {
        "content-type": DOCUMENT_UPLOAD_CONTENT_TYPE,
    }
    assert upload.object_key == "documents/job-001/source.txt"
    assert upload.expires_in_seconds == 900


def test_trims_upload_url_and_object_key() -> None:
    """Transport values should be normalized before exposure."""
    upload = PresignedDocumentUpload.create(
        url="  https://example.com/presigned-upload  ",
        object_key="  documents/job-001/source.txt  ",
        expires_in_seconds=900,
    )

    assert upload.url == "https://example.com/presigned-upload"
    assert upload.object_key == "documents/job-001/source.txt"


@pytest.mark.parametrize(
    ("url", "object_key", "expected_message"),
    [
        (
            "",
            "documents/job-001/source.txt",
            "upload URL must not be empty",
        ),
        (
            "   ",
            "documents/job-001/source.txt",
            "upload URL must not be empty",
        ),
        (
            "https://example.com/presigned-upload",
            "",
            "object key must not be empty",
        ),
        (
            "https://example.com/presigned-upload",
            "   ",
            "object key must not be empty",
        ),
    ],
)
def test_rejects_blank_upload_values(
    url: str,
    object_key: str,
    expected_message: str,
) -> None:
    """Upload instructions require stable non-empty values."""
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        PresignedDocumentUpload.create(
            url=url,
            object_key=object_key,
            expires_in_seconds=900,
        )


@pytest.mark.parametrize(
    "expires_in_seconds",
    [
        0,
        -1,
        -900,
    ],
)
def test_rejects_non_positive_expiration(
    expires_in_seconds: int,
) -> None:
    """Presigned upload instructions must expire in the future."""
    with pytest.raises(ValidationError):
        PresignedDocumentUpload.create(
            url="https://example.com/presigned-upload",
            object_key="documents/job-001/source.txt",
            expires_in_seconds=expires_in_seconds,
        )


def test_upload_instructions_are_immutable() -> None:
    """Upload instructions should not change after creation."""
    upload = PresignedDocumentUpload.create(
        url="https://example.com/presigned-upload",
        object_key="documents/job-001/source.txt",
        expires_in_seconds=900,
    )

    with pytest.raises(ValidationError):
        upload.url = "https://example.com/other-upload"


def test_serializes_to_json_compatible_payload() -> None:
    """Upload instructions should serialize cleanly for handlers."""
    upload = PresignedDocumentUpload.create(
        url="https://example.com/presigned-upload",
        object_key="documents/job-001/source.txt",
        expires_in_seconds=900,
    )

    assert upload.model_dump(mode="json") == {
        "method": "PUT",
        "url": "https://example.com/presigned-upload",
        "headers": {
            "content-type": "text/plain",
        },
        "object_key": "documents/job-001/source.txt",
        "expires_in_seconds": 900,
    }


def test_direct_model_validation_rejects_wrong_method() -> None:
    """The public upload contract should remain PUT-only."""
    with pytest.raises(ValidationError):
        PresignedDocumentUpload(
            method="POST",
            url="https://example.com/presigned-upload",
            headers={
                "content-type": "text/plain",
            },
            object_key="documents/job-001/source.txt",
            expires_in_seconds=900,
        )
