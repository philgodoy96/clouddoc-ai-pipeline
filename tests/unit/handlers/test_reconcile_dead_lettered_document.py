"""Tests for the DLQ reconciliation partial-batch handler."""

import json
from typing import NamedTuple

import pytest

from clouddoc.application.dead_letter_processing_ports import (
    DeadLetteredDocumentProcessingError,
)
from clouddoc.delivery.events.errors import (
    MalformedQueueEventError,
    MalformedQueueMessageError,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.handlers import reconcile_dead_lettered_document as handler_module
from clouddoc.handlers.reconcile_dead_lettered_document import (
    handle,
)
from clouddoc.runtime.settings import RuntimeSettings

EXPECTED_BUCKET = "clouddoc-documents"

SENSITIVE_FRAGMENTS = (
    "documents/job-001/source.txt",
    "clouddoc-documents",
    "etag-job-001",
    "not-json",
    "temporary failure for job-001",
    "unexpected failure for job-001",
    "temporary reconciliation failure for job-001",
    "unexpected reconciliation failure for job-001",
    "repository unavailable",
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


def assert_fields_exclude_sensitive_content(
    fields: dict[str, object],
) -> None:
    """Prove structured fields omit payload and exception message content."""
    serialized = json.dumps(fields, default=str)

    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in serialized


def events_by_name(
    logger: RecordingOperationalLogger,
    event_name: str,
) -> list[RecordedOperationalEvent]:
    """Return recorded events matching one event name."""
    return [event for event in logger.events if event.event_name == event_name]


def make_runtime_settings() -> RuntimeSettings:
    """Create immutable runtime settings for Lambda entrypoint tests."""
    return RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
        documents_bucket_name=EXPECTED_BUCKET,
        upload_url_expiration_seconds=900,
        processing_lease_duration_seconds=300,
        max_document_size_bytes=65_536,
    )


def install_fake_settings(
    monkeypatch: pytest.MonkeyPatch,
    settings: RuntimeSettings,
) -> list[RuntimeSettings]:
    """Replace RuntimeSettings.from_environment without mutating os.environ."""
    settings_loads: list[RuntimeSettings] = []

    class FakeRuntimeSettings:
        """Settings loader double that returns configured settings."""

        @classmethod
        def from_environment(cls) -> RuntimeSettings:
            """Return the configured runtime settings."""
            settings_loads.append(settings)
            return settings

    monkeypatch.setattr(
        handler_module,
        "RuntimeSettings",
        FakeRuntimeSettings,
    )

    return settings_loads


def install_recording_builder(
    monkeypatch: pytest.MonkeyPatch,
    *,
    processor: "RecordingDeadLetteredDocumentProcessor",
    raise_error: Exception | None = None,
) -> tuple[list[RuntimeSettings], list[object]]:
    """Monkeypatch the processor builder and record composition arguments."""
    recorded_settings: list[RuntimeSettings] = []
    recorded_loggers: list[object] = []

    def fake_build_dead_lettered_document_processor(
        *,
        settings: RuntimeSettings,
        operational_logger: object = None,
    ) -> RecordingDeadLetteredDocumentProcessor:
        """Match the handler's composition call contract."""
        recorded_settings.append(settings)
        recorded_loggers.append(operational_logger)

        if raise_error is not None:
            raise raise_error

        return processor

    monkeypatch.setattr(
        handler_module,
        "build_dead_lettered_document_processor",
        fake_build_dead_lettered_document_processor,
    )

    return recorded_settings, recorded_loggers


class RecordingDeadLetteredDocumentProcessor:
    """Processor double that records normalized DLQ events."""

    def __init__(
        self,
        *,
        failing_job_ids: set[str] | None = None,
        unexpected_job_ids: set[str] | None = None,
    ) -> None:
        """Initialize deterministic processor behavior."""
        self._failing_job_ids = failing_job_ids or set()
        self._unexpected_job_ids = unexpected_job_ids or set()
        self.events: list[UploadedDocumentEvent] = []

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Record or fail one normalized dead-lettered event."""
        self.events.append(event)

        if event.job_id in self._failing_job_ids:
            raise DeadLetteredDocumentProcessingError(
                f"temporary reconciliation failure for {event.job_id}"
            )

        if event.job_id in self._unexpected_job_ids:
            raise RuntimeError(f"unexpected reconciliation failure for {event.job_id}")


def make_s3_record(
    *,
    job_id: str = "job-001",
    bucket_name: str = EXPECTED_BUCKET,
    event_name: str = "ObjectCreated:Put",
    object_size: object = 128,
) -> dict[str, object]:
    """Create one deterministic S3 notification record."""
    return {
        "eventName": event_name,
        "s3": {
            "bucket": {
                "name": bucket_name,
            },
            "object": {
                "key": (f"documents%2F{job_id}%2Fsource.txt"),
                "size": object_size,
                "eTag": f"etag-{job_id}",
                "sequencer": f"sequencer-{job_id}",
            },
        },
    }


def make_queue_record(
    *,
    message_id: str = "dlq-message-001",
    s3_records: list[object] | None = None,
    body: object | None = None,
) -> dict[str, object]:
    """Create one deterministic DLQ SQS record."""
    resolved_body = (
        json.dumps(
            {
                "Records": (
                    s3_records
                    or [
                        make_s3_record(),
                    ]
                ),
            }
        )
        if body is None
        else body
    )

    return {
        "messageId": message_id,
        "body": resolved_body,
    }


def make_event(
    *queue_records: object,
) -> dict[str, object]:
    """Create one outer Lambda SQS event."""
    return {
        "Records": list(queue_records),
    }


def invoke(
    event: object,
    *,
    processor: (RecordingDeadLetteredDocumentProcessor | None) = None,
    logger: object | None = None,
    timer: object | None = None,
) -> tuple[
    dict[str, list[dict[str, str]]],
    RecordingDeadLetteredDocumentProcessor,
]:
    """Invoke the testable reconciliation handler."""
    resolved_processor = processor or RecordingDeadLetteredDocumentProcessor()
    kwargs: dict[str, object] = {
        "processor": resolved_processor,
        "expected_bucket_name": EXPECTED_BUCKET,
    }
    if logger is not None:
        kwargs["logger"] = logger
    if timer is not None:
        kwargs["timer"] = timer

    response = handle(
        event,
        None,
        **kwargs,
    )

    return response, resolved_processor


def test_returns_empty_partial_failure_response_for_empty_batch() -> None:
    """An empty DLQ batch should complete without failures."""
    response, processor = invoke(
        make_event(),
    )

    assert response == {
        "batchItemFailures": [],
    }
    assert processor.events == []


def test_reconciles_one_successful_dlq_message() -> None:
    """One valid DLQ message should be acknowledged."""
    response, processor = invoke(
        make_event(
            make_queue_record(),
        )
    )

    assert response == {
        "batchItemFailures": [],
    }
    assert len(processor.events) == 1

    normalized_event = processor.events[0]

    assert normalized_event.message_id == "dlq-message-001"
    assert normalized_event.job_id == "job-001"
    assert normalized_event.bucket_name == EXPECTED_BUCKET
    assert normalized_event.object_key == "documents/job-001/source.txt"


def test_reconciles_multiple_messages_in_input_order() -> None:
    """Valid DLQ records should preserve outer batch order."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    ),
                ],
            ),
        )
    )

    assert response == {
        "batchItemFailures": [],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]


