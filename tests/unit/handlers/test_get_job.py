"""Tests for the get-document-job Lambda handler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import NamedTuple

import pytest

from clouddoc.application import (
    ApplicationDependencyError,
    ApplicationNotFoundError,
    GetDocumentJobQuery,
)
from clouddoc.domain import JobStatus
from clouddoc.handlers import get_job as get_job_module
from clouddoc.handlers.get_job import handle
from clouddoc.schemas.job_views import DocumentJobView

FIXED_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

SENSITIVE_FRAGMENTS = (
    "https://example.com/presigned-upload",
    "documents/job-001/source.txt",
    "clouddoc-secret-table",
    "DynamoDB unavailable",
    "job missing",
)


class RecordedOperationalEvent(NamedTuple):
    """One captured operational logger emission."""

    level: str
    event_name: str
    fields: dict[str, object]


class RecordingOperationalLogger:
    """Operational logger double that records every emission."""

    def __init__(self) -> None:
        """Initialize an empty event list."""
        self.events: list[RecordedOperationalEvent] = []

    def info(self, event_name: str, **fields: object) -> None:
        """Record an informational event."""
        self.events.append(
            RecordedOperationalEvent(
                level="info",
                event_name=event_name,
                fields=dict(fields),
            )
        )

    def warning(self, event_name: str, **fields: object) -> None:
        """Record a warning event."""
        self.events.append(
            RecordedOperationalEvent(
                level="warning",
                event_name=event_name,
                fields=dict(fields),
            )
        )

    def error(self, event_name: str, **fields: object) -> None:
        """Record an error event."""
        self.events.append(
            RecordedOperationalEvent(
                level="error",
                event_name=event_name,
                fields=dict(fields),
            )
        )


class RaisingOperationalLogger:
    """Operational logger double that fails every emission."""

    def info(self, event_name: str, **fields: object) -> None:
        """Fail informational emission."""
        del event_name, fields
        raise RuntimeError("logger info failure")

    def warning(self, event_name: str, **fields: object) -> None:
        """Fail warning emission."""
        del event_name, fields
        raise RuntimeError("logger warning failure")

    def error(self, event_name: str, **fields: object) -> None:
        """Fail error emission."""
        del event_name, fields
        raise RuntimeError("logger error failure")


class SequenceTimer:
    """Deterministic timer that returns a fixed sequence of values."""

    def __init__(self, *values: float) -> None:
        """Store the values that will be returned on successive calls."""
        self._values = list(values)
        self._index = 0

    def __call__(self) -> float:
        """Return the next configured timer value."""
        if self._index >= len(self._values):
            raise RuntimeError("SequenceTimer exhausted")

        value = self._values[self._index]
        self._index += 1
        return value


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


def assert_fields_exclude_sensitive_content(
    fields: dict[str, object],
) -> None:
    """Prove structured fields omit sensitive payload and message content."""
    serialized = json.dumps(fields)

    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in serialized


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


def test_successful_retrieval_emits_one_info_completion_event() -> None:
    """Successful retrieval should emit exactly one safe info event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        make_event(),
        None,
        service=RecordingGetService(),
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == 200
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == "info"
    assert event.event_name == "control_plane.request_completed"
    assert event.fields == {
        "operation": "get_document_job",
        "outcome": "succeeded",
        "status_code": 200,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "job_id": "job-001",
    }
    assert "error_code" not in event.fields
    assert "exception_type" not in event.fields
    assert_fields_exclude_sensitive_content(event.fields)


def test_logged_job_id_excludes_surrounding_whitespace() -> None:
    """Logged job identity should use the normalized path parameter."""
    logger = RecordingOperationalLogger()

    response = handle(
        make_event(
            path_parameters={
                "job_id": "  job-001  ",
            }
        ),
        None,
        service=RecordingGetService(),
        logger=logger,
        timer=SequenceTimer(10.0, 10.125),
    )

    assert response["statusCode"] == 200
    assert len(logger.events) == 1
    assert logger.events[0].fields["job_id"] == "job-001"


