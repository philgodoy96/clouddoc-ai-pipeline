"""Integration tests for bounded S3 document text retrieval."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from clouddoc.application import (
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentValidationError,
)
from clouddoc.infrastructure import S3DocumentTextLoader

BUCKET_NAME = "clouddoc-document-retrieval-test"
OBJECT_KEY = "documents/job-001/source.txt"
MAX_SIZE_BYTES = 65_536


@pytest.fixture
def s3_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Any]:
    """Create an isolated Moto-backed versioned S3 bucket."""
    monkeypatch.setenv(
        "AWS_ACCESS_KEY_ID",
        "testing",
    )
    monkeypatch.setenv(
        "AWS_SECRET_ACCESS_KEY",
        "testing",
    )
    monkeypatch.setenv(
        "AWS_SESSION_TOKEN",
        "testing",
    )
    monkeypatch.setenv(
        "AWS_DEFAULT_REGION",
        "us-east-1",
    )

    with mock_aws(
        config={
            "core": {
                "service_whitelist": [
                    "s3",
                ],
            }
        }
    ):
        client = boto3.client(
            "s3",
            region_name="us-east-1",
        )
        client.create_bucket(
            Bucket=BUCKET_NAME,
        )
        client.put_bucket_versioning(
            Bucket=BUCKET_NAME,
            VersioningConfiguration={
                "Status": "Enabled",
            },
        )

        yield client


@pytest.fixture
def loader(
    s3_client: Any,
) -> S3DocumentTextLoader:
    """Create a document loader connected to the Moto bucket."""
    return S3DocumentTextLoader(
        s3_client=s3_client,
        bucket_name=BUCKET_NAME,
        max_size_bytes=MAX_SIZE_BYTES,
    )


def put_document(
    s3_client: Any,
    *,
    content: bytes,
    content_type: str = "text/plain",
    object_key: str = OBJECT_KEY,
) -> DocumentObjectReference:
    """Store one object and return its trusted event-style reference."""
    response = s3_client.put_object(
        Bucket=BUCKET_NAME,
        Key=object_key,
        Body=content,
        ContentType=content_type,
    )

    return DocumentObjectReference(
        object_key=object_key,
        expected_size_bytes=len(content),
        expected_etag=response["ETag"],
        version_id=response.get("VersionId"),
    )


def test_loads_plain_text_document_from_s3(
    s3_client: Any,
    loader: S3DocumentTextLoader,
) -> None:
    """A valid S3 object should round-trip through the adapter."""
    content = "Olá, CloudDoc!".encode()
    reference = put_document(
        s3_client,
        content=content,
    )

    document = loader.load(
        reference=reference,
    )

    assert document.object_key == OBJECT_KEY
    assert document.content == "Olá, CloudDoc!"
    assert document.content_type == "text/plain"
    assert document.size_bytes == len(content)
    assert document.etag == reference.expected_etag.strip('"')
    assert document.version_id == reference.version_id


def test_loads_the_exact_referenced_object_version(
    s3_client: Any,
    loader: S3DocumentTextLoader,
) -> None:
    """A versioned event should load its original object version."""
    first_content = b"first document version"
    first_reference = put_document(
        s3_client,
        content=first_content,
    )

    second_reference = put_document(
        s3_client,
        content=b"replacement document version",
    )

    assert first_reference.version_id != second_reference.version_id

    document = loader.load(
        reference=first_reference,
    )

    assert document.content == first_content.decode("utf-8")
    assert document.version_id == first_reference.version_id
    assert document.etag == (first_reference.expected_etag.strip('"'))


def test_rejects_missing_document_object(
    loader: S3DocumentTextLoader,
) -> None:
    """A missing S3 key should use the normalized not-found error."""
    reference = DocumentObjectReference(
        object_key="documents/missing-job/source.txt",
        expected_size_bytes=0,
        expected_etag="missing-etag",
        version_id=None,
    )

    with pytest.raises(
        DocumentNotFoundError,
        match="document object was not found",
    ):
        loader.load(
            reference=reference,
        )


def test_rejects_unsupported_s3_content_type(
    s3_client: Any,
    loader: S3DocumentTextLoader,
) -> None:
    """Only canonical text/plain objects should be accepted."""
    reference = put_document(
        s3_client,
        content=b'{"document": "content"}',
        content_type="application/json",
    )

    with pytest.raises(
        DocumentValidationError,
        match="document content type must be text/plain",
    ):
        loader.load(
            reference=reference,
        )


def test_rejects_invalid_utf8_s3_body(
    s3_client: Any,
    loader: S3DocumentTextLoader,
) -> None:
    """Binary content labeled as text must still decode strictly."""
    reference = put_document(
        s3_client,
        content=b"\xff\xfe\xfd",
    )

    with pytest.raises(
        DocumentValidationError,
        match="document body must be valid UTF-8",
    ):
        loader.load(
            reference=reference,
        )


def test_rejects_document_above_configured_limit(
    s3_client: Any,
) -> None:
    """Known oversized objects should fail before body retrieval."""
    content = b"a" * 11
    reference = put_document(
        s3_client,
        content=content,
    )
    bounded_loader = S3DocumentTextLoader(
        s3_client=s3_client,
        bucket_name=BUCKET_NAME,
        max_size_bytes=10,
    )

    with pytest.raises(
        DocumentValidationError,
        match="document exceeds the configured size limit",
    ):
        bounded_loader.load(
            reference=reference,
        )


def test_rejects_replaced_current_object_when_event_has_no_version(
    s3_client: Any,
    loader: S3DocumentTextLoader,
) -> None:
    """An unversioned stale event must not process a replacement object."""
    original_reference = put_document(
        s3_client,
        content=b"original content",
    )

    put_document(
        s3_client,
        content=b"replacement content",
    )

    stale_unversioned_reference = DocumentObjectReference(
        object_key=OBJECT_KEY,
        expected_size_bytes=(original_reference.expected_size_bytes),
        expected_etag=original_reference.expected_etag,
        version_id=None,
    )

    with pytest.raises(
        DocumentValidationError,
        match=(
            r"document size does not match the uploaded event"
            r"|document ETag does not match the uploaded event"
        ),
    ):
        loader.load(
            reference=stale_unversioned_reference,
        )


def test_preserves_empty_plain_text_document(
    s3_client: Any,
    loader: S3DocumentTextLoader,
) -> None:
    """A zero-byte text document is structurally valid."""
    reference = put_document(
        s3_client,
        content=b"",
    )

    document = loader.load(
        reference=reference,
    )

    assert document.content == ""
    assert document.size_bytes == 0
    assert document.content_type == "text/plain"