def test_reconciles_multiple_s3_records_in_one_dlq_message() -> None:
    """One exhausted queue message may contain multiple events."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                    make_s3_record(
                        job_id="job-002",
                    ),
                ],
            )
        )
    )

    assert response == {
        "batchItemFailures": [],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]
    assert {event.message_id for event in processor.events} == {
        "dlq-message-001",
    }


def test_isolates_malformed_dlq_message() -> None:
    """One malformed message should not fail valid siblings."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                body="not-json",
            ),
            make_queue_record(
                message_id="dlq-message-003",
                s3_records=[
                    make_s3_record(
                        job_id="job-003",
                    ),
                ],
            ),
        )
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "dlq-message-002",
            },
        ],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-003",
    ]


def test_isolates_retryable_processor_failure() -> None:
    """One reconciliation failure should retry only its message."""
    processor = RecordingDeadLetteredDocumentProcessor(
        failing_job_ids={
            "job-002",
        },
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-003",
                s3_records=[
                    make_s3_record(
                        job_id="job-003",
                    ),
                ],
            ),
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "dlq-message-002",
            },
        ],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
        "job-003",
    ]


def test_isolates_unexpected_processor_failure() -> None:
    """Unexpected defects should remain isolated per DLQ message."""
    processor = RecordingDeadLetteredDocumentProcessor(
        unexpected_job_ids={
            "job-002",
        },
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-003",
                s3_records=[
                    make_s3_record(
                        job_id="job-003",
                    ),
                ],
            ),
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "dlq-message-002",
            },
        ],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
        "job-003",
    ]


