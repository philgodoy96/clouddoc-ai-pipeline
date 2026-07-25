"""Tests for the create-document-job Lambda handler."""

import json
from datetime import UTC, datetime

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    CreateDocumentJobCommand,
)
from clouddoc.domain import JobStatus
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
