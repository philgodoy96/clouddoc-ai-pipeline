"""Tests for normalized dead-letter reconciliation reasons."""

from clouddoc.application import DeadLetterReason


def test_processing_retries_exhausted_value_is_stable() -> None:
    """The persisted queue-exhaustion reason must remain stable."""
    reason = DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED

    assert reason.value == "processing_retries_exhausted"
    assert str(reason) == "processing_retries_exhausted"


def test_dead_letter_reason_is_string_compatible() -> None:
    """Repository operations may receive enum values as strings."""
    reason = DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED

    assert isinstance(reason, str)


def test_dead_letter_reason_values_are_unique() -> None:
    """Each reconciliation reason must have one distinct value."""
    values = {reason.value for reason in DeadLetterReason}

    assert len(values) == len(DeadLetterReason)
