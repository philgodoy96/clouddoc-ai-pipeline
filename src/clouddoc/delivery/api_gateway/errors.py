"""Transport-facing API Gateway error models."""

from dataclasses import dataclass

from clouddoc.delivery.api_gateway.request_context import (
    APIRequestContext,
)


@dataclass(frozen=True, slots=True)
class APIError:
    """Safe error representation returned to API clients."""

    code: str
    message: str
    request_id: str
    correlation_id: str

    @classmethod
    def from_request_context(
        cls,
        *,
        code: str,
        message: str,
        request_context: APIRequestContext,
    ) -> "APIError":
        """Create an API error associated with one request."""
        normalized_code = code.strip()
        normalized_message = message.strip()

        if not normalized_code:
            raise ValueError("error code must not be empty")

        if not normalized_message:
            raise ValueError("error message must not be empty")

        return cls(
            code=normalized_code,
            message=normalized_message,
            request_id=request_context.request_id,
            correlation_id=request_context.correlation_id,
        )

    def to_payload(self) -> dict[str, object]:
        """Return the stable external error payload."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": self.request_id,
                "correlation_id": self.correlation_id,
            }
        }
