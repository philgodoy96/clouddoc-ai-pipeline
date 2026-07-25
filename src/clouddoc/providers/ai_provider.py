"""Application-facing AI provider contract."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from clouddoc.domain.errors import InvalidDomainValueError
from clouddoc.schemas.ai_output import AIExtractionResult


@dataclass(frozen=True, slots=True)
class AIProviderRequest:
    """Normalized input passed to an AI provider."""

    document_text: str
    correlation_id: str
    processing_attempt_id: str

    def __post_init__(self) -> None:
        """Validate provider request invariants."""
        if not self.document_text.strip():
            raise InvalidDomainValueError("document_text must not be empty")

        if not self.correlation_id.strip():
            raise InvalidDomainValueError("correlation_id must not be empty")

        if not self.processing_attempt_id.strip():
            raise InvalidDomainValueError("processing_attempt_id must not be empty")


@runtime_checkable
class AIProvider(Protocol):
    """Contract implemented by application-compatible AI providers."""

    @property
    def provider_name(self) -> str:
        """Return a stable provider identifier."""
        ...

    def extract(
        self,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Classify and extract structured data from one document."""
        ...
