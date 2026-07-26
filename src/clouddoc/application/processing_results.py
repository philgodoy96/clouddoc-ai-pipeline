"""Application results for processing-start continuation decisions."""

from dataclasses import dataclass
from enum import StrEnum

from clouddoc.domain import ProcessingAttempt


class ProcessingStartOutcome(StrEnum):
    """Describe whether the current worker may continue processing."""

    CLAIM_ACQUIRED = "claim_acquired"
    PROCESSING_ALREADY_ACTIVE = "processing_already_active"
    EFFECT_ALREADY_APPLIED = "effect_already_applied"


@dataclass(frozen=True, slots=True)
class ProcessingStartResult:
    """Represent the outcome of one processing-start request."""

    outcome: ProcessingStartOutcome
    attempt: ProcessingAttempt | None
    correlation_id: str | None

    def __post_init__(self) -> None:
        """Validate continuation authorization invariants."""
        if self.outcome is ProcessingStartOutcome.CLAIM_ACQUIRED:
            if self.attempt is None:
                raise ValueError("claim_acquired outcome requires an attempt")

            if self.correlation_id is None or not self.correlation_id.strip():
                raise ValueError("claim_acquired outcome requires a correlation_id")

        if self.outcome is ProcessingStartOutcome.PROCESSING_ALREADY_ACTIVE:
            if self.attempt is not None:
                raise ValueError(
                    "processing_already_active outcome must not include an attempt"
                )

            if self.correlation_id is not None:
                raise ValueError(
                    "processing_already_active outcome must not include a "
                    "correlation_id"
                )

        if self.outcome is ProcessingStartOutcome.EFFECT_ALREADY_APPLIED:
            if self.attempt is not None:
                raise ValueError(
                    "effect_already_applied outcome must not include an attempt"
                )

            if self.correlation_id is not None:
                raise ValueError(
                    "effect_already_applied outcome must not include a correlation_id"
                )

    @classmethod
    def claim_acquired(
        cls,
        *,
        attempt: ProcessingAttempt,
        correlation_id: str,
    ) -> "ProcessingStartResult":
        """Create a result authorizing this worker to continue."""
        return cls(
            outcome=ProcessingStartOutcome.CLAIM_ACQUIRED,
            attempt=attempt,
            correlation_id=correlation_id,
        )

    @classmethod
    def processing_already_active(
        cls,
    ) -> "ProcessingStartResult":
        """Create a result indicating another attempt currently owns processing."""
        return cls(
            outcome=ProcessingStartOutcome.PROCESSING_ALREADY_ACTIVE,
            attempt=None,
            correlation_id=None,
        )

    @classmethod
    def effect_already_applied(
        cls,
    ) -> "ProcessingStartResult":
        """Create a result indicating no further work is required."""
        return cls(
            outcome=ProcessingStartOutcome.EFFECT_ALREADY_APPLIED,
            attempt=None,
            correlation_id=None,
        )
