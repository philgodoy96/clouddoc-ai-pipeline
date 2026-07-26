"""Tests for bounded S3 document text retrieval."""

from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from clouddoc.application import (
    DocumentDependencyError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentTextLoader,
    DocumentValidationError,
)
from clouddoc.infrastructure.s3_documents import (
    S3DocumentTextLoader,
)

BUCKET_NAME = "clouddoc-documents"
OBJECT_KEY = "documents/job-001/source.txt"
CONTENT = "Olá, CloudDoc!"
CONTENT_BYTES = CONTENT.encode("utf-8")
CONTENT_SIZE = len(CONTENT_BYTES)
ETAG = "0123456789abcdef"
VERSION_ID = "version-001"
MAX_SIZE_BYTES = 65_536


class RecordingBody:
    """Streaming-body double with bounded-read tracking."""

    def __init__(
        self,
        content: object = CONTENT_BYTES,
        *,
        read_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        """Initialize the body double."""
        self._content = content
        self._read_error = read_error
        self._close_error = close_error
        self.read_amounts: list[int] = []
        self.close_calls = 0

    def read(
        self,
        amount: int,
    ) -> object:
        """Record the bound and return configured content."""
        self.read_amounts.append(amount)

        if self._read_error is not None:
            raise self._read_error

        return self._content

    def close(self) -> None:
        """Record body cleanup."""
        self.close_calls += 1

        if self._close_error is not None:
            raise self._close_error


class RecordingS3Client:
    """S3 client double returning one configured response."""

    def __init__(
        self,
        *,
        response: object | None = None,
    ) -> None:
        """Initialize the fake client."""
        self.response = response if response is not None else make_response()
        self.calls: list[dict[str, str]] = []

    def get_object(
        self,
        **request: str,
    ) -> object:
        """Record and return one GetObject response."""
        self.calls.append(request)
        return self.response


class FailingS3Client:
    """S3 client double raising one configured SDK failure."""

    def __init__(
        self,
        error: Exception,
    ) -> None:
        """Store the configured failure."""
        self._error = error

    def get_object(
        self,
        **request: str,
    ) -> dict[str, Any]:
        """Raise the configured failure."""
        del request
        raise self._error


def make_response(
    *,
    body: object | None = None,
    content_length: object = CONTENT_SIZE,
    content_type: object = "text/plain",
    etag: object = f'"{ETAG}"',
    version_id: object = VERSION_ID,
) -> dict[str, object]:
    """Create one deterministic S3 GetObject response."""
    return {
        "Body": body or RecordingBody(),
        "ContentLength": content_length,
        "ContentType": content_type,
        "ETag": etag,
        "VersionId": version_id,
    }


def make_reference(
    *,
    expected_size_bytes: int = CONTENT_SIZE,
    expected_etag: str = ETAG,
    version_id: str | None = VERSION_ID,
) -> DocumentObjectReference:
    """Create one deterministic object reference."""
    return DocumentObjectReference(
        object_key=OBJECT_KEY,
        expected_size_bytes=expected_size_bytes,
        expected_etag=expected_etag,
        version_id=version_id,
    )


def make_loader(
    *,
    client: object | None = None,
    bucket_name: str = BUCKET_NAME,
    max_size_bytes: int = MAX_SIZE_BYTES,
) -> S3DocumentTextLoader:
    """Create the loader with deterministic dependencies."""
    return S3DocumentTextLoader(
        s3_client=client or RecordingS3Client(),
        bucket_name=bucket_name,
        max_size_bytes=max_size_bytes,
    )


def make_client_error(
    code: str,
) -> ClientError:
    """Create one deterministic S3 ClientError."""
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": code,
            }
        },
        "GetObject",
    )


def test_loader_satisfies_application_contract() -> None:
    """The S3 adapter should satisfy the application port."""
    assert isinstance(
        make_loader(),
        DocumentTextLoader,
    )


def test_loads_plain_text_document_from_trusted_bucket() -> None:
    """The loader should return validated UTF-8 text."""
    body = RecordingBody()
    client = RecordingS3Client(
        response=make_response(
            body=body,
        )
    )
    loader = make_loader(
        client=client,
    )

    document = loader.load(
        reference=make_reference(),
    )

    assert client.calls == [
        {
            "Bucket": BUCKET_NAME,
            "Key": OBJECT_KEY,
            "VersionId": VERSION_ID,
        }
    ]
    assert body.read_amounts == [
        MAX_SIZE_BYTES + 1,
    ]
    assert body.close_calls == 1

    assert document.object_key == OBJECT_KEY
    assert document.content == CONTENT
    assert document.content_type == "text/plain"
    assert document.size_bytes == CONTENT_SIZE
    assert document.etag == ETAG
    assert document.version_id == VERSION_ID


