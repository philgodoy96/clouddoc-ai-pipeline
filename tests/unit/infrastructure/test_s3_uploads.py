"""Tests for the S3 presigned document upload provider."""

from typing import Any

import pytest
from botocore.exceptions import ClientError

from clouddoc.application.upload_ports import (
    DocumentUploadProvider,
    DocumentUploadProviderError,
)
from clouddoc.infrastructure.s3_uploads import (
    S3PresignedDocumentUploadProvider,
)


class RecordingS3Client:
    """S3 client double that records presigning requests."""

    def __init__(
        self,
        *,
        returned_url: object = ("https://documents.example.com/presigned-upload"),
    ) -> None:
        """Initialize the fake client."""
        self.returned_url = returned_url
        self.calls: list[dict[str, Any]] = []

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: dict[str, object],
        ExpiresIn: int,
        HttpMethod: str,
    ) -> object:
        """Record and return the configured presigned URL."""
        self.calls.append(
            {
                "ClientMethod": ClientMethod,
                "Params": Params,
                "ExpiresIn": ExpiresIn,
                "HttpMethod": HttpMethod,
            }
        )

        return self.returned_url


class FailingS3Client:
    """S3 client double that raises an SDK error."""

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: dict[str, object],
        ExpiresIn: int,
        HttpMethod: str,
    ) -> str:
        """Simulate an S3 presigning failure."""
        raise ClientError(
            {
                "Error": {
                    "Code": "AccessDenied",
                    "Message": "Access denied",
                }
            },
            "GeneratePresignedUrl",
        )


def make_provider(
    *,
    client: object | None = None,
    bucket_name: str = "clouddoc-documents",
    expiration_seconds: int = 900,
) -> S3PresignedDocumentUploadProvider:
    """Create an S3 upload provider with deterministic configuration."""
    return S3PresignedDocumentUploadProvider(
        s3_client=client or RecordingS3Client(),
        bucket_name=bucket_name,
        expiration_seconds=expiration_seconds,
    )


def test_provider_satisfies_upload_contract() -> None:
    """The S3 adapter should implement the application port."""
    assert isinstance(
        make_provider(),
        DocumentUploadProvider,
    )


def test_creates_presigned_put_object_upload() -> None:
    """The provider should sign the approved S3 PutObject request."""
    client = RecordingS3Client()
    provider = make_provider(client=client)

    upload = provider.create_upload(
        job_id="job-001",
    )

    assert client.calls == [
        {
            "ClientMethod": "put_object",
            "Params": {
                "Bucket": "clouddoc-documents",
                "Key": "documents/job-001/source.txt",
                "ContentType": "text/plain",
            },
            "ExpiresIn": 900,
            "HttpMethod": "PUT",
        }
    ]
    assert upload.method == "PUT"
    assert upload.headers == {
        "content-type": "text/plain",
    }
    assert upload.object_key == "documents/job-001/source.txt"
    assert upload.expires_in_seconds == 900


def test_uses_configured_bucket_and_expiration() -> None:
    """Runtime configuration should control bucket and URL lifetime."""
    client = RecordingS3Client()
    provider = make_provider(
        client=client,
        bucket_name="custom-documents-bucket",
        expiration_seconds=600,
    )

    upload = provider.create_upload(
        job_id="job-special",
    )

    call = client.calls[0]

    assert call["Params"] == {
        "Bucket": "custom-documents-bucket",
        "Key": "documents/job-special/source.txt",
        "ContentType": "text/plain",
    }
    assert call["ExpiresIn"] == 600
    assert upload.expires_in_seconds == 600


def test_trims_bucket_name() -> None:
    """Surrounding whitespace should not enter S3 requests."""
    client = RecordingS3Client()
    provider = make_provider(
        client=client,
        bucket_name="  clouddoc-documents  ",
    )

    provider.create_upload(
        job_id="job-001",
    )

    assert client.calls[0]["Params"]["Bucket"] == ("clouddoc-documents")


@pytest.mark.parametrize(
    "bucket_name",
    [
        "",
        " ",
        "   ",
        "\t",
    ],
)
def test_rejects_blank_bucket_name(
    bucket_name: str,
) -> None:
    """The provider requires a configured S3 bucket."""
    with pytest.raises(
        ValueError,
        match="bucket_name must not be empty",
    ):
        make_provider(
            bucket_name=bucket_name,
        )


@pytest.mark.parametrize(
    "expiration_seconds",
    [
        0,
        -1,
        True,
        False,
        900.0,
        "900",
    ],
)
def test_rejects_invalid_expiration(
    expiration_seconds: object,
) -> None:
    """Presigned URL expiration must be a positive integer."""
    with pytest.raises(
        ValueError,
        match="expiration_seconds must be a positive integer",
    ):
        make_provider(
            expiration_seconds=expiration_seconds,
        )


def test_translates_s3_sdk_failure() -> None:
    """SDK failures should not cross the upload-provider boundary."""
    provider = make_provider(
        client=FailingS3Client(),
    )

    with pytest.raises(
        DocumentUploadProviderError,
        match="failed to create document upload instructions",
    ) as captured_error:
        provider.create_upload(
            job_id="job-001",
        )

    assert isinstance(
        captured_error.value.__cause__,
        ClientError,
    )


@pytest.mark.parametrize(
    "returned_url",
    [
        None,
        123,
        "",
        "   ",
    ],
)
def test_rejects_invalid_presigned_url(
    returned_url: object,
) -> None:
    """Invalid SDK results must not become client instructions."""
    provider = make_provider(
        client=RecordingS3Client(
            returned_url=returned_url,
        ),
    )

    with pytest.raises(
        DocumentUploadProviderError,
        match="S3 returned an invalid presigned upload URL",
    ):
        provider.create_upload(
            job_id="job-001",
        )


def test_does_not_expose_bucket_in_upload_view() -> None:
    """The public upload contract should not expose bucket metadata."""
    upload = make_provider().create_upload(
        job_id="job-001",
    )

    payload = upload.model_dump(mode="json")

    assert "bucket" not in payload
    assert "bucket_name" not in payload
