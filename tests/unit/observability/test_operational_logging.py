"""Tests for structured operational logging."""

from __future__ import annotations

import logging
from typing import cast

import pytest

from clouddoc.observability import (
    DEFAULT_OPERATIONAL_SERVICE,
    NullOperationalLogger,
    OperationalLogger,
    StandardOperationalLogger,
)


class RecordingHandler(logging.Handler):
    """Capture emitted log records for deterministic assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Record one emitted log entry."""
        self.records.append(record)


class RaisingLogger(logging.Logger):
    """Simulate an unexpected logging implementation failure."""

    def __init__(self) -> None:
        super().__init__("raising-operational-logger", level=logging.DEBUG)

    def isEnabledFor(self, level: int) -> bool:
        """Allow every tested log level."""
        del level
        return True

    def log(
        self,
        level: int,
        msg: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        """Fail every emission attempt."""
        del level, msg, args, kwargs
        raise RuntimeError("simulated logging failure")


def make_logger(
    *,
    level: int = logging.DEBUG,
    component: str = "document-processor",
    service: str = DEFAULT_OPERATIONAL_SERVICE,
) -> tuple[StandardOperationalLogger, RecordingHandler]:
    """Create one isolated operational logger and recording handler."""
    python_logger = logging.Logger(
        f"test.{service}.{component}",
        level=level,
    )
    python_logger.propagate = False

    handler = RecordingHandler()
    python_logger.addHandler(handler)

    return (
        StandardOperationalLogger(
            component=component,
            service=service,
            logger=python_logger,
        ),
        handler,
    )


def test_operational_logger_implementations_satisfy_protocol() -> None:
    """Both concrete loggers should satisfy the public runtime protocol."""
    logger, _ = make_logger()

    assert isinstance(logger, OperationalLogger)
    assert isinstance(NullOperationalLogger(), OperationalLogger)


def test_info_emits_flat_structured_event() -> None:
    """An informational event should preserve approved operational context."""
    logger, handler = make_logger(
        component=" document-processor ",
        service=" cloud-doc ",
    )

    logger.info(
        " processing.record_completed ",
        operation="process_document",
        outcome="processed",
        request_id="request-001",
        correlation_id="correlation-001",
        job_id="job-001",
        processing_attempt_id="attempt-001",
        sqs_message_id="message-001",
        duration_ms=125.5,
        retryable=False,
        total_tokens=150,
        failure_reason=None,
    )

    assert len(handler.records) == 1
    record = handler.records[0]

    assert record.levelno == logging.INFO
    assert record.getMessage() == "processing.record_completed"
    assert record.event_name == "processing.record_completed"
    assert record.service == "cloud-doc"
    assert record.component == "document-processor"
    assert record.operation == "process_document"
    assert record.outcome == "processed"
    assert record.request_id == "request-001"
    assert record.correlation_id == "correlation-001"
    assert record.job_id == "job-001"
    assert record.processing_attempt_id == "attempt-001"
    assert record.sqs_message_id == "message-001"
    assert record.duration_ms == 125.5
    assert record.retryable is False
    assert record.total_tokens == 150
    assert record.failure_reason is None
    assert not hasattr(record, "dropped_field_count")


@pytest.mark.parametrize(
    ("method_name", "expected_level"),
    [
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
    ],
)
def test_warning_and_error_use_expected_levels(
    method_name: str,
    expected_level: int,
) -> None:
    """Each public severity method should emit its matching logging level."""
    logger, handler = make_logger()

    getattr(logger, method_name)(
        "processing.record_failed",
        outcome="retryable_failure",
        error_code="application_dependency_error",
    )

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.levelno == expected_level
    assert record.event_name == "processing.record_failed"
    assert record.outcome == "retryable_failure"
    assert record.error_code == "application_dependency_error"


def test_all_approved_field_names_are_emitted() -> None:
    """The public field catalog should remain available to instrumentation."""
    logger, handler = make_logger()

    expected_fields = {
        "batch_size": 1,
        "correlation_id": "correlation-001",
        "duration_ms": 10.5,
        "error_code": "dependency_error",
        "exception_type": "ApplicationDependencyError",
        "failed_record_count": 1,
        "failure_reason": "provider_unavailable",
        "input_tokens": 100,
        "job_id": "job-001",
        "model_id": "amazon.nova-micro-v1:0",
        "operation": "process_document",
        "outcome": "retryable_failure",
        "output_tokens": 50,
        "processed_record_count": 0,
        "processing_attempt_id": "attempt-001",
        "provider_error_code": "ai_provider_unavailable",
        "provider_latency_ms": 125,
        "provider_name": "bedrock",
        "provider_request_id": "provider-request-001",
        "request_id": "request-001",
        "retryable": True,
        "sqs_message_id": "message-001",
        "status_code": 503,
        "stop_reason": "end_turn",
        "total_tokens": 150,
    }

    logger.info("catalog.checked", **expected_fields)

    assert len(handler.records) == 1
    record = handler.records[0]
    for field_name, expected_value in expected_fields.items():
        assert getattr(record, field_name) == expected_value

    assert not hasattr(record, "dropped_field_count")


def test_unknown_fields_are_not_serialized() -> None:
    """Unapproved field names must not enter the structured log record."""
    logger, handler = make_logger()

    logger.info(
        "processing.record_completed",
        outcome="processed",
        document_text="confidential document",
        raw_model_response='{"summary": "secret"}',
        authorization="Bearer secret",
    )

    assert len(handler.records) == 1
    record = handler.records[0]

    assert record.outcome == "processed"
    assert record.dropped_field_count == 3
    assert not hasattr(record, "document_text")
    assert not hasattr(record, "raw_model_response")
    assert not hasattr(record, "authorization")


@pytest.mark.parametrize(
    ("field_name", "unsafe_value"),
    [
        ("duration_ms", float("nan")),
        ("duration_ms", float("inf")),
        ("duration_ms", float("-inf")),
        ("error_code", {"nested": "value"}),
        ("failure_reason", ["nested", "value"]),
        ("request_id", object()),
    ],
)
def test_unsafe_values_are_not_serialized(
    field_name: str,
    unsafe_value: object,
) -> None:
    """Nested, opaque, and non-finite values must be dropped safely."""
    logger, handler = make_logger()

    logger.info(
        "processing.record_completed",
        **{field_name: cast(str, unsafe_value)},
    )

    assert len(handler.records) == 1
    record = handler.records[0]

    assert record.dropped_field_count == 1
    assert not hasattr(record, field_name)


@pytest.mark.parametrize(
    "event_name",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
        None,
        123,
    ],
)
def test_invalid_event_names_are_ignored(event_name: object) -> None:
    """Invalid event names should not raise or emit partial records."""
    logger, handler = make_logger()

    logger.info(
        cast(str, event_name),
        outcome="ignored",
    )

    assert handler.records == []