def test_omits_version_id_for_unversioned_reference() -> None:
    """Unversioned events should use the current object version."""
    client = RecordingS3Client(
        response=make_response(
            version_id=None,
        )
    )
    loader = make_loader(
        client=client,
    )

    document = loader.load(
        reference=make_reference(
            version_id=None,
        )
    )

    assert client.calls == [
        {
            "Bucket": BUCKET_NAME,
            "Key": OBJECT_KEY,
        }
    ]
    assert document.version_id is None


def test_trims_bucket_name() -> None:
    """Whitespace should not enter S3 requests."""
    client = RecordingS3Client()
    loader = make_loader(
        client=client,
        bucket_name="  clouddoc-documents  ",
    )

    loader.load(
        reference=make_reference(),
    )

    assert client.calls[0]["Bucket"] == BUCKET_NAME


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
    """The loader requires a trusted bucket."""
    with pytest.raises(
        ValueError,
        match="bucket_name must not be empty",
    ):
        make_loader(
            bucket_name=bucket_name,
        )


@pytest.mark.parametrize(
    "max_size_bytes",
    [
        0,
        -1,
        True,
        False,
        1.5,
        "65536",
    ],
)
def test_rejects_invalid_maximum_size(
    max_size_bytes: object,
) -> None:
    """The loader requires one positive integer bound."""
    with pytest.raises(
        ValueError,
        match="max_size_bytes must be a positive integer",
    ):
        S3DocumentTextLoader(
            s3_client=RecordingS3Client(),
            bucket_name=BUCKET_NAME,
            max_size_bytes=max_size_bytes,
        )


def test_rejects_oversized_event_before_s3_request() -> None:
    """Known oversized objects should not consume an S3 read."""
    client = RecordingS3Client()
    loader = make_loader(
        client=client,
        max_size_bytes=10,
    )

    with pytest.raises(
        DocumentValidationError,
        match="document exceeds the configured size limit",
    ):
        loader.load(
            reference=make_reference(
                expected_size_bytes=11,
            )
        )

    assert client.calls == []


@pytest.mark.parametrize(
    "error_code",
    [
        "404",
        "NoSuchKey",
        "NoSuchVersion",
        "NotFound",
    ],
)
def test_translates_missing_object_errors(
    error_code: str,
) -> None:
    """Missing object variants should share one application error."""
    loader = make_loader(client=FailingS3Client(make_client_error(error_code)))

    with pytest.raises(
        DocumentNotFoundError,
        match="document object was not found",
    ) as captured_error:
        loader.load(
            reference=make_reference(),
        )

    assert isinstance(
        captured_error.value.__cause__,
        ClientError,
    )


@pytest.mark.parametrize(
    "error",
    [
        make_client_error("AccessDenied"),
        make_client_error("SlowDown"),
        make_client_error("InternalError"),
        EndpointConnectionError(endpoint_url="https://s3.example.com"),
    ],
)
def test_translates_s3_dependency_failures(
    error: Exception,
) -> None:
    """SDK failures should not cross the infrastructure boundary."""
    loader = make_loader(client=FailingS3Client(error))

    with pytest.raises(
        DocumentDependencyError,
        match="failed to retrieve document object from S3",
    ) as captured_error:
        loader.load(
            reference=make_reference(),
        )

    assert captured_error.value.__cause__ is error


def test_rejects_invalid_s3_response() -> None:
    """GetObject must return a response mapping."""
    loader = make_loader(
        client=RecordingS3Client(
            response="invalid",
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="S3 returned an invalid document response",
    ):
        loader.load(
            reference=make_reference(),
        )


def test_rejects_missing_response_body() -> None:
    """A successful response must contain a readable body."""
    loader = make_loader(
        client=RecordingS3Client(
            response={
                "ContentLength": CONTENT_SIZE,
                "ContentType": "text/plain",
                "ETag": f'"{ETAG}"',
                "VersionId": VERSION_ID,
            }
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="without a response body",
    ):
        loader.load(
            reference=make_reference(),
        )


@pytest.mark.parametrize(
    "content_length",
    [
        None,
        "15",
        -1,
        True,
    ],
)
def test_rejects_invalid_content_length(
    content_length: object,
) -> None:
    """S3 size metadata must be a non-negative integer."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                content_length=content_length,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="S3 returned an invalid document size",
    ):
        loader.load(
            reference=make_reference(),
        )

    assert body.close_calls == 1


def test_rejects_oversized_s3_metadata() -> None:
    """Actual S3 metadata must remain within the configured limit."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                content_length=11,
            )
        ),
        max_size_bytes=10,
    )

    with pytest.raises(
        DocumentValidationError,
        match="document exceeds the configured size limit",
    ):
        loader.load(
            reference=make_reference(
                expected_size_bytes=10,
            )
        )

    assert body.read_amounts == []
    assert body.close_calls == 1


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "",
        "application/json",
        "text/html",
        "text/plain; charset=utf-8",
    ],
)
def test_rejects_unsupported_content_type(
    content_type: object,
) -> None:
    """Only canonical text/plain documents are supported."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                content_type=content_type,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="document content type must be text/plain",
    ):
        loader.load(
            reference=make_reference(),
        )

    assert body.read_amounts == []
    assert body.close_calls == 1


@pytest.mark.parametrize(
    "etag",
    [
        None,
        "",
        "   ",
        123,
    ],
)
def test_rejects_invalid_response_etag(
    etag: object,
) -> None:
    """Retrieved objects require a meaningful ETag."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                etag=etag,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="S3 returned an invalid document ETag",
    ):
        loader.load(
            reference=make_reference(),
        )

    assert body.close_calls == 1


