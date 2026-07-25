"""Tests for API Gateway request-context resolution."""

import re

import pytest

from clouddoc.delivery.api_gateway import (
    APIRequestContext,
    resolve_request_context,
)

GENERATED_REQUEST_ID_PATTERN = re.compile(r"^req_[0-9a-f]{32}$")


def test_resolves_request_and_correlation_ids_from_headers() -> None:
    """Explicit trace headers should take precedence."""
    context = resolve_request_context(
        {
            "headers": {
                "x-request-id": "request-001",
                "x-correlation-id": "correlation-001",
            },
            "requestContext": {
                "requestId": "gateway-request",
            },
        }
    )

    assert context == APIRequestContext(
        request_id="request-001",
        correlation_id="correlation-001",
    )


def test_resolves_headers_case_insensitively() -> None:
    """Header names should be normalized without case sensitivity."""
    context = resolve_request_context(
        {
            "headers": {
                "X-Request-ID": "request-001",
                "X-CORRELATION-id": "correlation-001",
            }
        }
    )

    assert context.request_id == "request-001"
    assert context.correlation_id == "correlation-001"


def test_trims_header_values() -> None:
    """Surrounding whitespace should not enter trace identity."""
    context = resolve_request_context(
        {
            "headers": {
                "x-request-id": "  request-001  ",
                "x-correlation-id": "  correlation-001  ",
            }
        }
    )

    assert context.request_id == "request-001"
    assert context.correlation_id == "correlation-001"


def test_uses_api_gateway_request_id_when_header_is_absent() -> None:
    """API Gateway identity should be the second request-ID source."""
    context = resolve_request_context(
        {
            "requestContext": {
                "requestId": "gateway-request-001",
            }
        }
    )

    assert context.request_id == "gateway-request-001"
    assert context.correlation_id == "gateway-request-001"


def test_correlation_id_falls_back_to_resolved_request_id() -> None:
    """Absent correlation identity should reuse the request identity."""
    context = resolve_request_context(
        {
            "headers": {
                "x-request-id": "request-001",
            }
        }
    )

    assert context == APIRequestContext(
        request_id="request-001",
        correlation_id="request-001",
    )


def test_generates_request_id_when_no_identity_is_available() -> None:
    """A fallback request identity should always be available."""
    context = resolve_request_context({})

    assert GENERATED_REQUEST_ID_PATTERN.fullmatch(context.request_id)
    assert context.correlation_id == context.request_id


def test_uses_injected_request_id_generator() -> None:
    """Tests and alternate runtimes may inject ID generation."""
    context = resolve_request_context(
        {},
        request_id_generator=lambda: "generated-request-001",
    )

    assert context == APIRequestContext(
        request_id="generated-request-001",
        correlation_id="generated-request-001",
    )


@pytest.mark.parametrize(
    "headers",
    [
        {
            "x-request-id": "",
            "x-correlation-id": "",
        },
        {
            "x-request-id": "   ",
            "x-correlation-id": "\t",
        },
        {
            "x-request-id": None,
            "x-correlation-id": 123,
        },
    ],
)
def test_ignores_invalid_or_blank_trace_headers(
    headers: object,
) -> None:
    """Invalid header values should not become request identity."""
    context = resolve_request_context(
        {
            "headers": headers,
            "requestContext": {
                "requestId": "gateway-request-001",
            },
        }
    )

    assert context.request_id == "gateway-request-001"
    assert context.correlation_id == "gateway-request-001"


@pytest.mark.parametrize(
    "request_context",
    [
        None,
        [],
        "invalid",
        {},
        {
            "requestId": None,
        },
        {
            "requestId": 123,
        },
        {
            "requestId": "   ",
        },
    ],
)
def test_ignores_invalid_api_gateway_request_context(
    request_context: object,
) -> None:
    """Malformed Gateway context should fall back safely."""
    context = resolve_request_context(
        {
            "requestContext": request_context,
        },
        request_id_generator=lambda: "generated-request-001",
    )

    assert context.request_id == "generated-request-001"
    assert context.correlation_id == "generated-request-001"


def test_explicit_correlation_id_uses_generated_request_id() -> None:
    """Correlation identity may coexist with a generated request ID."""
    context = resolve_request_context(
        {
            "headers": {
                "x-correlation-id": "correlation-001",
            }
        },
        request_id_generator=lambda: "generated-request-001",
    )

    assert context == APIRequestContext(
        request_id="generated-request-001",
        correlation_id="correlation-001",
    )


def test_rejects_blank_generated_request_id() -> None:
    """A broken generator must not produce missing trace identity."""
    with pytest.raises(
        ValueError,
        match="request ID generator must return a non-empty string",
    ):
        resolve_request_context(
            {},
            request_id_generator=lambda: "   ",
        )
