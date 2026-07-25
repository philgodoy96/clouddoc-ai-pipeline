"""Deterministic AI provider used for tests and local development."""

from enum import StrEnum

from clouddoc.providers.ai_provider import (
    AIProviderRequest,
)
from clouddoc.providers.provider_errors import (
    AIProviderInvalidResponseError,
    AIProviderThrottledError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from clouddoc.schemas.ai_output import (
    AIExtractionResult,
    DocumentType,
)


class MockAIProviderOutcome(StrEnum):
    """Supported deterministic behaviors for the mock provider."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    THROTTLED = "throttled"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"


class MockAIProvider:
    """Deterministic provider for local development and automated tests."""

    provider_name = "mock"

    def __init__(
        self,
        *,
        outcome: MockAIProviderOutcome = MockAIProviderOutcome.SUCCESS,
    ) -> None:
        """Configure the deterministic provider outcome."""
        self._outcome = outcome

    def extract(
        self,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Return a deterministic result or raise a configured error."""
        if self._outcome is MockAIProviderOutcome.TIMEOUT:
            raise AIProviderTimeoutError(
                "mock provider request timed out",
                provider_name=self.provider_name,
            )

        if self._outcome is MockAIProviderOutcome.THROTTLED:
            raise AIProviderThrottledError(
                "mock provider request was throttled",
                provider_name=self.provider_name,
            )

        if self._outcome is MockAIProviderOutcome.UNAVAILABLE:
            raise AIProviderUnavailableError(
                "mock provider is unavailable",
                provider_name=self.provider_name,
            )

        if self._outcome is MockAIProviderOutcome.INVALID_RESPONSE:
            raise AIProviderInvalidResponseError(
                "mock provider returned an invalid response",
                provider_name=self.provider_name,
            )

        return _build_success_result(request)


def _build_success_result(
    request: AIProviderRequest,
) -> AIExtractionResult:
    """Build a stable result from the normalized request."""
    normalized_text = request.document_text.strip()
    summary = _build_summary(normalized_text)

    return AIExtractionResult(
        document_type=_classify_document(normalized_text),
        summary=summary,
        key_fields={
            "character_count": len(normalized_text),
            "word_count": len(normalized_text.split()),
            "correlation_id": request.correlation_id,
            "processing_attempt_id": request.processing_attempt_id,
        },
        confidence=0.85,
        requires_human_review=False,
    )


def _classify_document(document_text: str) -> DocumentType:
    """Classify documents using deterministic keyword rules."""
    normalized_text = document_text.casefold()

    if "invoice" in normalized_text:
        return DocumentType.INVOICE

    if "contract" in normalized_text or "agreement" in normalized_text:
        return DocumentType.CONTRACT

    if "report" in normalized_text:
        return DocumentType.REPORT

    if "internal note" in normalized_text:
        return DocumentType.INTERNAL_NOTE

    return DocumentType.UNKNOWN


def _build_summary(document_text: str) -> str:
    """Create a bounded deterministic summary."""
    maximum_summary_characters = 200

    if len(document_text) <= maximum_summary_characters:
        return document_text

    return f"{document_text[: maximum_summary_characters - 3].rstrip()}..."
