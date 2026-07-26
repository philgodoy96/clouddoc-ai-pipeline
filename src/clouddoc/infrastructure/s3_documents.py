"""Bounded S3 implementation of the document text loader contract."""

from contextlib import suppress
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from clouddoc.application.document_ports import (
    DocumentDependencyError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentTextLoader,
    DocumentValidationError,
    LoadedTextDocument,
)

SUPPORTED_DOCUMENT_CONTENT_TYPE = "text/plain"

_NOT_FOUND_ERROR_CODES = {
    "404",
    "NoSuchKey",
    "NoSuchVersion",
    "NotFound",
}


class S3DocumentTextLoader:
    """Load bounded UTF-8 plain-text documents from a trusted S3 bucket."""

    def __init__(
        self,
        *,
        s3_client: Any,
        bucket_name: str,
        max_size_bytes: int,
    ) -> None:
        """Initialize the loader with trusted runtime dependencies."""
        normalized_bucket_name = bucket_name.strip()

        if not normalized_bucket_name:
            raise ValueError("bucket_name must not be empty")

        if isinstance(max_size_bytes, bool):
            raise ValueError("max_size_bytes must be a positive integer")

        if not isinstance(max_size_bytes, int):
            raise ValueError("max_size_bytes must be a positive integer")

        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes must be a positive integer")

        self._s3_client = s3_client
        self._bucket_name = normalized_bucket_name
        self._max_size_bytes = max_size_bytes

    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Load and validate one complete document object."""
        self._validate_expected_size(reference)

        response = self._get_object(reference)
        body = response.get("Body")

        if body is None:
            raise DocumentValidationError(
                "S3 returned a document without a response body"
            )

        try:
            return self._load_response(
                reference=reference,
                response=response,
                body=body,
            )
        finally:
            close = getattr(
                body,
                "close",
                None,
            )

            if callable(close):
                with suppress(Exception):
                    close()

    def _get_object(
        self,
        reference: DocumentObjectReference,
    ) -> dict[str, Any]:
        """Retrieve one object from the trusted bucket."""
        request: dict[str, str] = {
            "Bucket": self._bucket_name,
            "Key": reference.object_key,
        }

        if reference.version_id is not None:
            request["VersionId"] = reference.version_id

        try:
            response = self._s3_client.get_object(
                **request,
            )
        except ClientError as error:
            error_code = str(
                error.response.get(
                    "Error",
                    {},
                ).get(
                    "Code",
                    "",
                )
            )

            if error_code in _NOT_FOUND_ERROR_CODES:
                raise DocumentNotFoundError("document object was not found") from error

            raise DocumentDependencyError(
                "failed to retrieve document object from S3"
            ) from error
        except BotoCoreError as error:
            raise DocumentDependencyError(
                "failed to retrieve document object from S3"
            ) from error

        if not isinstance(response, dict):
            raise DocumentValidationError("S3 returned an invalid document response")

        return response

    def _load_response(
        self,
        *,
        reference: DocumentObjectReference,
        response: dict[str, Any],
        body: Any,
    ) -> LoadedTextDocument:
        """Validate metadata, read a bounded body, and decode UTF-8."""
        content_length = self._require_content_length(response)
        content_type = self._require_content_type(response)
        etag = self._require_etag(response)
        version_id = self._require_version_id(
            reference=reference,
            response=response,
        )

        self._validate_response_identity(
            reference=reference,
            content_length=content_length,
            etag=etag,
        )

        try:
            content_bytes = body.read(self._max_size_bytes + 1)
        except (BotoCoreError, OSError) as error:
            raise DocumentDependencyError(
                "failed to read document body from S3"
            ) from error

        if not isinstance(content_bytes, bytes):
            raise DocumentValidationError("S3 returned a non-binary document body")

        if len(content_bytes) > self._max_size_bytes:
            raise DocumentValidationError("document exceeds the configured size limit")

        if len(content_bytes) != content_length:
            raise DocumentValidationError(
                "document body size does not match S3 metadata"
            )

        try:
            content = content_bytes.decode(
                "utf-8",
                errors="strict",
            )
        except UnicodeDecodeError as error:
            raise DocumentValidationError(
                "document body must be valid UTF-8"
            ) from error

        return LoadedTextDocument(
            object_key=reference.object_key,
            content=content,
            content_type=content_type,
            size_bytes=content_length,
            etag=etag,
            version_id=version_id,
        )

    def _validate_expected_size(
        self,
        reference: DocumentObjectReference,
    ) -> None:
        """Reject oversized events before issuing an S3 request."""
        if reference.expected_size_bytes > self._max_size_bytes:
            raise DocumentValidationError("document exceeds the configured size limit")

    def _require_content_length(
        self,
        response: dict[str, Any],
    ) -> int:
        """Return one valid bounded S3 content length."""
        content_length = response.get("ContentLength")

        if isinstance(content_length, bool):
            raise DocumentValidationError("S3 returned an invalid document size")

        if not isinstance(content_length, int):
            raise DocumentValidationError("S3 returned an invalid document size")

        if content_length < 0:
            raise DocumentValidationError("S3 returned an invalid document size")

        if content_length > self._max_size_bytes:
            raise DocumentValidationError("document exceeds the configured size limit")

        return content_length

    @staticmethod
    def _require_content_type(
        response: dict[str, Any],
    ) -> str:
        """Return the canonical supported document content type."""
        content_type = response.get("ContentType")

        if content_type != SUPPORTED_DOCUMENT_CONTENT_TYPE:
            raise DocumentValidationError("document content type must be text/plain")

        return content_type

    @staticmethod
    def _require_etag(
        response: dict[str, Any],
    ) -> str:
        """Return a normalized S3 entity tag."""
        etag = response.get("ETag")

        if not isinstance(etag, str):
            raise DocumentValidationError("S3 returned an invalid document ETag")

        normalized_etag = _normalize_etag(etag)

        if not normalized_etag:
            raise DocumentValidationError("S3 returned an invalid document ETag")

        return normalized_etag

    @staticmethod
    def _require_version_id(
        *,
        reference: DocumentObjectReference,
        response: dict[str, Any],
    ) -> str | None:
        """Validate version identity when the event supplies one."""
        version_id = response.get("VersionId")

        if version_id is not None:
            if not isinstance(version_id, str):
                raise DocumentValidationError("S3 returned an invalid document version")

            version_id = version_id.strip()

            if not version_id:
                raise DocumentValidationError("S3 returned an invalid document version")

        if reference.version_id is not None and version_id != reference.version_id:
            raise DocumentValidationError(
                "document version does not match the uploaded event"
            )

        return version_id

    @staticmethod
    def _validate_response_identity(
        *,
        reference: DocumentObjectReference,
        content_length: int,
        etag: str,
    ) -> None:
        """Ensure the retrieved object matches trusted event metadata."""
        if content_length != reference.expected_size_bytes:
            raise DocumentValidationError(
                "document size does not match the uploaded event"
            )

        if etag != _normalize_etag(reference.expected_etag):
            raise DocumentValidationError(
                "document ETag does not match the uploaded event"
            )


def _normalize_etag(
    etag: str,
) -> str:
    """Normalize optional S3 response quotation around an ETag."""
    normalized_etag = etag.strip()

    if (
        len(normalized_etag) >= 2
        and normalized_etag[0] == '"'
        and normalized_etag[-1] == '"'
    ):
        normalized_etag = normalized_etag[1:-1]

    return normalized_etag.strip()


_loader_contract_check: DocumentTextLoader
_loader_contract_check = S3DocumentTextLoader(
    s3_client=None,
    bucket_name="contract-check",
    max_size_bytes=1,
)