def test_stops_remaining_events_in_failed_dlq_message() -> None:
    """Processing should stop after one event fails in a message."""
    processor = RecordingDeadLetteredDocumentProcessor(
        failing_job_ids={
            "job-002",
        },
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                    make_s3_record(
                        job_id="job-002",
                    ),
                    make_s3_record(
                        job_id="job-003",
                    ),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-004",
                    ),
                ],
            ),
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "dlq-message-001",
            },
        ],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
        "job-004",
    ]


def test_rejects_unexpected_source_bucket_per_message() -> None:
    """A source-bucket mismatch should remain retryable."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        bucket_name="unexpected-bucket",
                    ),
                ],
            )
        )
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "dlq-message-001",
            },
        ],
    }
    assert processor.events == []


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "invalid",
        42,
        {},
        {
            "Records": None,
        },
        {
            "Records": {},
        },
    ],
)
def test_rejects_malformed_outer_queue_event(
    event: object,
) -> None:
    """The outer invocation must contain a list of records."""
    with pytest.raises(
        MalformedQueueEventError,
    ):
        invoke(
            event,
        )


@pytest.mark.parametrize(
    "queue_record",
    [
        None,
        [],
        "invalid",
        {},
        {
            "messageId": None,
            "body": "{}",
        },
        {
            "messageId": "",
            "body": "{}",
        },
        {
            "messageId": "   ",
            "body": "{}",
        },
    ],
)
def test_rejects_record_without_reportable_message_id(
    queue_record: object,
) -> None:
    """A record without an ID cannot enter partial failures."""
    with pytest.raises(
        MalformedQueueMessageError,
    ):
        invoke(
            make_event(
                queue_record,
            )
        )


def test_lambda_handler_propagates_settings_to_processor_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lambda entrypoint should load settings and pass them to composition."""
    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    settings = make_runtime_settings()
    processor = RecordingDeadLetteredDocumentProcessor()
    recorded_settings, _recorded_loggers = install_recording_builder(
        monkeypatch,
        processor=processor,
    )
    settings_loads = install_fake_settings(monkeypatch, settings)

    response = handler_module.lambda_handler(
        make_event(
            make_queue_record(),
        ),
        None,
    )

    assert settings_loads == [settings]
    assert recorded_settings == [settings]
    assert response == {
        "batchItemFailures": [],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
    ]
    assert len(processor.events) == 1
    assert settings.documents_bucket_name == EXPECTED_BUCKET
    assert handler_module._PROCESSOR is processor


