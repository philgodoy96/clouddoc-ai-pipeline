"""Normalized AI provider exceptions."""


class AIProviderError(Exception):
    """Base exception raised by AI provider implementations."""

    error_code = "ai_provider_error"

    def __init__(
        self,
        message: str,
        *,
        provider_name: str | None = None,
    ) -> None:
        """Initialize a normalized provider error."""
        super().__init__(message)
        self.provider_name = provider_name


class AIProviderTimeoutError(AIProviderError):
    """Raised when an AI provider request exceeds its time budget."""

    error_code = "ai_provider_timeout"


class AIProviderThrottledError(AIProviderError):
    """Raised when an AI provider rejects a request due to throttling."""

    error_code = "ai_provider_throttled"


class AIProviderUnavailableError(AIProviderError):
    """Raised when an AI provider is temporarily unavailable."""

    error_code = "ai_provider_unavailable"


class AIProviderInvalidResponseError(AIProviderError):
    """Raised when a provider returns an unusable response."""

    error_code = "ai_provider_invalid_response"


class AIProviderConfigurationError(AIProviderError):
    """Raised when static provider configuration prevents invocation."""

    error_code = "ai_provider_configuration_error"
