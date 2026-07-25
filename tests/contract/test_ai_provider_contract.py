"""Contract tests for application-compatible AI providers."""

from collections.abc import Callable

import pytest

from clouddoc.providers import (
    AIProvider,
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
from clouddoc.schemas.ai_output import AIExtractionResult

ProviderFactory = Callable[[], AIProvider]


@pytest.fixture
def provider_factories() -> list[ProviderFactory]:
    """Return provider implementations that must satisfy the contract."""
    return [
        MockAIProvider,
    ]


@pytest.fixture
def valid_request() -> AIProviderRequest:
    """Create a normalized provider request."""
    return AIProviderRequest(
        document_text="Service contract between two companies.",
        correlation_id="correlation-001",
        processing_attempt_id="attempt-001",
    )


def test_provider_implementations_satisfy_runtime_protocol(
    provider_factories: list[ProviderFactory],
) -> None:
    """Every registered provider must expose the public contract."""
    for factory in provider_factories:
        provider = factory()

        assert isinstance(provider, AIProvider)
        assert provider.provider_name


def test_provider_implementations_return_validated_result(
    provider_factories: list[ProviderFactory],
    valid_request: AIProviderRequest,
) -> None:
    """Successful providers must return the application-owned schema."""
    for factory in provider_factories:
        provider = factory()

        result = provider.extract(valid_request)

        assert isinstance(result, AIExtractionResult)


@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [
        (
            MockAIProviderOutcome.TIMEOUT,
            AIProviderTimeoutError,
        ),
        (
            MockAIProviderOutcome.THROTTLED,
            AIProviderThrottledError,
        ),
        (
            MockAIProviderOutcome.UNAVAILABLE,
            AIProviderUnavailableError,
        ),
        (
            MockAIProviderOutcome.INVALID_RESPONSE,
            AIProviderInvalidResponseError,
        ),
    ],
)
def test_provider_failures_use_normalized_error_types(
    outcome: MockAIProviderOutcome,
    expected_error: type[Exception],
    valid_request: AIProviderRequest,
) -> None:
    """Provider failures must not expose implementation-specific errors."""
    provider = MockAIProvider(outcome=outcome)

    with pytest.raises(expected_error):
        provider.extract(valid_request)
