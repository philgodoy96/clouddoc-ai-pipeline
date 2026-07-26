"""Tests for the DLQ reconciliation partial-batch handler."""

import json

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
) -> list[RuntimeSettings]:
    """Monkeypatch the processor builder and record settings arguments."""
    recorded_settings: list[RuntimeSettings] = []

    def fake_build_dead_lettered_document_processor(
        *,
        settings: RuntimeSettings,
    ) -> RecordingDeadLetteredDocumentProcessor:
        """Match the handler's settings-only builder call contract."""
        recorded_settings.append(settings)

        if raise_error is not None:
            raise raise_error

        return processor

    monkeypatch.setattr(
        handler_module,
        "build_dead_lettered_document_processor",
        fake_build_dead_lettered_document_processor,
    )

    return recorded_settings


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
) -> tuple[
    dict[str, list[dict[str, str]]],
    RecordingDeadLetteredDocumentProcessor,
]:
    """Invoke the testable reconciliation handler."""
    resolved_processor = processor or RecordingDeadLetteredDocumentProcessor()

    response = handle(
        event,
        None,
        processor=resolved_processor,
        expected_bucket_name=EXPECTED_BUCKET,
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
    recorded_settings = install_recording_builder(
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
    recorded_settings = install_recording_builder(
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
