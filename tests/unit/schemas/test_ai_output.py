"""Tests for structured AI extraction output validation."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from clouddoc.schemas.ai_output import (
    MAX_KEY_LENGTH,
    MAX_LIST_ITEMS,
    MAX_NESTING_DEPTH,
    MAX_OBJECT_ENTRIES,
    MAX_SERIALIZED_RESULT_BYTES,
    MAX_SUMMARY_LENGTH,
    AIExtractionResult,
    DocumentType,
)


def make_result(
    **overrides: object,
) -> AIExtractionResult:
    """Create a valid AI extraction result with optional overrides."""
    values: dict[str, object] = {
        "document_type": DocumentType.CONTRACT,
        "summary": "A service agreement between two companies.",
        "key_fields": {
            "effective_date": "2026-07-25",
            "renewal_type": "annual",
        },
        "confidence": 0.92,
        "requires_human_review": False,
    }
    values.update(overrides)

    return AIExtractionResult.model_validate(values)


@pytest.mark.parametrize(
    "document_type",
    [
        DocumentType.CONTRACT,
        DocumentType.INVOICE,
        DocumentType.REPORT,
        DocumentType.INTERNAL_NOTE,
        DocumentType.UNKNOWN,
    ],
)
def test_accepts_supported_document_types(
    document_type: DocumentType,
) -> None:
    """Every approved document type should be accepted."""
    result = make_result(document_type=document_type)

    assert result.document_type is document_type


def test_normalizes_summary_whitespace() -> None:
    """Leading and trailing summary whitespace should be removed."""
    result = make_result(summary="  A valid summary.  ")

    assert result.summary == "A valid summary."


@pytest.mark.parametrize(
    "summary",
    [
        "",
        "   ",
    ],
)
def test_rejects_empty_summary(summary: str) -> None:
    """The result must contain a meaningful summary."""
    with pytest.raises(ValidationError):
        make_result(summary=summary)


def test_rejects_oversized_summary() -> None:
    """The summary must remain within the application limit."""
    with pytest.raises(ValidationError):
        make_result(summary="a" * (MAX_SUMMARY_LENGTH + 1))


def test_rejects_non_string_summary() -> None:
    """The summary field must not coerce non-string values."""
    with pytest.raises(ValidationError):
        make_result(summary=123)


def test_rejects_unsupported_document_type() -> None:
    """Arbitrary provider classifications must not be accepted."""
    with pytest.raises(ValidationError):
        make_result(document_type="legal_document")


@pytest.mark.parametrize(
    "confidence",
    [
        -0.01,
        1.01,
    ],
)
def test_rejects_confidence_outside_supported_range(
    confidence: float,
) -> None:
    """Confidence must remain between zero and one."""
    with pytest.raises(ValidationError):
        make_result(confidence=confidence)


def test_accepts_confidence_boundaries() -> None:
    """Both confidence boundaries should be valid."""
    assert make_result(confidence=0.0).confidence == 0.0
    assert make_result(confidence=1.0).confidence == 1.0


def test_rejects_string_confidence() -> None:
    """Confidence must not be coerced from a provider string."""
    with pytest.raises(ValidationError):
        make_result(confidence="0.92")


@pytest.mark.parametrize(
    "requires_human_review",
    [
        "false",
        "true",
        0,
        1,
    ],
)
def test_rejects_coerced_human_review_values(
    requires_human_review: object,
) -> None:
    """The human-review decision must be a strict boolean."""
    with pytest.raises(ValidationError):
        make_result(
            requires_human_review=requires_human_review,
        )


def test_rejects_non_object_key_fields() -> None:
    """Extracted key fields must be represented as an object."""
    with pytest.raises(
        ValidationError,
        match="key_fields must be an object",
    ):
        make_result(key_fields=["effective_date"])


@pytest.mark.parametrize(
    "invalid_key",
    [
        "",
        "   ",
    ],
)
def test_rejects_empty_key_field_name(
    invalid_key: str,
) -> None:
    """Extracted field names must not be empty."""
    with pytest.raises(
        ValidationError,
        match="keys must not be empty",
    ):
        make_result(key_fields={invalid_key: "value"})


def test_rejects_oversized_key_field_name() -> None:
    """Extracted field names must remain bounded."""
    oversized_key = "k" * (MAX_KEY_LENGTH + 1)

    with pytest.raises(
        ValidationError,
        match="keys must contain at most",
    ):
        make_result(key_fields={oversized_key: "value"})


def test_accepts_json_compatible_key_field_values() -> None:
    """The schema should accept supported JSON-compatible values."""
    key_fields = {
        "text": "value",
        "integer": 10,
        "number": 10.5,
        "boolean": True,
        "empty": None,
        "items": ["a", 2, False, None],
        "nested": {
            "customer": {
                "name": "Example Company",
            }
        },
    }

    result = make_result(key_fields=key_fields)

    assert result.key_fields == key_fields


@pytest.mark.parametrize(
    "unsupported_value",
    [
        datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
        Decimal("10.50"),
        b"bytes",
        {"set-value"},
        ("tuple",),
    ],
)
def test_rejects_unsupported_python_values(
    unsupported_value: object,
) -> None:
    """Only JSON-compatible values should cross the AI boundary."""
    with pytest.raises(
        ValidationError,
        match="unsupported JSON value",
    ):
        make_result(key_fields={"invalid": unsupported_value})


@pytest.mark.parametrize(
    "non_finite_value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_rejects_non_finite_numbers(
    non_finite_value: float,
) -> None:
    """JSON output must not contain non-finite floating-point values."""
    with pytest.raises(
        ValidationError,
        match="must contain a finite number",
    ):
        make_result(key_fields={"number": non_finite_value})


def test_accepts_maximum_object_entries() -> None:
    """An object at the configured entry limit should be accepted."""
    key_fields = {f"field_{index}": index for index in range(MAX_OBJECT_ENTRIES)}

    result = make_result(key_fields=key_fields)

    assert len(result.key_fields) == MAX_OBJECT_ENTRIES


def test_rejects_excessive_object_entries() -> None:
    """An object above the configured entry limit should fail."""
    key_fields = {f"field_{index}": index for index in range(MAX_OBJECT_ENTRIES + 1)}

    with pytest.raises(
        ValidationError,
        match="must contain at most",
    ):
        make_result(key_fields=key_fields)


def test_accepts_maximum_list_items() -> None:
    """A list at the configured item limit should be accepted."""
    items = list(range(MAX_LIST_ITEMS))

    result = make_result(key_fields={"items": items})

    assert result.key_fields["items"] == items


def test_rejects_excessive_list_items() -> None:
    """A list above the configured item limit should fail."""
    items = list(range(MAX_LIST_ITEMS + 1))

    with pytest.raises(
        ValidationError,
        match="must contain at most",
    ):
        make_result(key_fields={"items": items})


def build_nested_object(collection_depth: int) -> dict[str, object]:
    """Build a nested object with a precise collection depth."""
    value: object = "leaf"

    for depth in range(collection_depth - 1):
        value = {f"level_{depth}": value}

    return {"root": value}


def test_accepts_maximum_nesting_depth() -> None:
    """Collections at the configured nesting depth should be accepted."""
    key_fields = build_nested_object(MAX_NESTING_DEPTH)

    result = make_result(key_fields=key_fields)

    assert result.key_fields == key_fields


def test_rejects_excessive_nesting_depth() -> None:
    """Collections deeper than the configured limit should fail."""
    key_fields = build_nested_object(MAX_NESTING_DEPTH + 1)

    with pytest.raises(
        ValidationError,
        match="exceeds the maximum nesting depth",
    ):
        make_result(key_fields=key_fields)


def test_rejects_extra_top_level_fields() -> None:
    """Unexpected provider fields must not be silently retained."""
    values = {
        "document_type": DocumentType.CONTRACT,
        "summary": "A valid summary.",
        "key_fields": {},
        "confidence": 0.9,
        "requires_human_review": False,
        "unexpected": "value",
    }

    with pytest.raises(ValidationError):
        AIExtractionResult.model_validate(values)


def test_result_is_immutable() -> None:
    """Validated provider output should not change after acceptance."""
    result = make_result()

    with pytest.raises(ValidationError):
        result.confidence = 0.1


def test_serializes_to_stable_json_compatible_shape() -> None:
    """Validated output should serialize without provider-specific types."""
    result = make_result(
        document_type=DocumentType.INVOICE,
        key_fields={"invoice_number": "INV-001"},
    )

    assert result.model_dump(mode="json") == {
        "document_type": "invoice",
        "summary": "A service agreement between two companies.",
        "key_fields": {
            "invoice_number": "INV-001",
        },
        "confidence": 0.92,
        "requires_human_review": False,
    }


def test_rejects_result_above_serialized_size_limit() -> None:
    """The complete result must fit within the application payload budget."""
    large_value = "x" * MAX_SERIALIZED_RESULT_BYTES

    with pytest.raises(
        ValidationError,
        match="serialized AI result exceeds",
    ):
        make_result(key_fields={"large_value": large_value})
