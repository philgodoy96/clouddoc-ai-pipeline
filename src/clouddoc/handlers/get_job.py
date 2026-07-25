"""Lambda handler for retrieving document jobs."""

from collections.abc import Mapping
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
from clouddoc.runtime import (
    RuntimeSettings,
    build_get_document_job_service,
)

_SERVICE: GetDocumentJob | None = None


def lambda_handler(
    event: object,
    context: object,
) -> dict[str, object]:
    """AWS Lambda entrypoint for document-job retrieval."""
    return handle(
        event,
        context,
        service=_get_service(),
    )


def handle(
    event: object,
    context: object,
    *,
    service: GetDocumentJob,
) -> dict[str, object]:
    """Handle one API Gateway document-job query request."""
    del context

    normalized_event: Mapping[str, Any] = event if isinstance(event, Mapping) else {}

    request_context = resolve_request_context(normalized_event)

    if not isinstance(event, Mapping):
        return _invalid_request_response(
            request_context,
            message="Request event must be an object.",
        )

    try:
        job_id = _parse_job_id(event)

        result = service.execute(
            GetDocumentJobQuery(
                job_id=job_id,
            )
        )
    except ValueError:
        return _invalid_request_response(
            request_context,
            message="A valid job_id path parameter is required.",
        )
    except ApplicationNotFoundError:
        return _error_response(
            status_code=404,
            code="job_not_found",
            message="Document job was not found.",
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
        status_code=200,
        body=result,
        headers=_trace_headers(request_context),
    )


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
