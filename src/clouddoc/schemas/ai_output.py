"""Validated structured output produced by AI providers."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_SUMMARY_LENGTH = 2_000
MAX_KEY_LENGTH = 100
MAX_OBJECT_ENTRIES = 50
MAX_LIST_ITEMS = 50
MAX_NESTING_DEPTH = 5
MAX_SERIALIZED_RESULT_BYTES = 32 * 1024


class DocumentType(StrEnum):
    """Supported document classifications."""

    CONTRACT = "contract"
    INVOICE = "invoice"
    REPORT = "report"
    INTERNAL_NOTE = "internal_note"
    UNKNOWN = "unknown"


Summary = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_SUMMARY_LENGTH,
    ),
]


class AIExtractionResult(BaseModel):
    """Application-owned contract for validated AI extraction output."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    document_type: DocumentType
    summary: Summary
    key_fields: dict[str, Any]
    confidence: float = Field(
        strict=True,
        ge=0.0,
        le=1.0,
    )
    requires_human_review: StrictBool

    @field_validator("key_fields", mode="before")
    @classmethod
    def validate_key_fields(
        cls,
        value: object,
    ) -> dict[str, Any]:
        """Require a bounded JSON-compatible object."""
        if not isinstance(value, dict):
            raise ValueError("key_fields must be an object")

        _validate_json_object(
            value,
            depth=1,
            field_path="key_fields",
        )

        return value

    @model_validator(mode="after")
    def validate_serialized_size(self) -> Self:
        """Reject valid-looking results that exceed the payload budget."""
        serialized_size = len(self.model_dump_json().encode("utf-8"))

        if serialized_size > MAX_SERIALIZED_RESULT_BYTES:
            raise ValueError(
                f"serialized AI result exceeds {MAX_SERIALIZED_RESULT_BYTES} bytes"
            )

        return self


def _validate_json_object(
    value: dict[object, object],
    *,
    depth: int,
    field_path: str,
) -> None:
    """Validate one JSON object and its nested values."""
    _validate_depth(depth, field_path=field_path)

    if len(value) > MAX_OBJECT_ENTRIES:
        raise ValueError(
            f"{field_path} must contain at most {MAX_OBJECT_ENTRIES} entries"
        )

    for key, nested_value in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{field_path} keys must be strings")

        if not key.strip():
            raise ValueError(f"{field_path} keys must not be empty")

        if len(key) > MAX_KEY_LENGTH:
            raise ValueError(
                f"{field_path} keys must contain at most {MAX_KEY_LENGTH} characters"
            )

        _validate_json_value(
            nested_value,
            depth=depth,
            field_path=f"{field_path}.{key}",
        )


def _validate_json_value(
    value: object,
    *,
    depth: int,
    field_path: str,
) -> None:
    """Validate one recursively nested JSON-compatible value."""
    if value is None or isinstance(value, (str, bool, int)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_path} must contain a finite number")
        return

    if isinstance(value, dict):
        _validate_json_object(
            value,
            depth=depth + 1,
            field_path=field_path,
        )
        return

    if isinstance(value, list):
        _validate_json_list(
            value,
            depth=depth + 1,
            field_path=field_path,
        )
        return

    raise ValueError(
        f"{field_path} contains an unsupported JSON value "
        f"of type {type(value).__name__}"
    )


def _validate_json_list(
    value: list[object],
    *,
    depth: int,
    field_path: str,
) -> None:
    """Validate one JSON array and its nested values."""
    _validate_depth(depth, field_path=field_path)

    if len(value) > MAX_LIST_ITEMS:
        raise ValueError(f"{field_path} must contain at most {MAX_LIST_ITEMS} items")

    for index, nested_value in enumerate(value):
        _validate_json_value(
            nested_value,
            depth=depth,
            field_path=f"{field_path}[{index}]",
        )


def _validate_depth(
    depth: int,
    *,
    field_path: str,
) -> None:
    """Protect the result from excessively nested collections."""
    if depth > MAX_NESTING_DEPTH:
        raise ValueError(
            f"{field_path} exceeds the maximum nesting depth of {MAX_NESTING_DEPTH}"
        )
