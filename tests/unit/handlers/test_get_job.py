"""Tests for the get-document-job Lambda handler."""

import json
from datetime import UTC, datetime

from clouddoc.application import (
    ApplicationDependencyError,
    ApplicationNotFoundError,
    GetDocumentJobQuery,
)
from clouddoc.domain import JobStatus
from clouddoc.handlers.get_job import handle
from clouddoc.schemas.job_views import DocumentJobView

FIXED_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class RecordingGetService:
    """Query service double that records the received query."""

    def __init__(self) -> None:
        """Initialize query tracking."""
        self.queries: list[GetDocumentJobQuery] = []

    def execute(
        self,
        query: GetDocumentJobQuery,
    ) -> DocumentJobView:
        """Record the query and return a deterministic job view."""
        self.queries.append(query)

        return DocumentJobView(
            job_id=query.job_id,
            status=JobStatus.PENDING_UPLOAD,
            request_id="request-original",
            correlation_id="correlation-original",
            created_at=FIXED_TIME,
            updated_at=FIXED_TIME,
            attempts=0,
            error_reason=None,
        )


class MissingGetService:
    """Query service double that reports a missing job."""

    def execute(
        self,
        query: GetDocumentJobQuery,
    ) -> DocumentJobView:
        """Raise an application not-found error."""
        raise ApplicationNotFoundError("job missing")


class FailingGetService:
    """Query service double that reports dependency failure."""

    def execute(
        self,
        query: GetDocumentJobQuery,
    ) -> DocumentJobView:
        """Raise an application dependency failure."""
        raise ApplicationDependencyError("DynamoDB unavailable")


class UnexpectedFailureService:
    """Query service double that raises an unexpected exception."""

    def execute(
        self,
        query: GetDocumentJobQuery,
    ) -> DocumentJobView:
        """Raise an internal exception containing sensitive detail."""
        raise RuntimeError("internal table clouddoc-secret-table failed")


def make_event(
    *,
    path_parameters: object = None,
    headers: object = None,
) -> dict[str, object]:
    """Create a representative API Gateway event."""
    return {
        "pathParameters": path_parameters
        if path_parameters is not None
        else {
            "job_id": "job-001",
        },
        "headers": headers
        or {
            "x-request-id": "request-001",
            "x-correlation-id": "correlation-001",
        },
        "requestContext": {
            "requestId": "gateway-request-001",
        },
    }


def parse_body(
    response: dict[str, object],
) -> dict[str, object]:
    """Decode a handler response body."""
    body = response["body"]

    assert isinstance(body, str)

    parsed = json.loads(body)

    assert isinstance(parsed, dict)

    return parsed


def test_returns_document_job() -> None:
    """A valid route should return the requested job."""
    service = RecordingGetService()

    response = handle(
        make_event(),
        None,
        service=service,
    )

    assert response["statusCode"] == 200
    assert response["headers"] == {
        "content-type": "application/json",
        "x-request-id": "request-001",
        "x-correlation-id": "correlation-001",
    }
    assert parse_body(response) == {
        "job_id": "job-001",
        "status": "pending_upload",
        "request_id": "request-original",
        "correlation_id": "correlation-original",
        "created_at": "2026-07-25T12:00:00Z",
        "updated_at": "2026-07-25T12:00:00Z",
        "attempts": 0,
        "error_reason": None,
    }


def test_passes_path_parameter_to_application_query() -> None:
    """The route job identity should reach the application service."""
    service = RecordingGetService()

    handle(
        make_event(
            path_parameters={
                "job_id": "job-special",
            }
        ),
        None,
        service=service,
    )

    assert service.queries == [
        GetDocumentJobQuery(
            job_id="job-special",
        )
    ]


def test_trims_job_id_path_parameter() -> None:
    """Surrounding whitespace should not enter the query contract."""
    service = RecordingGetService()

    handle(
        make_event(
            path_parameters={
                "job_id": "  job-001  ",
            }
        ),
        None,
        service=service,
    )

    assert service.queries == [
        GetDocumentJobQuery(
            job_id="job-001",
        )
    ]


def test_maps_missing_job() -> None:
    """A missing application resource should map to HTTP 404."""
    response = handle(
        make_event(),
        None,
        service=MissingGetService(),
    )

    assert response["statusCode"] == 404
    assert parse_body(response)["error"] == {
        "code": "job_not_found",
        "message": "Document job was not found.",
        "request_id": "request-001",
        "correlation_id": "correlation-001",
    }


def test_maps_application_dependency_failure() -> None:
    """Unavailable dependencies should map to HTTP 503."""
    response = handle(
        make_event(),
        None,
        service=FailingGetService(),
    )

    assert response["statusCode"] == 503
    assert parse_body(response)["error"] == {
        "code": "service_unavailable",
        "message": ("Document job service is temporarily unavailable."),
        "request_id": "request-001",
        "correlation_id": "correlation-001",
    }


def test_maps_unexpected_failure_without_exposing_details() -> None:
    """Internal exception details must not enter the response."""
    response = handle(
        make_event(),
        None,
        service=UnexpectedFailureService(),
    )

    serialized_response = json.dumps(response)

    assert response["statusCode"] == 500
    assert "clouddoc-secret-table" not in serialized_response
    assert "RuntimeError" not in serialized_response
    assert parse_body(response)["error"] == {
        "code": "internal_error",
        "message": "An unexpected error occurred.",
        "request_id": "request-001",
        "correlation_id": "correlation-001",
    }


def test_rejects_missing_path_parameters() -> None:
    """A request without route parameters should return HTTP 400."""
    response = handle(
        make_event(path_parameters={}),
        None,
        service=RecordingGetService(),
    )

    assert response["statusCode"] == 400
    assert parse_body(response)["error"] == {
        "code": "invalid_request",
        "message": "A valid job_id path parameter is required.",
        "request_id": "request-001",
        "correlation_id": "correlation-001",
    }


def test_rejects_blank_job_id() -> None:
    """Blank route identities should not reach the application."""
    service = RecordingGetService()

    response = handle(
        make_event(
            path_parameters={
                "job_id": "   ",
            }
        ),
        None,
        service=service,
    )

    assert response["statusCode"] == 400
    assert service.queries == []


def test_rejects_non_string_job_id() -> None:
    """Path identities should not be silently coerced."""
    service = RecordingGetService()

    response = handle(
        make_event(
            path_parameters={
                "job_id": 123,
            }
        ),
        None,
        service=service,
    )

    assert response["statusCode"] == 400
    assert service.queries == []


def test_rejects_non_mapping_path_parameters() -> None:
    """Malformed path parameter containers should fail safely."""
    response = handle(
        make_event(
            path_parameters=["job-001"],
        ),
        None,
        service=RecordingGetService(),
    )

    assert response["statusCode"] == 400


def test_rejects_non_mapping_event() -> None:
    """Malformed Lambda input should return a traced client error."""
    response = handle(
        "invalid-event",
        None,
        service=RecordingGetService(),
    )

    assert response["statusCode"] == 400

    error = parse_body(response)["error"]

    assert error["code"] == "invalid_request"
    assert isinstance(error["request_id"], str)
    assert error["correlation_id"] == error["request_id"]


def test_response_trace_headers_use_current_request_context() -> None:
    """Response headers should identify the current API request."""
    response = handle(
        make_event(
            headers={
                "X-Request-ID": "request-special",
                "X-Correlation-ID": "correlation-special",
            }
        ),
        None,
        service=RecordingGetService(),
    )

    assert response["headers"] == {
        "content-type": "application/json",
        "x-request-id": "request-special",
        "x-correlation-id": "correlation-special",
    }
