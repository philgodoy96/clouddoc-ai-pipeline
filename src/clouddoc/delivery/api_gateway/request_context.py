"""Request identity resolution for API Gateway events."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

REQUEST_ID_HEADER = "x-request-id"
CORRELATION_ID_HEADER = "x-correlation-id"

RequestIdGenerator = Callable[[], str]


@dataclass(frozen=True, slots=True)
class APIRequestContext:
    """Resolved request identity for one delivery invocation."""

    request_id: str
    correlation_id: str


def resolve_request_context(
    event: Mapping[str, Any],
    *,
    request_id_generator: RequestIdGenerator | None = None,
) -> APIRequestContext:
    """Resolve request and correlation identifiers from an API event."""
    normalized_headers = _normalize_headers(event.get("headers"))

    request_id = (
        normalized_headers.get(REQUEST_ID_HEADER)
        or _resolve_api_gateway_request_id(event)
        or _generate_request_id(request_id_generator)
    )
    correlation_id = normalized_headers.get(CORRELATION_ID_HEADER) or request_id

    return APIRequestContext(
        request_id=request_id,
        correlation_id=correlation_id,
    )


def _normalize_headers(
    raw_headers: object,
) -> dict[str, str]:
    """Normalize non-empty string headers case-insensitively."""
    if not isinstance(raw_headers, Mapping):
        return {}

    normalized_headers: dict[str, str] = {}

    for raw_name, raw_value in raw_headers.items():
        if not isinstance(raw_name, str):
            continue

        if not isinstance(raw_value, str):
            continue

        name = raw_name.strip().lower()
        value = raw_value.strip()

        if not name or not value:
            continue

        normalized_headers[name] = value

    return normalized_headers


def _resolve_api_gateway_request_id(
    event: Mapping[str, Any],
) -> str | None:
    """Read a non-empty request ID from API Gateway request context."""
    request_context = event.get("requestContext")

    if not isinstance(request_context, Mapping):
        return None

    raw_request_id = request_context.get("requestId")

    if not isinstance(raw_request_id, str):
        return None

    request_id = raw_request_id.strip()

    return request_id or None


def _generate_request_id(
    request_id_generator: RequestIdGenerator | None,
) -> str:
    """Generate the final request-ID fallback."""
    generator = request_id_generator or _default_request_id_generator
    generated_request_id = generator().strip()

    if not generated_request_id:
        raise ValueError("request ID generator must return a non-empty string")

    return generated_request_id


def _default_request_id_generator() -> str:
    """Generate an opaque request identifier."""
    return f"req_{uuid4().hex}"