def test_disabled_level_does_not_emit_event() -> None:
    """The standard logger should respect the wrapped logger level."""
    logger, handler = make_logger(level=logging.WARNING)

    logger.info(
        "processing.record_completed",
        outcome="processed",
    )

    assert handler.records == []

    logger.warning(
        "processing.record_failed",
        outcome="retryable_failure",
    )

    assert len(handler.records) == 1
    assert handler.records[0].levelno == logging.WARNING


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("component", ""),
        ("component", " "),
        ("component", "\t"),
        ("service", ""),
        ("service", " "),
        ("service", "\n"),
    ],
)
def test_constructor_rejects_blank_identity_labels(
    field_name: str,
    value: str,
) -> None:
    """Service and component labels must contain non-whitespace content."""
    kwargs = {
        "component": "document-processor",
        "service": DEFAULT_OPERATIONAL_SERVICE,
    }
    kwargs[field_name] = value

    with pytest.raises(
        ValueError,
        match=f"{field_name} must not be empty",
    ):
        StandardOperationalLogger(**kwargs)


def test_logging_failure_does_not_escape_observability_boundary() -> None:
    """An internal logging failure must not change a business outcome."""
    logger = StandardOperationalLogger(
        component="document-processor",
        logger=RaisingLogger(),
    )

    logger.error(
        "processing.record_failed",
        outcome="retryable_failure",
        error_code="application_dependency_error",
    )


def test_null_logger_discards_every_severity() -> None:
    """The null implementation should accept events without side effects."""
    logger = NullOperationalLogger()

    assert (
        logger.info(
            "processing.record_completed",
            outcome="processed",
        )
        is None
    )
    assert (
        logger.warning(
            "processing.record_failed",
            outcome="retryable_failure",
        )
        is None
    )
    assert (
        logger.error(
            "processing.record_failed",
            outcome="internal_error",
        )
        is None
    )
