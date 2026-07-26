"""Application results for dead-letter job reconciliation."""

from dataclasses import dataclass
from enum import StrEnum


class DeadLetterReconciliationOutcome(StrEnum):
    """Describe the authoritative result of one DLQ reconciliation."""

    DEAD_RECORDED = "dead_recorded"
    EFFECT_ALREADY_APPLIED = "effect_already_applied"


@dataclass(frozen=True, slots=True)
class DeadLetterReconciliationResult:
    """Represent one explicit dead-letter reconciliation decision."""

    outcome: DeadLetterReconciliationOutcome
    job_id: str

    def __post_init__(self) -> None:
        """Validate reconciliation-result invariants."""
        if not self.job_id.strip():
            raise ValueError("job_id must not be blank")

        if not isinstance(
            self.outcome,
            DeadLetterReconciliationOutcome,
        ):
            raise ValueError("unsupported dead-letter reconciliation outcome")

    @classmethod
    def dead_recorded(
        cls,
        *,
        job_id: str,
    ) -> "DeadLetterReconciliationResult":
        """Create a result for one durably recorded dead job."""
        return cls(
            outcome=DeadLetterReconciliationOutcome.DEAD_RECORDED,
            job_id=job_id,
        )

    @classmethod
    def effect_already_applied(
        cls,
        *,
        job_id: str,
    ) -> "DeadLetterReconciliationResult":
        """Create a result requiring no additional lifecycle effect."""
        return cls(
            outcome=(DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED),
            job_id=job_id,
        )
