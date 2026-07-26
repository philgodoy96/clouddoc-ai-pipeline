"""Application results for claim-aware document processing."""

from dataclasses import dataclass
from enum import StrEnum

from clouddoc.domain import ProcessingAttempt
from clouddoc.schemas import AIExtractionResult


class DocumentProcessingOutcome(StrEnum):
    """Describe the result of one uploaded-document workflow."""

    PROCESSED = "processed"
    EFFECT_ALREADY_APPLIED = "effect_already_applied"


@dataclass(frozen=True, slots=True)
class DocumentProcessingResult:
    """Represent an explicit document-processing workflow outcome."""

    outcome: DocumentProcessingOutcome
    attempt: ProcessingAttempt | None
    extraction_result: AIExtractionResult | None

    def __post_init__(self) -> None:
        """Validate workflow-result invariants."""
        if self.outcome is DocumentProcessingOutcome.PROCESSED:
            if self.attempt is None:
                raise ValueError("processed outcome requires an attempt")

            if self.extraction_result is None:
                raise ValueError("processed outcome requires an extraction result")

            return

        if self.attempt is not None:
            raise ValueError(
                "effect_already_applied outcome must not include an attempt"
            )

        if self.extraction_result is not None:
            raise ValueError(
                "effect_already_applied outcome must not include an extraction result"
            )

    @classmethod
    def processed(
        cls,
        *,
        attempt: ProcessingAttempt,
        extraction_result: AIExtractionResult,
    ) -> "DocumentProcessingResult":
        """Create a result containing one owned validated extraction."""
        return cls(
            outcome=DocumentProcessingOutcome.PROCESSED,
            attempt=attempt,
            extraction_result=extraction_result,
        )

    @classmethod
    def effect_already_applied(
        cls,
    ) -> "DocumentProcessingResult":
        """Create a result requiring no further workflow effects."""
        return cls(
            outcome=(DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED),
            attempt=None,
            extraction_result=None,
        )