def test_missing_job_emits_one_warning_completion_event() -> None:
    """Missing jobs should emit one warning with the normalized job ID."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        make_event(),
        None,
        service=MissingGetService(),
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == 404
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == "warning"
    assert event.event_name == "control_plane.request_completed"
    assert event.fields == {
        "operation": "get_document_job",
        "outcome": "not_found",
        "status_code": 404,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "job_id": "job-001",
        "error_code": "job_not_found",
        "exception_type": "ApplicationNotFoundError",
    }
    assert_fields_exclude_sensitive_content(event.fields)


def test_invalid_path_emits_one_warning_without_job_id() -> None:
    """Invalid path parameters should emit one warning without job_id."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        make_event(path_parameters={}),
        None,
        service=RecordingGetService(),
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == 400
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == "warning"
    assert event.event_name == "control_plane.request_completed"
    assert event.fields == {
        "operation": "get_document_job",
        "outcome": "invalid_request",
        "status_code": 400,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "error_code": "invalid_request",
        "exception_type": "ValueError",
    }
    assert "job_id" not in event.fields
    assert_fields_exclude_sensitive_content(event.fields)


@pytest.mark.parametrize(
    ("service", "status_code", "level", "outcome", "error_code", "exception_type"),
    [
        (
            FailingGetService(),
            503,
            "error",
            "dependency_failure",
            "service_unavailable",
            "ApplicationDependencyError",
        ),
        (
            UnexpectedFailureService(),
            500,
            "error",
            "internal_error",
            "internal_error",
            "RuntimeError",
        ),
    ],
)
def test_mapped_failures_emit_one_completion_event_with_job_id(
    service: object,
    status_code: int,
    level: str,
    outcome: str,
    error_code: str,
    exception_type: str,
) -> None:
    """Dependency and unexpected failures should include the parsed job ID."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        make_event(),
        None,
        service=service,  # type: ignore[arg-type]
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == status_code
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == level
    assert event.event_name == "control_plane.request_completed"
    assert event.fields == {
        "operation": "get_document_job",
        "outcome": outcome,
        "status_code": status_code,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "job_id": "job-001",
        "error_code": error_code,
        "exception_type": exception_type,
    }
    assert_fields_exclude_sensitive_content(event.fields)


def test_non_mapping_event_emits_one_warning_without_job_id_or_exception() -> None:
    """Non-mapping events should emit one warning without job_id or exception."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        "invalid-event",
        None,
        service=RecordingGetService(),
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == 400
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == "warning"
    assert event.event_name == "control_plane.request_completed"
    assert event.fields["outcome"] == "invalid_request"
    assert event.fields["error_code"] == "invalid_request"
    assert "job_id" not in event.fields
    assert "exception_type" not in event.fields
    assert_fields_exclude_sensitive_content(event.fields)


def test_raising_logger_does_not_change_successful_response() -> None:
    """Logger failures must not alter the successful HTTP response."""
    response = handle(
        make_event(),
        None,
        service=RecordingGetService(),
        logger=RaisingOperationalLogger(),
        timer=SequenceTimer(10.0, 10.125),
    )

    assert response["statusCode"] == 200
    assert parse_body(response)["job_id"] == "job-001"
    assert response["headers"] == {
        "content-type": "application/json",
        "x-request-id": "request-001",
        "x-correlation-id": "correlation-001",
    }


def test_lambda_handler_passes_module_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production entrypoint should wire the module-level operational logger."""
    logger = RecordingOperationalLogger()
    service = RecordingGetService()

    monkeypatch.setattr(get_job_module, "_LOGGER", logger)
    monkeypatch.setattr(get_job_module, "_get_service", lambda: service)

    response = get_job_module.lambda_handler(
        make_event(),
        None,
    )

    assert response["statusCode"] == 200
    assert len(logger.events) == 1
    assert logger.events[0].event_name == "control_plane.request_completed"
    assert logger.events[0].fields["outcome"] == "succeeded"