def test_rejects_event_and_s3_size_mismatch() -> None:
    """A replaced object must not be processed silently."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="document size does not match the uploaded event",
    ):
        loader.load(
            reference=make_reference(
                expected_size_bytes=CONTENT_SIZE - 1,
            )
        )

    assert body.read_amounts == []
    assert body.close_calls == 1


def test_rejects_event_and_s3_etag_mismatch() -> None:
    """The loaded object must match trusted event identity."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="document ETag does not match the uploaded event",
    ):
        loader.load(
            reference=make_reference(
                expected_etag="different-etag",
            )
        )

    assert body.read_amounts == []
    assert body.close_calls == 1


def test_rejects_version_mismatch() -> None:
    """A versioned event must retrieve the same object version."""
    body = RecordingBody()
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                version_id="different-version",
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="document version does not match the uploaded event",
    ):
        loader.load(
            reference=make_reference(),
        )

    assert body.read_amounts == []
    assert body.close_calls == 1


def test_reads_only_maximum_size_plus_one_byte() -> None:
    """The body read must always use a hard overflow sentinel."""
    body = RecordingBody(b"a" * 11)
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                content_length=10,
            )
        ),
        max_size_bytes=10,
    )

    with pytest.raises(
        DocumentValidationError,
        match="document exceeds the configured size limit",
    ):
        loader.load(
            reference=make_reference(
                expected_size_bytes=10,
            )
        )

    assert body.read_amounts == [
        11,
    ]
    assert body.close_calls == 1


def test_rejects_body_size_mismatch() -> None:
    """The complete body must match reported S3 metadata."""
    body = RecordingBody(CONTENT_BYTES[:-1])
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="document body size does not match S3 metadata",
    ):
        loader.load(
            reference=make_reference(),
        )

    assert body.close_calls == 1


def test_rejects_non_binary_body() -> None:
    """Streaming bodies must return bytes."""
    body = RecordingBody(CONTENT)
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="S3 returned a non-binary document body",
    ):
        loader.load(
            reference=make_reference(),
        )

    assert body.close_calls == 1


def test_rejects_invalid_utf8_body() -> None:
    """Document bodies must decode using strict UTF-8."""
    invalid_body = b"\xff\xfe"
    body = RecordingBody(invalid_body)
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
                content_length=len(invalid_body),
            )
        )
    )

    with pytest.raises(
        DocumentValidationError,
        match="document body must be valid UTF-8",
    ):
        loader.load(
            reference=make_reference(
                expected_size_bytes=len(invalid_body),
            )
        )

    assert body.close_calls == 1


def test_translates_stream_read_failure() -> None:
    """Body-read dependency failures should remain retryable."""
    read_error = EndpointConnectionError(endpoint_url="https://s3.example.com")
    body = RecordingBody(
        read_error=read_error,
    )
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
            )
        )
    )

    with pytest.raises(
        DocumentDependencyError,
        match="failed to read document body from S3",
    ) as captured_error:
        loader.load(
            reference=make_reference(),
        )

    assert captured_error.value.__cause__ is read_error
    assert body.close_calls == 1


def test_close_failure_does_not_replace_successful_load() -> None:
    """Cleanup errors must not discard a validated document."""
    body = RecordingBody(close_error=RuntimeError("close failed"))
    loader = make_loader(
        client=RecordingS3Client(
            response=make_response(
                body=body,
            )
        )
    )

    document = loader.load(
        reference=make_reference(),
    )

    assert document.content == CONTENT
    assert body.close_calls == 1
