"""Tests for normalized document-processing failure reasons."""

import pytest

from clouddoc.application import ProcessingFailureReason


@pytest.mark.parametrize(
    ("reason", "expected_value"),
    [
        (
            ProcessingFailureReason.DOCUMENT_NOT_FOUND,
            "document_not_found",
        ),
        (
            ProcessingFailureReason.DOCUMENT_VALIDATION_FAILED,
            "document_validation_failed",
        ),
        (
            ProcessingFailureReason.INVALID_DOCUMENT_REFERENCE,
            "invalid_document_reference",
        ),
        (
            ProcessingFailureReason.INVALID_PROVIDER_REQUEST,
            "invalid_provider_request",
        ),
        (
            ProcessingFailureReason.AI_PROVIDER_INVALID_RESPONSE,
            "ai_provider_invalid_response",
        ),
    ],
)
def test_failure_reason_values_are_stable(
    reason: ProcessingFailureReason,
    expected_value: str,
) -> None:
    """Failure reasons should remain stable persistence values."""
    assert reason.value == expected_value
    assert str(reason) == expected_value


def test_failure_reason_values_are_unique() -> None:
    """Each terminal condition must have one distinct reason."""
    values = {reason.value for reason in ProcessingFailureReason}

    assert len(values) == len(ProcessingFailureReason)


def test_failure_reasons_are_string_compatible() -> None:
    """Repository operations may receive enum values as strings."""
    reason = ProcessingFailureReason.DOCUMENT_NOT_FOUND

    assert isinstance(reason, str)
