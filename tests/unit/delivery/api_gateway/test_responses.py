"""Tests for API Gateway response mapping."""

import json

import pytest
from pydantic import BaseModel, ConfigDict

from clouddoc.delivery.api_gateway.errors import APIError
from clouddoc.delivery.api_gateway.request_context import (
    APIRequestContext,
)
from clouddoc.delivery.api_gateway.responses import (
    error_response,
    success_response,
)


class ExampleResponseModel(BaseModel):
    """Simple immutable response model used by mapping tests."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    status: str


def make_request_context() -> APIRequestContext:
    """Create a deterministic request context."""
    return APIRequestContext(
        request_id="request-001",
        correlation_id="correlation-001",
    )


def parse_body(
    response: dict[str, object],
) -> dict[str, object]:
    """Decode a serialized API Gateway response body."""
    body = response["body"]

    assert isinstance(body, str)

    parsed = json.loads(body)

    assert isinstance(parsed, dict)

    return parsed


def test_builds_success_response_from_pydantic_model() -> None:
    """Pydantic response models should become JSON payloads."""
    response = success_response(
        status_code=201,
        body=ExampleResponseModel(
            job_id="job-001",
            status="pending_upload",
        ),
    )

    assert response["statusCode"] == 201
    assert response["headers"] == {
        "content-type": "application/json",
    }
    assert parse_body(response) == {
        "job_id": "job-001",
        "status": "pending_upload",
    }


def test_builds_success_response_from_mapping() -> None:
    """Mapping payloads should serialize without mutation."""
    body = {
        "job_id": "job-001",
        "attempts": 0,
    }

    response = success_response(
        status_code=200,
        body=body,
    )

    assert parse_body(response) == body
    assert body == {
        "job_id": "job-001",
        "attempts": 0,
    }


def test_serializes_compact_json() -> None:
    """Responses should avoid unnecessary JSON whitespace."""
    response = success_response(
        status_code=200,
        body={
            "job_id": "job-001",
        },
    )

    assert response["body"] == '{"job_id":"job-001"}'


def test_preserves_unicode_payloads() -> None:
    """Client-facing text should remain readable in serialized JSON."""
    response = success_response(
        status_code=200,
        body={
            "message": "Documento processado",
        },
    )

    assert response["body"] == ('{"message":"Documento processado"}')


def test_builds_safe_error_response() -> None:
    """Errors should use the stable external response structure."""
    error = APIError.from_request_context(
        code="job_not_found",
        message="Document job was not found.",
        request_context=make_request_context(),
    )

    response = error_response(
        status_code=404,
        error=error,
    )

    assert response["statusCode"] == 404
    assert parse_body(response) == {
        "error": {
            "code": "job_not_found",
            "message": "Document job was not found.",
            "request_id": "request-001",
            "correlation_id": "correlation-001",
        }
    }


def test_error_factory_trims_code_and_message() -> None:
    """Error identifiers and messages should be normalized."""
    error = APIError.from_request_context(
        code="  invalid_request  ",
        message="  Request is invalid.  ",
        request_context=make_request_context(),
    )

    assert error.code == "invalid_request"
    assert error.message == "Request is invalid."


@pytest.mark.parametrize(
    ("code", "message", "expected_message"),
    [
        (
            "",
            "Request is invalid.",
            "error code must not be empty",
        ),
        (
            "   ",
            "Request is invalid.",
            "error code must not be empty",
        ),
        (
            "invalid_request",
            "",
            "error message must not be empty",
        ),
        (
            "invalid_request",
            "   ",
            "error message must not be empty",
        ),
    ],
)
def test_error_factory_rejects_blank_values(
    code: str,
    message: str,
    expected_message: str,
) -> None:
    """External errors require stable non-empty values."""
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        APIError.from_request_context(
            code=code,
            message=message,
            request_context=make_request_context(),
        )


def test_merges_custom_response_headers() -> None:
    """Approved response headers should be normalized and retained."""
    response = success_response(
        status_code=200,
        body={
            "job_id": "job-001",
        },
        headers={
            "X-Request-ID": "request-001",
        },
    )

    assert response["headers"] == {
        "content-type": "application/json",
        "x-request-id": "request-001",
    }


def test_custom_content_type_cannot_override_json() -> None:
    """JSON helpers should always return the approved content type."""
    response = success_response(
        status_code=200,
        body={},
        headers={
            "content-type": "text/plain",
        },
    )

    assert response["headers"] == {
        "content-type": "application/json",
    }


@pytest.mark.parametrize(
    "status_code",
    [
        99,
        600,
        -1,
    ],
)
def test_rejects_out_of_range_status_codes(
    status_code: int,
) -> None:
    """HTTP status codes must stay inside the valid range."""
    with pytest.raises(
        ValueError,
        match="status code must be between 100 and 599",
    ):
        success_response(
            status_code=status_code,
            body={},
        )


@pytest.mark.parametrize(
    "status_code",
    [
        True,
        False,
        200.0,
        "200",
    ],
)
def test_rejects_non_integer_status_codes(
    status_code: object,
) -> None:
    """Status codes must not be coerced from other value types."""
    with pytest.raises(
        ValueError,
        match="status code must be an integer",
    ):
        success_response(
            status_code=status_code,
            body={},
        )


def test_rejects_unsupported_response_body() -> None:
    """Response helpers should reject arbitrary body objects."""
    with pytest.raises(
        TypeError,
        match=("response body must be a Pydantic model or mapping"),
    ):
        success_response(
            status_code=200,
            body=["invalid"],
        )


@pytest.mark.parametrize(
    "headers",
    [
        {
            123: "value",
        },
        {
            "x-request-id": 123,
        },
    ],
)
def test_rejects_non_string_response_headers(
    headers: object,
) -> None:
    """Header names and values should not be silently coerced."""
    with pytest.raises(TypeError):
        success_response(
            status_code=200,
            body={},
            headers=headers,
        )


@pytest.mark.parametrize(
    "headers",
    [
        {
            "": "value",
        },
        {
            "   ": "value",
        },
        {
            "x-request-id": "",
        },
        {
            "x-request-id": "   ",
        },
    ],
)
def test_rejects_blank_response_headers(
    headers: object,
) -> None:
    """Headers require non-empty normalized names and values."""
    with pytest.raises(ValueError):
        success_response(
            status_code=200,
            body={},
            headers=headers,
        )