def test_lambda_handler_caches_composed_processor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm invocations should reuse the cached processor composition."""
    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    settings = make_runtime_settings()
    processor = RecordingDeadLetteredDocumentProcessor()
    recorded_settings, _recorded_loggers = install_recording_builder(
        monkeypatch,
        processor=processor,
    )
    settings_loads = install_fake_settings(monkeypatch, settings)

    first_response = handler_module.lambda_handler(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    )
                ],
            )
        ),
        None,
    )
    second_response = handler_module.lambda_handler(
        make_event(
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    )
                ],
            )
        ),
        None,
    )

    assert settings_loads == [settings, settings]
    assert recorded_settings == [settings]
    assert first_response == {
        "batchItemFailures": [],
    }
    assert second_response == {
        "batchItemFailures": [],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]
    assert handler_module._PROCESSOR is processor


def test_lambda_handler_propagates_expected_bucket_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lambda entrypoint should pass documents_bucket_name into handle(...)."""
    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    matching_settings = make_runtime_settings()
    processor = RecordingDeadLetteredDocumentProcessor()
    install_recording_builder(
        monkeypatch,
        processor=processor,
    )
    install_fake_settings(monkeypatch, matching_settings)

    matching_response = handler_module.lambda_handler(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
            )
        ),
        None,
    )

    assert matching_response == {
        "batchItemFailures": [],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
    ]

    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    mismatched_settings = RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
        documents_bucket_name="other-documents-bucket",
        upload_url_expiration_seconds=900,
        processing_lease_duration_seconds=300,
        max_document_size_bytes=65_536,
    )
    mismatched_processor = RecordingDeadLetteredDocumentProcessor()
    install_recording_builder(
        monkeypatch,
        processor=mismatched_processor,
    )
    install_fake_settings(monkeypatch, mismatched_settings)

    mismatched_response = handler_module.lambda_handler(
        make_event(
            make_queue_record(
                message_id="dlq-message-002",
            )
        ),
        None,
    )

    assert mismatched_response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "dlq-message-002",
            }
        ],
    }
    assert mismatched_processor.events == []


def test_lambda_handler_builder_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cold-start composition failures must fail the entire invocation."""
    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    settings = make_runtime_settings()
    install_recording_builder(
        monkeypatch,
        processor=RecordingDeadLetteredDocumentProcessor(),
        raise_error=RuntimeError("processor composition failed"),
    )
    install_fake_settings(monkeypatch, settings)

    with pytest.raises(
        RuntimeError,
        match="processor composition failed",
    ):
        handler_module.lambda_handler(
            make_event(
                make_queue_record(),
            ),
            None,
        )

    assert handler_module._PROCESSOR is None


def test_successful_batch_emits_one_info_batch_event() -> None:
    """Successful DLQ processing should emit only one handler batch event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.0, 10.125)

    response, _ = invoke(
        make_event(make_queue_record()),
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": []}
    assert events_by_name(logger, "reconciliation.record_completed") == []
    assert events_by_name(logger, "reconciliation.record_failed") == []

    batch_events = events_by_name(logger, "reconciliation.batch_completed")

    assert len(batch_events) == 1
    assert batch_events[0].level == "info"
    assert batch_events[0].fields == {
        "operation": "reconcile_dead_letter_batch",
        "outcome": "succeeded",
        "batch_size": 1,
        "processed_record_count": 1,
        "failed_record_count": 0,
        "duration_ms": 125.0,
    }
    assert_fields_exclude_sensitive_content(batch_events[0].fields)


def test_malformed_sqs_body_emits_record_and_batch_failure_events() -> None:
    """Malformed SQS bodies should emit one record failure and one batch event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.0, 10.050, 10.125)

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                body="not-json",
            )
        ),
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": [{"itemIdentifier": "dlq-message-001"}]}
    assert processor.events == []

    failed_events = events_by_name(logger, "reconciliation.record_failed")
    batch_events = events_by_name(logger, "reconciliation.batch_completed")

    assert len(failed_events) == 1
    assert failed_events[0].level == "warning"
    assert failed_events[0].fields["operation"] == ("reconcile_dead_lettered_document")
    assert failed_events[0].fields["outcome"] == "event_rejected"
    assert failed_events[0].fields["error_code"] == ("dead_letter_event_parsing_error")
    assert failed_events[0].fields["exception_type"] == ("MalformedQueueMessageError")
    assert failed_events[0].fields["retryable"] is True
    assert failed_events[0].fields["sqs_message_id"] == "dlq-message-001"
    assert "job_id" not in failed_events[0].fields

    assert len(batch_events) == 1
    assert batch_events[0].level == "warning"
    assert batch_events[0].fields["outcome"] == "completed_with_failures"
    assert_fields_exclude_sensitive_content(failed_events[0].fields)
    assert_fields_exclude_sensitive_content(batch_events[0].fields)


def test_processor_error_emits_retryable_record_failure() -> None:
    """DeadLetteredDocumentProcessingError should emit one safe error event."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.0, 10.050, 10.125)
    processor = RecordingDeadLetteredDocumentProcessor(
        failing_job_ids={"job-001"},
    )

    response, _ = invoke(
        make_event(make_queue_record()),
        processor=processor,
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": [{"itemIdentifier": "dlq-message-001"}]}

    failed_events = events_by_name(logger, "reconciliation.record_failed")

    assert len(failed_events) == 1
    assert failed_events[0].level == "error"
    assert failed_events[0].fields == {
        "operation": "reconcile_dead_lettered_document",
        "outcome": "retryable_failure",
        "error_code": "dead_lettered_document_processing_error",
        "exception_type": "DeadLetteredDocumentProcessingError",
        "retryable": True,
        "sqs_message_id": "dlq-message-001",
        "job_id": "job-001",
        "duration_ms": 50.0,
    }
    assert_fields_exclude_sensitive_content(failed_events[0].fields)


def test_unexpected_processor_failure_emits_normalized_error_telemetry() -> None:
    """Unexpected reconciliation failures should omit exception message content."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.0, 10.050, 10.125)
    processor = RecordingDeadLetteredDocumentProcessor(
        unexpected_job_ids={"job-001"},
    )

    response, _ = invoke(
        make_event(make_queue_record()),
        processor=processor,
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": [{"itemIdentifier": "dlq-message-001"}]}

    failed_events = events_by_name(logger, "reconciliation.record_failed")

    assert len(failed_events) == 1
    assert failed_events[0].fields == {
        "operation": "reconcile_dead_lettered_document",
        "outcome": "retryable_failure",
        "error_code": "unexpected_reconciliation_error",
        "exception_type": "RuntimeError",
        "retryable": True,
        "sqs_message_id": "dlq-message-001",
        "job_id": "job-001",
        "duration_ms": 50.0,
    }
    assert_fields_exclude_sensitive_content(failed_events[0].fields)


def test_multiple_failed_events_in_one_message_emit_one_handler_failure() -> None:
    """Processing stops at the first failed event inside one DLQ message."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.0, 10.050, 10.040, 10.125)
    processor = RecordingDeadLetteredDocumentProcessor(
        failing_job_ids={"job-002"},
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[
                    make_s3_record(job_id="job-001"),
                    make_s3_record(job_id="job-002"),
                    make_s3_record(job_id="job-003"),
                ],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[make_s3_record(job_id="job-004")],
            ),
        ),
        processor=processor,
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": [{"itemIdentifier": "dlq-message-001"}]}
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
        "job-004",
    ]
    assert len(events_by_name(logger, "reconciliation.record_failed")) == 1
    assert len(events_by_name(logger, "reconciliation.batch_completed")) == 1


