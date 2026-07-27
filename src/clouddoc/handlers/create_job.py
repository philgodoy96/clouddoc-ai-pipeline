"""Lambda handler for creating document jobs."""

import json
from collections.abc import Callable, Mapping
from time import perf_counter
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
from clouddoc.observability import (
    NullOperationalLogger,
    OperationalLogger,
    StandardOperationalLogger,
)
from clouddoc.runtime import (
    RuntimeSettings,
    build_create_document_job_service,
)

Timer = Callable[[], float]

_NULL_LOGGER = NullOperationalLogger()
_LOGGER = StandardOperationalLogger(component="create-job")
_SERVICE: CreateDocumentJob | None = None

_OPERATION = "create_document_job"
_COMPLETION_EVENT = "control_plane.request_completed"


def lambda_handler(
    event: object,
    context: object,
) -> dict[str, object]:
    """AWS Lambda entrypoint for document-job creation."""
    return handle(
        event,
        context,
        service=_get_service(),
        logger=_LOGGER,
    )


def handle(
    event: object,
    context: object,
    *,
    service: CreateDocumentJob,
    logger: OperationalLogger = _NULL_LOGGER,
    timer: Timer = perf_counter,
) -> dict[str, object]:
    """Handle one API Gateway document-job creation request."""
    del context
    started_at = timer()

    normalized_event: Mapping[str, Any] = event if isinstance(event, Mapping) else {}

    request_context = resolve_request_context(normalized_event)

    if not isinstance(event, Mapping):
        return _complete_request(
            response=_invalid_request_response(
                request_context,
                message="Request event must be an object.",
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="invalid_request",
            error_code="invalid_request",
        )

    try:
        _validate_request_body(event)

        result = service.execute(
            CreateDocumentJobCommand(
                request_id=request_context.request_id,
                correlation_id=request_context.correlation_id,
            )
        )
    except ValueError as error:
        return _complete_request(
            response=_invalid_request_response(
                request_context,
                message="Request body must be an empty JSON object.",
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="invalid_request",
            error_code="invalid_request",
            exception_type=type(error).__name__,
        )
    except ApplicationConflictError as error:
        return _complete_request(
            response=_error_response(
                status_code=409,
                code="job_conflict",
                message="Document job could not be created.",
                request_context=request_context,
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="conflict",
            error_code="job_conflict",
            exception_type=type(error).__name__,
        )
    except ApplicationDependencyError as error:
        return _complete_request(
            response=_error_response(
                status_code=503,
                code="service_unavailable",
                message="Document job service is temporarily unavailable.",
                request_context=request_context,
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="dependency_failure",
            error_code="service_unavailable",
            exception_type=type(error).__name__,
        )
    except Exception as error:
        return _complete_request(
            response=_error_response(
                status_code=500,
                code="internal_error",
                message="An unexpected error occurred.",
                request_context=request_context,
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="internal_error",
            error_code="internal_error",
            exception_type=type(error).__name__,
        )

    return _complete_request(
        response=success_response(
            status_code=201,
            body=result,
            headers=_trace_headers(request_context),
        ),
        logger=logger,
        timer=timer,
        started_at=started_at,
        request_context=request_context,
        operation=_OPERATION,
        outcome="succeeded",
        job_id=result.job.job_id,
    )


def _complete_request(
    *,
    response: dict[str, object],
    logger: OperationalLogger,
    timer: Timer,
    started_at: float,
    request_context: APIRequestContext,
    operation: str,
    outcome: str,
    job_id: str | None = None,
    error_code: str | None = None,
    exception_type: str | None = None,
) -> dict[str, object]:
    """Emit one safe completion event without altering the HTTP response."""
    try:
        status_code = response.get("statusCode")
        if not isinstance(status_code, int):
            return response

        duration_ms = round(max(0.0, timer() - started_at) * 1_000, 3)

        fields: dict[str, object] = {
            "operation": operation,
            "outcome": outcome,
            "status_code": status_code,
            "request_id": request_context.request_id,
            "correlation_id": request_context.correlation_id,
            "duration_ms": duration_ms,
        }
        if job_id is not None:
            fields["job_id"] = job_id
        if error_code is not None:
            fields["error_code"] = error_code
        if exception_type is not None:
            fields["exception_type"] = exception_type

        if 200 <= status_code <= 399:
            logger.info(_COMPLETION_EVENT, **fields)
        elif 400 <= status_code <= 499:
            logger.warning(_COMPLETION_EVENT, **fields)
        elif status_code >= 500:
            logger.error(_COMPLETION_EVENT, **fields)
    except Exception:
        # Operational telemetry must never change a business outcome.
        pass

    return response


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
