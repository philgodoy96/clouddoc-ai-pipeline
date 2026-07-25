"""Tests for the deterministic mock AI provider."""

import pytest

from clouddoc.providers import (
    AIProviderRequest,
    MockAIProvider,
    MockAIProviderOutcome,
)
from clouddoc.providers.provider_errors import (
    AIProviderInvalidResponseError,
    AIProviderThrottledError,
    AIProviderTimeoutError,
    AIProviderUnavailableError,
)
from clouddoc.schemas.ai_output import DocumentType


def make_request(
    *,
    document_text: str = "Service contract between two companies.",
    correlation_id: str = "correlation-001",
    processing_attempt_id: str = "attempt-001",
) -> AIProviderRequest:
    """Create a valid request for mock-provider tests."""
    return AIProviderRequest(
        document_text=document_text,
        correlation_id=correlation_id,
        processing_attempt_id=processing_attempt_id,
    )


def test_success_result_is_deterministic() -> None:
    """The same request should always produce the same result."""
    provider = MockAIProvider()
    request = make_request()

    first_result = provider.extract(request)
    second_result = provider.extract(request)

    assert first_result == second_result


@pytest.mark.parametrize(
    ("document_text", "expected_type"),
    [
        (
            "Invoice number INV-001 is payable immediately.",
            DocumentType.INVOICE,
        ),
        (
            "Service contract between two companies.",
            DocumentType.CONTRACT,
        ),
        (
            "Annual agreement for support services.",
            DocumentType.CONTRACT,
        ),
        (
            "Quarterly operations report.",
            DocumentType.REPORT,
        ),
        (
            "Internal note regarding customer escalation.",
            DocumentType.INTERNAL_NOTE,
        ),
        (
            "Unclassified document content.",
            DocumentType.UNKNOWN,
        ),
    ],
)
def test_classifies_documents_with_stable_keyword_rules(
    document_text: str,
    expected_type: DocumentType,
) -> None:
    """Keyword classification should remain deterministic."""
    provider = MockAIProvider()

    result = provider.extract(make_request(document_text=document_text))

    assert result.document_type is expected_type


def test_keyword_classification_is_case_insensitive() -> None:
    """Classification must not depend on input casing."""
    provider = MockAIProvider()

    result = provider.extract(make_request(document_text="INVOICE NUMBER INV-001"))

    assert result.document_type is DocumentType.INVOICE


def test_success_result_preserves_request_trace_identifiers() -> None:
    """Mock output should prove which request reached the provider."""
    provider = MockAIProvider()

    result = provider.extract(
        make_request(
            correlation_id="correlation-999",
            processing_attempt_id="attempt-999",
        )
    )

    assert result.key_fields["correlation_id"] == "correlation-999"
    assert result.key_fields["processing_attempt_id"] == "attempt-999"


def test_success_result_contains_stable_document_statistics() -> None:
    """Mock output should expose deterministic text statistics."""
    provider = MockAIProvider()
    document_text = "One two three."

    result = provider.extract(make_request(document_text=document_text))

    assert result.key_fields["character_count"] == len(document_text)
    assert result.key_fields["word_count"] == 3
    assert result.confidence == 0.85
    assert result.requires_human_review is False


def test_success_normalizes_outer_document_whitespace() -> None:
    """Outer whitespace should not affect the normalized mock result."""
    provider = MockAIProvider()

    result = provider.extract(
        make_request(
            document_text="  Service contract text.  ",
        )
    )

    assert result.summary == "Service contract text."
    assert result.key_fields["character_count"] == len("Service contract text.")


def test_short_document_is_used_as_summary() -> None:
    """A short document should be returned as its complete summary."""
    provider = MockAIProvider()
    document_text = "Short internal note."

    result = provider.extract(make_request(document_text=document_text))

    assert result.summary == document_text


def test_long_summary_is_bounded_deterministically() -> None:
    """Long mock summaries should remain bounded and predictable."""
    provider = MockAIProvider()
    document_text = "word " * 100

    result = provider.extract(make_request(document_text=document_text))

    assert len(result.summary) <= 200
    assert result.summary.endswith("...")


@pytest.mark.parametrize(
    ("outcome", "expected_error", "expected_code"),
    [
        (
            MockAIProviderOutcome.TIMEOUT,
            AIProviderTimeoutError,
            "ai_provider_timeout",
        ),
        (
            MockAIProviderOutcome.THROTTLED,
            AIProviderThrottledError,
            "ai_provider_throttled",
        ),
        (
            MockAIProviderOutcome.UNAVAILABLE,
            AIProviderUnavailableError,
            "ai_provider_unavailable",
        ),
        (
            MockAIProviderOutcome.INVALID_RESPONSE,
            AIProviderInvalidResponseError,
            "ai_provider_invalid_response",
        ),
    ],
)
def test_configured_failure_outcome_raises_normalized_error(
    outcome: MockAIProviderOutcome,
    expected_error: type[Exception],
    expected_code: str,
) -> None:
    """Mock failures should expose stable normalized error metadata."""
    provider = MockAIProvider(outcome=outcome)

    with pytest.raises(expected_error) as error_info:
        provider.extract(make_request())

    error = error_info.value

    assert error.error_code == expected_code
    assert error.provider_name == "mock"


@pytest.mark.parametrize(
    ("document_text", "expected_message"),
    [
        ("", "document_text must not be empty"),
        ("   ", "document_text must not be empty"),
    ],
)
def test_request_rejects_empty_document(
    document_text: str,
    expected_message: str,
) -> None:
    """The application must not call providers with empty content."""
    from clouddoc.domain.errors import InvalidDomainValueError

    with pytest.raises(
        InvalidDomainValueError,
        match=expected_message,
    ):
        make_request(document_text=document_text)


@pytest.mark.parametrize(
    ("correlation_id", "processing_attempt_id", "expected_message"),
    [
        (
            "",
            "attempt-001",
            "correlation_id must not be empty",
        ),
        (
            "correlation-001",
            "",
            "processing_attempt_id must not be empty",
        ),
    ],
)
def test_request_rejects_empty_trace_identifiers(
    correlation_id: str,
    processing_attempt_id: str,
    expected_message: str,
) -> None:
    """Provider requests require stable workflow identifiers."""
    from clouddoc.domain.errors import InvalidDomainValueError

    with pytest.raises(
        InvalidDomainValueError,
        match=expected_message,
    ):
        make_request(
            correlation_id=correlation_id,
            processing_attempt_id=processing_attempt_id,
        )