def test_later_valid_messages_still_process_after_failed_message() -> None:
    """One failed DLQ message should not stop later valid messages."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.0, 10.020, 10.040, 10.125)
    processor = RecordingDeadLetteredDocumentProcessor(
        failing_job_ids={"job-001"},
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[make_s3_record(job_id="job-001")],
            ),
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[make_s3_record(job_id="job-002")],
            ),
        ),
        processor=processor,
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": [{"itemIdentifier": "dlq-message-001"}]}
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]
    batch_events = events_by_name(logger, "reconciliation.batch_completed")
    assert len(batch_events) == 1
    assert batch_events[0].fields["processed_record_count"] == 1
    assert batch_events[0].fields["failed_record_count"] == 1


def test_empty_batch_emits_one_successful_batch_event() -> None:
    """An empty DLQ batch should emit one successful batch summary."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    response, processor = invoke(
        make_event(),
        logger=logger,
        timer=timer,
    )

    assert response == {"batchItemFailures": []}
    assert processor.events == []

    batch_events = events_by_name(logger, "reconciliation.batch_completed")

    assert len(batch_events) == 1
    assert batch_events[0].fields == {
        "operation": "reconcile_dead_letter_batch",
        "outcome": "succeeded",
        "batch_size": 0,
        "processed_record_count": 0,
        "failed_record_count": 0,
        "duration_ms": 125.0,
    }


