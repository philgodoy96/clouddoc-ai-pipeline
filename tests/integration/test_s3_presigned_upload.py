"""Integration tests for S3 presigned document uploads."""

from urllib.parse import parse_qs, unquote, urlparse

import boto3
from botocore.config import Config
from moto import mock_aws

from clouddoc.infrastructure.s3_uploads import (
    S3PresignedDocumentUploadProvider,
)

BUCKET_NAME = "clouddoc-documents-test"


def test_generates_s3_v4_presigned_put_object_url() -> None:
    """The adapter should generate a correctly scoped S3 URL."""
    with mock_aws():
        s3_client = boto3.client(
            "s3",
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
            ),
        )
        s3_client.create_bucket(
            Bucket=BUCKET_NAME,
        )

        provider = S3PresignedDocumentUploadProvider(
            s3_client=s3_client,
            bucket_name=BUCKET_NAME,
            expiration_seconds=900,
        )

        upload = provider.create_upload(
            job_id="job-001",
        )

    parsed_url = urlparse(upload.url)
    query = parse_qs(parsed_url.query)

    assert upload.method == "PUT"
    assert upload.object_key == "documents/job-001/source.txt"
    assert upload.headers == {
        "content-type": "text/plain",
    }
    assert upload.expires_in_seconds == 900

    assert BUCKET_NAME in parsed_url.netloc
    assert unquote(parsed_url.path) == ("/documents/job-001/source.txt")
    assert query["X-Amz-Expires"] == [
        "900",
    ]
    assert "X-Amz-Signature" in query
    assert "X-Amz-Credential" in query
    assert "X-Amz-Date" in query

    signed_headers = query["X-Amz-SignedHeaders"][0].split(";")

    assert "content-type" in signed_headers
    assert "host" in signed_headers
