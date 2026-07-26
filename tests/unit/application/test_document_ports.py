"""Tests for document text retrieval application contracts."""

from dataclasses import FrozenInstanceError

import pytest

from clouddoc.application import (
    DocumentDependencyError,
    DocumentLoadError,
    DocumentNotFoundError,
    DocumentObjectReference,
    DocumentTextLoader,
    DocumentValidationError,
    LoadedTextDocument,
)

OBJECT_KEY = "documents/job-001/source.txt"
ETAG = "0123456789abcdef"
VERSION_ID = "version-001"
CONTENT = "Olá, CloudDoc!"
CONTENT_SIZE_BYTES = len(CONTENT.encode("utf-8"))


class RecordingDocumentTextLoader:
    """Document loader double that records requested references."""

    def __init__(
        self,
        *,
        result: LoadedTextDocument,
    ) -> None:
        """Initialize the loader with one deterministic result."""
        self._result = result
        self.references: list[DocumentObjectReference] = []

    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Record the reference and return the configured document."""
        self.references.append(reference)
        return self._result


def make_reference() -> DocumentObjectReference:
    """Create one deterministic document reference."""
    return DocumentObjectReference(
        object_key=OBJECT_KEY,
        expected_size_bytes=CONTENT_SIZE_BYTES,
        expected_etag=ETAG,
        version_id=VERSION_ID,
    )


def make_loaded_document() -> LoadedTextDocument:
    """Create one deterministic loaded text document."""
    return LoadedTextDocument(
        object_key=OBJECT_KEY,
        content=CONTENT,
        content_type="text/plain",
        size_bytes=CONTENT_SIZE_BYTES,
        etag=ETAG,
        version_id=VERSION_ID,
    )


def test_document_reference_preserves_expected_identity() -> None:
    """The reference should retain trusted event metadata."""
    reference = make_reference()

    assert reference.object_key == OBJECT_KEY
    assert reference.expected_size_bytes == CONTENT_SIZE_BYTES
    assert reference.expected_etag == ETAG
    assert reference.version_id == VERSION_ID


def test_document_reference_is_immutable() -> None:
    """Document references must not change after validation."""
    reference = make_reference()

    with pytest.raises(FrozenInstanceError):
        reference.object_key = "documents/job-002/source.txt"


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("object_key", ""),
        ("object_key", "   "),
        ("expected_etag", ""),
        ("expected_etag", "   "),
    ],
)
def test_document_reference_rejects_blank_required_text(
    field_name: str,
    field_value: str,
) -> None:
    """Required document identity values must not be blank."""
    values = {
        "object_key": OBJECT_KEY,
        "expected_size_bytes": CONTENT_SIZE_BYTES,
        "expected_etag": ETAG,
        "version_id": VERSION_ID,
    }
    values[field_name] = field_value

    with pytest.raises(
        ValueError,
        match=f"{field_name} must not be blank",
    ):
        DocumentObjectReference(**values)


def test_document_reference_rejects_blank_version_id() -> None:
    """A present version identifier must contain meaningful text."""
    with pytest.raises(
        ValueError,
        match="version_id must not be blank",
    ):
        DocumentObjectReference(
            object_key=OBJECT_KEY,
            expected_size_bytes=CONTENT_SIZE_BYTES,
            expected_etag=ETAG,
            version_id="   ",
        )


def test_document_reference_allows_missing_version_id() -> None:
    """Unversioned bucket events may omit the object version."""
    reference = DocumentObjectReference(
        object_key=OBJECT_KEY,
        expected_size_bytes=CONTENT_SIZE_BYTES,
        expected_etag=ETAG,
        version_id=None,
    )

    assert reference.version_id is None


def test_document_reference_rejects_negative_expected_size() -> None:
    """S3 object sizes cannot be negative."""
    with pytest.raises(
        ValueError,
        match=("expected_size_bytes must be greater than or equal to zero"),
    ):
        DocumentObjectReference(
            object_key=OBJECT_KEY,
            expected_size_bytes=-1,
            expected_etag=ETAG,
        )


def test_loaded_document_preserves_validated_content() -> None:
    """The loaded value should expose validated text and metadata."""
    document = make_loaded_document()

    assert document.object_key == OBJECT_KEY
    assert document.content == CONTENT
    assert document.content_type == "text/plain"
    assert document.size_bytes == CONTENT_SIZE_BYTES
    assert document.etag == ETAG
    assert document.version_id == VERSION_ID


def test_loaded_document_is_immutable() -> None:
    """Validated document content must not change after loading."""
    document = make_loaded_document()

    with pytest.raises(FrozenInstanceError):
        document.content = "modified"


@pytest.mark.parametrize(
    "content_type",
    [
        "",
        "application/json",
        "text/html",
        "text/plain; charset=utf-8",
    ],
)
def test_loaded_document_requires_canonical_plain_text_type(
    content_type: str,
) -> None:
    """Loaded documents expose one canonical supported media type."""
    with pytest.raises(
        ValueError,
        match="content_type must be text/plain",
    ):
        LoadedTextDocument(
            object_key=OBJECT_KEY,
            content=CONTENT,
            content_type=content_type,
            size_bytes=CONTENT_SIZE_BYTES,
            etag=ETAG,
        )


def test_loaded_document_rejects_negative_size() -> None:
    """Loaded object sizes cannot be negative."""
    with pytest.raises(
        ValueError,
        match=("size_bytes must be greater than or equal to zero"),
    ):
        LoadedTextDocument(
            object_key=OBJECT_KEY,
            content=CONTENT,
            content_type="text/plain",
            size_bytes=-1,
            etag=ETAG,
        )


def test_loaded_document_requires_matching_utf8_byte_size() -> None:
    """The reported size must match the complete UTF-8 body."""
    with pytest.raises(
        ValueError,
        match=("size_bytes must match the UTF-8 encoded content length"),
    ):
        LoadedTextDocument(
            object_key=OBJECT_KEY,
            content=CONTENT,
            content_type="text/plain",
            size_bytes=len(CONTENT),
            etag=ETAG,
        )


def test_loaded_document_rejects_invalid_unicode_content() -> None:
    """The value object must reject text that cannot encode as UTF-8."""
    invalid_content = "\ud800"

    with pytest.raises(
        ValueError,
        match="content must be valid UTF-8 text",
    ):
        LoadedTextDocument(
            object_key=OBJECT_KEY,
            content=invalid_content,
            content_type="text/plain",
            size_bytes=1,
            etag=ETAG,
        )


def test_loader_double_satisfies_application_contract() -> None:
    """A structural implementation should satisfy the loader port."""
    result = make_loaded_document()
    loader = RecordingDocumentTextLoader(
        result=result,
    )
    reference = make_reference()

    assert isinstance(
        loader,
        DocumentTextLoader,
    )

    loaded_document = loader.load(
        reference=reference,
    )

    assert loaded_document is result
    assert loader.references == [
        reference,
    ]


@pytest.mark.parametrize(
    "error_type",
    [
        DocumentNotFoundError,
        DocumentValidationError,
        DocumentDependencyError,
    ],
)
def test_specialized_errors_share_document_load_base(
    error_type: type[DocumentLoadError],
) -> None:
    """All loader failures should share one application boundary."""
    error = error_type("document loading failed")

    assert isinstance(
        error,
        DocumentLoadError,
    )
