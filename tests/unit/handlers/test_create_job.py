"""Tests for the create-document-job Lambda handler."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import NamedTuple

import pytest

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    CreateDocumentJobCommand,
)
from clouddoc.domain import JobStatus
from clouddoc.handlers import create_job as create_job_module
from clouddoc.handlers.create_job import handle
from clouddoc.schemas.job_views import DocumentJobView
from clouddoc.schemas.upload_views import (
    CreateDocumentJobResult,
    PresignedDocumentUpload,
)

FIXED_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
FIXED_UPLOAD = PresignedDocumentUpload.create(
    url="https://example.com/presigned-upload",
    object_key="documents/job-001/source.txt",
    expires_in_seconds=900,
)

SENSITIVE_FRAGMENTS = (
    "https://example.com/presigned-upload",
    "documents/job-001/source.txt",
    "clouddoc-secret-table",
    "DynamoDB unavailable",
    "duplicate job",
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


def make_create_result(
    *,
    request_id: str,
    correlation_id: str,
) -> CreateDocumentJobResult:
    """Build a deterministic creation result for handler doubles."""
    return CreateDocumentJobResult(
        job=DocumentJobView(
            job_id="job-001",
            status=JobStatus.PENDING_UPLOAD,
            request_id=request_id,
            correlation_id=correlation_id,
            created_at=FIXED_TIME,
            updated_at=FIXED_TIME,
            attempts=0,
            error_reason=None,
        ),
        upload=FIXED_UPLOAD,
    )


class RecordingCreateService:
    """Creation service double that records the received command."""

    def __init__(self) -> None:
        """Initialize command tracking."""
        self.commands: list[CreateDocumentJobCommand] = []

    def execute(
        self,
        command: CreateDocumentJobCommand,
    ) -> CreateDocumentJobResult:
        """Record the command and return a deterministic result."""
        self.commands.append(command)

        return make_create_result(
            request_id=command.request_id,
            correlation_id=command.correlation_id,
        )


class ConflictCreateService:
    """Creation service double that reports a known conflict."""

    def execute(
        self,
        command: CreateDocumentJobCommand,
    ) -> CreateDocumentJobResult:
        """Raise an application conflict."""
        raise ApplicationConflictError("duplicate job")


class FailingCreateService:
    """Creation service double that reports dependency failure."""

    def execute(
        self,
        command: CreateDocumentJobCommand,
    ) -> CreateDocumentJobResult:
        """Raise an application dependency failure."""
        raise ApplicationDependencyError("DynamoDB unavailable")


class UnexpectedFailureService:
    """Creation service double that raises an unexpected exception."""

    def execute(
        self,
        command: CreateDocumentJobCommand,
    ) -> CreateDocumentJobResult:
        """Raise an internal exception containing sensitive detail."""
        raise RuntimeError("internal table clouddoc-secret-table failed")


def make_event(
    *,
    body: object = None,
    headers: object = None,
) -> dict[str, object]:
    """Create a representative API Gateway event."""
    return {
        "body": body,
        "headers": headers
        or {
            "x-request-id": "request-001",
            "x-correlation-id": "correlation-001",
        },
        "requestContext": {
            "requestId": "gateway-request-001",
        },
        "isBase64Encoded": False,
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


def test_returns_created_document_job() -> None:
    """A valid request should create and return a pending job."""
    service = RecordingCreateService()

    response = handle(
        make_event(body="{}"),
        None,
        service=service,
    )

    assert response["statusCode"] == 201
    assert response["headers"] == {
        "content-type": "application/json",
        "x-request-id": "request-001",
        "x-correlation-id": "correlation-001",
    }

    body = parse_body(response)

    assert body == {
        "job": {
            "job_id": "job-001",
            "status": "pending_upload",
            "request_id": "request-001",
            "correlation_id": "correlation-001",
            "created_at": "2026-07-25T12:00:00Z",
            "updated_at": "2026-07-25T12:00:00Z",
            "attempts": 0,
            "error_reason": None,
        },
        "upload": {
            "method": "PUT",
            "url": "https://example.com/presigned-upload",
            "headers": {
                "content-type": "text/plain",
            },
            "object_key": "documents/job-001/source.txt",
            "expires_in_seconds": 900,
        },
    }
    assert "object_key" in body["upload"]
    assert "url" in body["upload"]
    assert "headers" in body["upload"]
    assert "expires_in_seconds" in body["upload"]
    assert "bucket" not in body["upload"]
    assert "bucket_name" not in body["upload"]
    assert "bucket" not in json.dumps(body)
    assert "bucket_name" not in json.dumps(body)


def test_propagates_resolved_trace_context() -> None:
    """Trace identity should reach the application command."""
    service = RecordingCreateService()

    handle(
        make_event(
            headers={
                "X-Request-ID": "request-special",
                "X-Correlation-ID": "correlation-special",
            }
        ),
        None,
        service=service,
    )

    assert service.commands == [
        CreateDocumentJobCommand(
            request_id="request-special",
            correlation_id="correlation-special",
        )
    ]


def test_accepts_absent_or_blank_body() -> None:
    """The current creation endpoint requires no request fields."""
    for body in (None, "", "   ", "{}"):
        service = RecordingCreateService()

        response = handle(
            make_event(body=body),
            None,
            service=service,
        )

        assert response["statusCode"] == 201
        assert len(service.commands) == 1


def test_rejects_malformed_json_body() -> None:
    """Malformed JSON should produce a safe client error."""
    service = RecordingCreateService()

    response = handle(
        make_event(body="{invalid"),
        None,
        service=service,
    )

    assert response["statusCode"] == 400
    assert service.commands == []
    assert parse_body(response) == {
        "error": {
            "code": "invalid_request",
            "message": ("Request body must be an empty JSON object."),
            "request_id": "request-001",
            "correlation_id": "correlation-001",
        }
    }


def test_rejects_non_object_json_body() -> None:
    """Arrays, strings, and null are not valid request objects."""
    for body in ("[]", '"value"', "null", "123"):
        response = handle(
            make_event(body=body),
            None,
            service=RecordingCreateService(),
        )

        assert response["statusCode"] == 400


def test_rejects_unexpected_request_fields() -> None:
    """Caller-controlled lifecycle fields must not be accepted."""
    response = handle(
        make_event(
            body='{"status":"succeeded"}',
        ),
        None,
        service=RecordingCreateService(),
    )

    assert response["statusCode"] == 400
    assert parse_body(response)["error"]["code"] == ("invalid_request")


def test_rejects_base64_encoded_body() -> None:
    """Unsupported encoded bodies should fail explicitly."""
    event = make_event(body="e30=")
    event["isBase64Encoded"] = True

    response = handle(
        event,
        None,
        service=RecordingCreateService(),
    )

    assert response["statusCode"] == 400


def test_maps_application_conflict() -> None:
    """Known creation conflicts should map to HTTP 409."""
    response = handle(
        make_event(),
        None,
        service=ConflictCreateService(),
    )

    assert response["statusCode"] == 409
    assert parse_body(response)["error"] == {
        "code": "job_conflict",
        "message": "Document job could not be created.",
        "request_id": "request-001",
        "correlation_id": "correlation-001",
    }


def test_maps_application_dependency_failure() -> None:
    """Unavailable dependencies should map to HTTP 503."""
    response = handle(
        make_event(),
        None,
        service=FailingCreateService(),
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


def test_rejects_non_mapping_event() -> None:
    """Malformed Lambda input should return a traced client error."""
    response = handle(
        ["invalid-event"],
        None,
        service=RecordingCreateService(),
    )

    assert response["statusCode"] == 400

    error = parse_body(response)["error"]

    assert error["code"] == "invalid_request"
    assert isinstance(error["request_id"], str)
    assert error["correlation_id"] == error["request_id"]


def test_successful_creation_emits_one_info_completion_event() -> None:
    """Successful creation should emit exactly one safe info event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        make_event(body="{}"),
        None,
        service=RecordingCreateService(),
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == 201
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == "info"
    assert event.event_name == "control_plane.request_completed"
    assert event.fields == {
        "operation": "create_document_job",
        "outcome": "succeeded",
        "status_code": 201,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "job_id": "job-001",
    }
    assert "error_code" not in event.fields
    assert "exception_type" not in event.fields
    assert_fields_exclude_sensitive_content(event.fields)


