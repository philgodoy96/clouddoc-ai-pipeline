"""Lambda handler for creating document jobs."""

import json
from collections.abc import Mapping
from typing import Any

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    CreateDocumentJob,
    CreateDocumentJobCommand,
)
from clouddoc.delivery.api_gateway.errors import APIError
from clouddoc.delivery.api_gateway.request_context import (
    APIRequestContext,
    resolve_request_context,
)
from clouddoc.delivery.api_gateway.responses import (
    error_response,
    success_response,
)
from clouddoc.runtime import (
    RuntimeSettings,
    build_create_document_job_service,
)

_SERVICE: CreateDocumentJob | None = None


def lambda_handler(
    event: object,
    context: object,
) -> dict[str, object]:
    """AWS Lambda entrypoint for document-job creation."""
    return handle(
        event,
        context,
        service=_get_service(),
    )


def handle(
    event: object,
    context: object,
    *,
    service: CreateDocumentJob,
) -> dict[str, object]:
    """Handle one API Gateway document-job creation request."""
    del context

    normalized_event: Mapping[str, Any] = event if isinstance(event, Mapping) else {}

    request_context = resolve_request_context(normalized_event)

    if not isinstance(event, Mapping):
        return _invalid_request_response(
            request_context,
            message="Request event must be an object.",
        )

    try:
        _validate_request_body(event)

        result = service.execute(
            CreateDocumentJobCommand(
                request_id=request_context.request_id,
                correlation_id=request_context.correlation_id,
            )
        )
    except ValueError:
        return _invalid_request_response(
            request_context,
            message="Request body must be an empty JSON object.",
        )
    except ApplicationConflictError:
        return _error_response(
            status_code=409,
            code="job_conflict",
            message="Document job could not be created.",
            request_context=request_context,
        )
    except ApplicationDependencyError:
        return _error_response(
            status_code=503,
            code="service_unavailable",
            message="Document job service is temporarily unavailable.",
            request_context=request_context,
        )
    except Exception:
        return _error_response(
            status_code=500,
            code="internal_error",
            message="An unexpected error occurred.",
            request_context=request_context,
        )

    return success_response(
        status_code=201,
        body=result,
        headers=_trace_headers(request_context),
    )


def _get_service() -> CreateDocumentJob:
    """Build and cache the creation service for warm invocations."""
    global _SERVICE

    if _SERVICE is None:
        settings = RuntimeSettings.from_environment()
        _SERVICE = build_create_document_job_service(
            settings=settings,
        )

    return _SERVICE


def _validate_request_body(
    event: Mapping[str, Any],
) -> None:
    """Require an absent body or an empty JSON object."""
    if event.get("isBase64Encoded") is True:
        raise ValueError("base64 request bodies are not supported")

    raw_body = event.get("body")

    if raw_body is None:
        return

    if not isinstance(raw_body, str):
        raise ValueError("request body must be a string")

    if not raw_body.strip():
        return

    try:
        parsed_body = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise ValueError("request body must contain valid JSON") from error

    if not isinstance(parsed_body, dict):
        raise ValueError("request body must be a JSON object")

    if parsed_body:
        raise ValueError("request body does not accept fields")


def _invalid_request_response(
    request_context: APIRequestContext,
    *,
    message: str,
) -> dict[str, object]:
    """Build a safe invalid-request response."""
    return _error_response(
        status_code=400,
        code="invalid_request",
        message=message,
        request_context=request_context,
    )


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_context: APIRequestContext,
) -> dict[str, object]:
    """Build an error response with request trace headers."""
    error = APIError.from_request_context(
        code=code,
        message=message,
        request_context=request_context,
    )

    return error_response(
        status_code=status_code,
        error=error,
        headers=_trace_headers(request_context),
    )


def _trace_headers(
    request_context: APIRequestContext,
) -> dict[str, str]:
    """Expose trace identifiers in response headers."""
    return {
        "x-request-id": request_context.request_id,
        "x-correlation-id": request_context.correlation_id,
    }
