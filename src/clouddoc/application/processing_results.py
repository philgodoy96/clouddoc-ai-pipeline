"""Application results for processing-start continuation decisions."""

from dataclasses import dataclass
from enum import StrEnum

from clouddoc.domain import ProcessingAttempt


class ProcessingStartOutcome(StrEnum):
    """Describe whether the current worker may continue processing."""

    CLAIM_ACQUIRED = "claim_acquired"
    EFFECT_ALREADY_APPLIED = "effect_already_applied"


@dataclass(frozen=True, slots=True)
class ProcessingStartResult:
    """Represent the outcome of one processing-start request."""

    outcome: ProcessingStartOutcome
    attempt: ProcessingAttempt | None

    def __post_init__(self) -> None:
        """Validate continuation authorization invariants."""
        if (
            self.outcome is ProcessingStartOutcome.CLAIM_ACQUIRED
            and self.attempt is None
        ):
            raise ValueError("claim_acquired outcome requires an attempt")

        if (
            self.outcome is ProcessingStartOutcome.EFFECT_ALREADY_APPLIED
            and self.attempt is not None
        ):
            raise ValueError(
                "effect_already_applied outcome must not include an attempt"
            )

    @classmethod
    def claim_acquired(
        cls,
        *,
        attempt: ProcessingAttempt,
    ) -> "ProcessingStartResult":
        """Create a result authorizing this worker to continue."""
        return cls(
            outcome=ProcessingStartOutcome.CLAIM_ACQUIRED,
            attempt=attempt,
        )

    @classmethod
    def effect_already_applied(
        cls,
    ) -> "ProcessingStartResult":
        """Create a result indicating no further work is required."""
        return cls(
            outcome=ProcessingStartOutcome.EFFECT_ALREADY_APPLIED,
            attempt=None,
        )
