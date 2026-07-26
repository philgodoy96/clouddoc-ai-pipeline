"""Application-layer contract for bounded document text retrieval."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class DocumentLoadError(Exception):
    """Base error raised while loading document content."""


class DocumentNotFoundError(DocumentLoadError):
    """Raised when the referenced document object does not exist."""


class DocumentValidationError(DocumentLoadError):
    """Raised when document content or metadata is invalid."""


class DocumentDependencyError(DocumentLoadError):
    """Raised when the document storage dependency is unavailable."""


def _require_non_blank(
    value: str,
    *,
    field_name: str,
) -> None:
    """Require a non-blank text value."""
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_optional_non_blank(
    value: str | None,
    *,
    field_name: str,
) -> None:
    """Require a non-blank optional text value when present."""
    if value is not None:
        _require_non_blank(
            value,
            field_name=field_name,
        )


@dataclass(frozen=True, slots=True)
class DocumentObjectReference:
    """Describe the expected identity of one uploaded document object."""

    object_key: str
    expected_size_bytes: int
    expected_etag: str
    version_id: str | None = None

    def __post_init__(self) -> None:
        """Validate the trusted document reference."""
        _require_non_blank(
            self.object_key,
            field_name="object_key",
        )
        _require_non_blank(
            self.expected_etag,
            field_name="expected_etag",
        )
        _require_optional_non_blank(
            self.version_id,
            field_name="version_id",
        )

        if self.expected_size_bytes < 0:
            raise ValueError(
                "expected_size_bytes must be greater than or equal to zero"
            )


@dataclass(frozen=True, slots=True)
class LoadedTextDocument:
    """Represent one validated UTF-8 plain-text document."""

    object_key: str
    content: str
    content_type: str
    size_bytes: int
    etag: str
    version_id: str | None = None

    def __post_init__(self) -> None:
        """Validate loaded document metadata and text consistency."""
        _require_non_blank(
            self.object_key,
            field_name="object_key",
        )
        _require_non_blank(
            self.etag,
            field_name="etag",
        )
        _require_optional_non_blank(
            self.version_id,
            field_name="version_id",
        )

        if self.content_type != "text/plain":
            raise ValueError("content_type must be text/plain")

        if self.size_bytes < 0:
            raise ValueError("size_bytes must be greater than or equal to zero")

        try:
            encoded_content = self.content.encode(
                "utf-8",
                errors="strict",
            )
        except UnicodeEncodeError as error:
            raise ValueError("content must be valid UTF-8 text") from error

        if len(encoded_content) != self.size_bytes:
            raise ValueError("size_bytes must match the UTF-8 encoded content length")


@runtime_checkable
class DocumentTextLoader(Protocol):
    """Load one validated UTF-8 plain-text document."""

    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument:
        """Load document text from the trusted storage boundary."""
        ...
