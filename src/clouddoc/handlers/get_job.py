"""Lambda handler for retrieving document jobs."""

from collections.abc import Callable, Mapping
from time import perf_counter
from typing import Any

from clouddoc.application import (
    ApplicationDependencyError,
    ApplicationNotFoundError,
    GetDocumentJob,
    GetDocumentJobQuery,
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
    build_get_document_job_service,
)

Timer = Callable[[], float]

_NULL_LOGGER = NullOperationalLogger()
_LOGGER = StandardOperationalLogger(component="get-job")
_SERVICE: GetDocumentJob | None = None

_OPERATION = "get_document_job"
_COMPLETION_EVENT = "control_plane.request_completed"


def lambda_handler(
    event: object,
    context: object,
) -> dict[str, object]:
    """AWS Lambda entrypoint for document-job retrieval."""
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
    service: GetDocumentJob,
    logger: OperationalLogger = _NULL_LOGGER,
    timer: Timer = perf_counter,
) -> dict[str, object]:
    """Handle one API Gateway document-job query request."""
    del context
    started_at = timer()

    normalized_event: Mapping[str, Any] = event if isinstance(event, Mapping) else {}

    request_context = resolve_request_context(normalized_event)
    job_id: str | None = None

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
        job_id = _parse_job_id(event)

        result = service.execute(
            GetDocumentJobQuery(
                job_id=job_id,
            )
        )
    except ValueError as error:
        return _complete_request(
            response=_invalid_request_response(
                request_context,
                message="A valid job_id path parameter is required.",
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="invalid_request",
            error_code="invalid_request",
            exception_type=type(error).__name__,
            job_id=job_id,
        )
    except ApplicationNotFoundError as error:
        return _complete_request(
            response=_error_response(
                status_code=404,
                code="job_not_found",
                message="Document job was not found.",
                request_context=request_context,
            ),
            logger=logger,
            timer=timer,
            started_at=started_at,
            request_context=request_context,
            operation=_OPERATION,
            outcome="not_found",
            error_code="job_not_found",
            exception_type=type(error).__name__,
            job_id=job_id,
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
            job_id=job_id,
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
            job_id=job_id,
        )

    return _complete_request(
        response=success_response(
            status_code=200,
            body=result,
            headers=_trace_headers(request_context),
        ),
        logger=logger,
        timer=timer,
        started_at=started_at,
        request_context=request_context,
        operation=_OPERATION,
        outcome="succeeded",
        job_id=job_id,
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


def _get_service() -> GetDocumentJob:
    """Build and cache the query service for warm invocations."""
    global _SERVICE

    if _SERVICE is None:
        settings = RuntimeSettings.from_environment()
        _SERVICE = build_get_document_job_service(
            settings=settings,
        )

    return _SERVICE


def _parse_job_id(
    event: Mapping[str, Any],
) -> str:
    """Read and validate the job identifier from path parameters."""
    path_parameters = event.get("pathParameters")

    if not isinstance(path_parameters, Mapping):
        raise ValueError("path parameters must be an object")

    raw_job_id = path_parameters.get("job_id")

    if not isinstance(raw_job_id, str):
        raise ValueError("job_id must be a string")

    job_id = raw_job_id.strip()

    if not job_id:
        raise ValueError("job_id must not be empty")

    return job_id


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
