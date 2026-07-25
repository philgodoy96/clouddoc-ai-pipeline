"""S3 implementation of the document upload provider contract."""

from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from clouddoc.application.upload_ports import (
    DocumentUploadProvider,
    DocumentUploadProviderError,
)
from clouddoc.schemas.upload_views import (
    DOCUMENT_UPLOAD_CONTENT_TYPE,
    PresignedDocumentUpload,
    build_document_object_key,
)


class S3PresignedDocumentUploadProvider:
    """Create server-owned presigned S3 PutObject instructions."""

    def __init__(
        self,
        *,
        s3_client: Any,
        bucket_name: str,
        expiration_seconds: int,
    ) -> None:
        """Initialize the provider with validated runtime configuration."""
        normalized_bucket_name = bucket_name.strip()

        if not normalized_bucket_name:
            raise ValueError("bucket_name must not be empty")

        if isinstance(expiration_seconds, bool):
            raise ValueError("expiration_seconds must be a positive integer")

        if not isinstance(expiration_seconds, int):
            raise ValueError("expiration_seconds must be a positive integer")

        if expiration_seconds <= 0:
            raise ValueError("expiration_seconds must be a positive integer")

        self._s3_client = s3_client
        self._bucket_name = normalized_bucket_name
        self._expiration_seconds = expiration_seconds

    def create_upload(
        self,
        *,
        job_id: str,
    ) -> PresignedDocumentUpload:
        """Create presigned PutObject instructions for one job."""
        object_key = build_document_object_key(job_id)

        try:
            url = self._s3_client.generate_presigned_url(
                ClientMethod="put_object",
                Params={
                    "Bucket": self._bucket_name,
                    "Key": object_key,
                    "ContentType": DOCUMENT_UPLOAD_CONTENT_TYPE,
                },
                ExpiresIn=self._expiration_seconds,
                HttpMethod="PUT",
            )
        except (BotoCoreError, ClientError) as error:
            raise DocumentUploadProviderError(
                "failed to create document upload instructions"
            ) from error

        if not isinstance(url, str):
            raise DocumentUploadProviderError(
                "S3 returned an invalid presigned upload URL"
            )

        normalized_url = url.strip()

        if not normalized_url:
            raise DocumentUploadProviderError(
                "S3 returned an invalid presigned upload URL"
            )

        return PresignedDocumentUpload.create(
            url=normalized_url,
            object_key=object_key,
            expires_in_seconds=self._expiration_seconds,
        )


_upload_provider_contract_check: DocumentUploadProvider
_upload_provider_contract_check = S3PresignedDocumentUploadProvider(
    s3_client=None,
    bucket_name="contract-check",
    expiration_seconds=1,
)
