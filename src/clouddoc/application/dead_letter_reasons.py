"""Normalized reasons for dead-letter job reconciliation."""

from enum import StrEnum


class DeadLetterReason(StrEnum):
    """Describe one safe, stable dead-letter reconciliation reason."""

    PROCESSING_RETRIES_EXHAUSTED = "processing_retries_exhausted"