def test_malformed_outer_event_emits_error_batch_and_reraises() -> None:
    """Malformed outer events remain invocation failures after telemetry."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    with pytest.raises(MalformedQueueEventError):
        invoke(
            {"Records": None},
            logger=logger,
            timer=timer,
        )

    batch_events = events_by_name(logger, "reconciliation.batch_completed")

    assert len(batch_events) == 1
    assert batch_events[0].level == "error"
    assert batch_events[0].fields["error_code"] == "malformed_queue_event"
    assert "batch_size" not in batch_events[0].fields
    assert events_by_name(logger, "reconciliation.record_failed") == []


def test_record_without_message_id_emits_error_batch_and_reraises() -> None:
    """Unreportable message IDs remain invocation failures after telemetry."""
    logger = RecordingOperationalLogger()
    timer = SequenceTimer(10.0, 10.125)

    with pytest.raises(MalformedQueueMessageError):
        invoke(
            make_event({"body": "{}"}),
            logger=logger,
            timer=timer,
        )

    batch_events = events_by_name(logger, "reconciliation.batch_completed")

    assert len(batch_events) == 1
    assert batch_events[0].fields["error_code"] == "malformed_queue_message"
    assert events_by_name(logger, "reconciliation.record_failed") == []


def test_raising_logger_does_not_change_successful_response() -> None:
    """Logger failures must not alter a successful partial-batch response."""
    response, _ = invoke(
        make_event(make_queue_record()),
        logger=RaisingOperationalLogger(),
        timer=SequenceTimer(10.0, 10.0, 10.125),
    )

    assert response == {"batchItemFailures": []}


def test_raising_logger_does_not_change_partial_failure_response() -> None:
    """Logger failures must not alter partial-failure response content."""
    response, _ = invoke(
        make_event(make_queue_record(body="not-json")),
        logger=RaisingOperationalLogger(),
        timer=SequenceTimer(10.0, 10.0, 10.050, 10.125),
    )

    assert response == {"batchItemFailures": [{"itemIdentifier": "dlq-message-001"}]}


def test_raising_logger_does_not_change_malformed_event_propagation() -> None:
    """Logger failures must not swallow malformed-event exceptions."""
    with pytest.raises(MalformedQueueEventError):
        invoke(
            {"Records": None},
            logger=RaisingOperationalLogger(),
            timer=SequenceTimer(10.0, 10.125),
        )


def test_lambda_handler_passes_module_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production entrypoint should wire the module logger to builder and handle."""
    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    settings = make_runtime_settings()
    processor = RecordingDeadLetteredDocumentProcessor()
    recorded_settings, recorded_loggers = install_recording_builder(
        monkeypatch,
        processor=processor,
    )
    install_fake_settings(monkeypatch, settings)

    module_logger = RecordingOperationalLogger()
    monkeypatch.setattr(handler_module, "_LOGGER", module_logger)

    response = handler_module.lambda_handler(
        make_event(make_queue_record()),
        None,
    )

    assert response == {"batchItemFailures": []}
    assert recorded_settings == [settings]
    assert recorded_loggers == [module_logger]
    assert len(events_by_name(module_logger, "reconciliation.batch_completed")) == 1
    assert handler_module._PROCESSOR is processor


def test_warm_invocation_processor_caching_remains_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warm invocations should keep one cached processor despite logger wiring."""
    monkeypatch.setattr(handler_module, "_PROCESSOR", None)

    settings = make_runtime_settings()
    processor = RecordingDeadLetteredDocumentProcessor()
    recorded_settings, recorded_loggers = install_recording_builder(
        monkeypatch,
        processor=processor,
    )
    install_fake_settings(monkeypatch, settings)
    monkeypatch.setattr(
        handler_module,
        "_LOGGER",
        RecordingOperationalLogger(),
    )

    handler_module.lambda_handler(
        make_event(
            make_queue_record(
                message_id="dlq-message-001",
                s3_records=[make_s3_record(job_id="job-001")],
            )
        ),
        None,
    )
    handler_module.lambda_handler(
        make_event(
            make_queue_record(
                message_id="dlq-message-002",
                s3_records=[make_s3_record(job_id="job-002")],
            )
        ),
        None,
    )

    assert recorded_settings == [settings]
    assert len(recorded_loggers) == 1
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]
    assert handler_module._PROCESSOR is processor