def test_invalid_body_emits_one_warning_completion_event() -> None:
    """Invalid request bodies should emit one warning without secrets."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        make_event(body="{invalid"),
        None,
        service=RecordingCreateService(),
        logger=logger,
        timer=timer,
    )

    assert response["statusCode"] == 400
    assert len(logger.events) == 1

    event = logger.events[0]

    assert event.level == "warning"
    assert event.event_name == "control_plane.request_completed"
    assert event.fields == {
        "operation": "create_document_job",
        "outcome": "invalid_request",
        "status_code": 400,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "error_code": "invalid_request",
        "exception_type": "ValueError",
    }
    assert_fields_exclude_sensitive_content(event.fields)


@pytest.mark.parametrize(
    ("service", "status_code", "level", "outcome", "error_code", "exception_type"),
    [
        (
            ConflictCreateService(),
            409,
            "warning",
            "conflict",
            "job_conflict",
            "ApplicationConflictError",
        ),
        (
            FailingCreateService(),
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
def test_mapped_failures_emit_one_completion_event(
    service: object,
    status_code: int,
    level: str,
    outcome: str,
    error_code: str,
    exception_type: str,
) -> None:
    """Mapped application failures should emit exactly one completion event."""
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
        "operation": "create_document_job",
        "outcome": outcome,
        "status_code": status_code,
        "request_id": "request-001",
        "correlation_id": "correlation-001",
        "duration_ms": 125.0,
        "error_code": error_code,
        "exception_type": exception_type,
    }
    assert "job_id" not in event.fields
    assert_fields_exclude_sensitive_content(event.fields)


def test_non_mapping_event_emits_one_warning_without_exception_type() -> None:
    """Non-mapping events should emit one warning without an exception type."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response = handle(
        ["invalid-event"],
        None,
        service=RecordingCreateService(),
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
    assert "exception_type" not in event.fields
    assert "job_id" not in event.fields
    assert_fields_exclude_sensitive_content(event.fields)


def test_raising_logger_does_not_change_successful_response() -> None:
    """Logger failures must not alter the successful HTTP response."""
    response = handle(
        make_event(body="{}"),
        None,
        service=RecordingCreateService(),
        logger=RaisingOperationalLogger(),
        timer=SequenceTimer(10.0, 10.125),
    )

    assert response["statusCode"] == 201
    assert parse_body(response)["job"]["job_id"] == "job-001"
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
    service = RecordingCreateService()

    monkeypatch.setattr(create_job_module, "_LOGGER", logger)
    monkeypatch.setattr(create_job_module, "_get_service", lambda: service)

    response = create_job_module.lambda_handler(
        make_event(body="{}"),
        None,
    )

    assert response["statusCode"] == 201
    assert len(logger.events) == 1
    assert logger.events[0].event_name == "control_plane.request_completed"
    assert logger.events[0].fields["outcome"] == "succeeded"
