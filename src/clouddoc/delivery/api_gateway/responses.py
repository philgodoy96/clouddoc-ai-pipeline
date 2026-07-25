"""API Gateway response construction helpers."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from clouddoc.delivery.api_gateway.errors import APIError

JSON_CONTENT_TYPE = "application/json"
DEFAULT_RESPONSE_HEADERS = {
    "content-type": JSON_CONTENT_TYPE,
}


@dataclass(frozen=True, slots=True)
class APIResponse:
    """Transport-neutral representation of an API Gateway response."""

    status_code: int
    body: dict[str, Any]
    headers: dict[str, str]

    def to_api_gateway_response(self) -> dict[str, object]:
        """Serialize the response into API Gateway proxy format."""
        return {
            "statusCode": self.status_code,
            "headers": dict(self.headers),
            "body": json.dumps(
                self.body,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        }


def success_response(
    *,
    status_code: int,
    body: BaseModel | Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build a successful JSON API Gateway response."""
    payload = _serialize_body(body)

    return APIResponse(
        status_code=_validate_status_code(status_code),
        body=payload,
        headers=_merge_headers(headers),
    ).to_api_gateway_response()


def error_response(
    *,
    status_code: int,
    error: APIError,
    headers: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Build a safe JSON API Gateway error response."""
    return APIResponse(
        status_code=_validate_status_code(status_code),
        body=error.to_payload(),
        headers=_merge_headers(headers),
    ).to_api_gateway_response()


def _serialize_body(
    body: BaseModel | Mapping[str, Any],
) -> dict[str, Any]:
    """Convert an approved response object into JSON-compatible data."""
    if isinstance(body, BaseModel):
        serialized = body.model_dump(mode="json")

        if not isinstance(serialized, dict):
            raise TypeError("response model must serialize to an object")

        return serialized

    if isinstance(body, Mapping):
        return {str(key): value for key, value in body.items()}

    raise TypeError("response body must be a Pydantic model or mapping")


def _validate_status_code(
    status_code: int,
) -> int:
    """Require a valid HTTP response status code."""
    if isinstance(status_code, bool):
        raise ValueError("status code must be an integer")

    if not isinstance(status_code, int):
        raise ValueError("status code must be an integer")

    if not 100 <= status_code <= 599:
        raise ValueError("status code must be between 100 and 599")

    return status_code


def _merge_headers(
    headers: Mapping[str, str] | None,
) -> dict[str, str]:
    """Merge caller headers with required JSON response headers."""
    merged_headers = dict(DEFAULT_RESPONSE_HEADERS)

    if headers is None:
        return merged_headers

    for raw_name, raw_value in headers.items():
        if not isinstance(raw_name, str):
            raise TypeError("response header names must be strings")

        if not isinstance(raw_value, str):
            raise TypeError("response header values must be strings")

        name = raw_name.strip().lower()
        value = raw_value.strip()

        if not name:
            raise ValueError("response header names must not be empty")

        if not value:
            raise ValueError("response header values must not be empty")

        merged_headers[name] = value

    merged_headers["content-type"] = JSON_CONTENT_TYPE

    return merged_headers
