"""Tests for the Processor Lambda partial-batch handler."""

import json

import pytest

from clouddoc.application.processing_ports import (
    UploadedDocumentProcessingError,
)
from clouddoc.delivery.events.errors import (
    MalformedQueueEventError,
    MalformedQueueMessageError,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.handlers.process_uploaded_document import handle

EXPECTED_BUCKET = "clouddoc-documents"


class RecordingProcessor:
    """Processor double that records normalized events."""

    def __init__(
        self,
        *,
        failing_job_ids: set[str] | None = None,
        unexpected_job_ids: set[str] | None = None,
    ) -> None:
        """Initialize deterministic processor behavior."""
        self.failing_job_ids = failing_job_ids or set()
        self.unexpected_job_ids = unexpected_job_ids or set()
        self.events: list[UploadedDocumentEvent] = []

    def process(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> None:
        """Record or fail one uploaded-document event."""
        self.events.append(event)

        if event.job_id in self.failing_job_ids:
            raise UploadedDocumentProcessingError(
                f"temporary failure for {event.job_id}"
            )

        if event.job_id in self.unexpected_job_ids:
            raise RuntimeError(f"unexpected failure for {event.job_id}")


def make_s3_record(
    *,
    job_id: str = "job-001",
    bucket_name: str = EXPECTED_BUCKET,
    event_name: str = "ObjectCreated:Put",
    object_size: object = 128,
) -> dict[str, object]:
    """Create one S3 notification record."""
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
    message_id: str = "message-001",
    s3_records: list[object] | None = None,
    body: object | None = None,
) -> dict[str, object]:
    """Create one SQS record."""
    resolved_body = (
        json.dumps(
            {
                "Records": s3_records
                or [
                    make_s3_record(),
                ]
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
    """Create an outer Lambda SQS event."""
    return {
        "Records": list(queue_records),
    }


def invoke(
    event: object,
    *,
    processor: RecordingProcessor | None = None,
) -> tuple[
    dict[str, list[dict[str, str]]],
    RecordingProcessor,
]:
    """Invoke the testable handler."""
    resolved_processor = processor or RecordingProcessor()

    response = handle(
        event,
        None,
        processor=resolved_processor,
        expected_bucket_name=EXPECTED_BUCKET,
    )

    return response, resolved_processor


def test_returns_empty_partial_failure_response_for_empty_batch() -> None:
    """An empty SQS batch should complete without failures."""
    response, processor = invoke(
        make_event(),
    )

    assert response == {
        "batchItemFailures": [],
    }
    assert processor.events == []


def test_processes_one_successful_sqs_message() -> None:
    """One valid message should be acknowledged."""
    response, processor = invoke(
        make_event(
            make_queue_record(),
        )
    )

    assert response == {
        "batchItemFailures": [],
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
    ]


def test_processes_multiple_successful_messages_in_order() -> None:
    """Successful queue records should preserve input order."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    )
                ],
            ),
            make_queue_record(
                message_id="message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    )
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


def test_processes_multiple_s3_records_in_one_message() -> None:
    """One queue message may fan out to multiple normalized events."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="message-001",
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
        "message-001",
    }


def test_returns_only_malformed_message_as_failure() -> None:
    """A malformed message should not fail valid siblings."""
    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    )
                ],
            ),
            make_queue_record(
                message_id="message-002",
                body="not-json",
            ),
            make_queue_record(
                message_id="message-003",
                s3_records=[
                    make_s3_record(
                        job_id="job-003",
                    )
                ],
            ),
        )
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "message-002",
            }
        ]
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-003",
    ]


def test_returns_only_processor_failure() -> None:
    """A retryable processor failure should isolate one message."""
    processor = RecordingProcessor(
        failing_job_ids={
            "job-002",
        }
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    )
                ],
            ),
            make_queue_record(
                message_id="message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    )
                ],
            ),
            make_queue_record(
                message_id="message-003",
                s3_records=[
                    make_s3_record(
                        job_id="job-003",
                    )
                ],
            ),
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "message-002",
            }
        ]
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
        "job-003",
    ]


def test_stops_processing_remaining_records_in_failed_message() -> None:
    """Processing should stop after one event fails in a message."""
    processor = RecordingProcessor(
        failing_job_ids={
            "job-002",
        }
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="message-001",
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
            )
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "message-001",
            }
        ]
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]


def test_unexpected_exception_becomes_message_failure() -> None:
    """Unexpected failures should remain inside the Lambda boundary."""
    processor = RecordingProcessor(
        unexpected_job_ids={
            "job-001",
        }
    )

    response, _ = invoke(
        make_event(
            make_queue_record(),
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "message-001",
            }
        ]
    }


def test_returns_each_failed_message_identifier_once() -> None:
    """Partial failure output should not duplicate identifiers."""
    processor = RecordingProcessor(
        failing_job_ids={
            "job-001",
            "job-002",
        }
    )

    response, _ = invoke(
        make_event(
            make_queue_record(
                message_id="message-shared",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    ),
                    make_s3_record(
                        job_id="job-002",
                    ),
                ],
            )
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "message-shared",
            }
        ]
    }


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "event",
        123,
        {},
        {
            "Records": None,
        },
        {
            "Records": {},
        },
    ],
)
def test_malformed_outer_event_raises(
    event: object,
) -> None:
    """A malformed outer envelope cannot produce partial failures."""
    with pytest.raises(MalformedQueueEventError):
        invoke(event)


@pytest.mark.parametrize(
    "queue_record",
    [
        None,
        [],
        "record",
        123,
        {},
        {
            "body": "{}",
        },
        {
            "messageId": "",
            "body": "{}",
        },
    ],
)
def test_missing_message_identity_raises(
    queue_record: object,
) -> None:
    """A record without messageId cannot be reported partially."""
    with pytest.raises(MalformedQueueMessageError):
        invoke(
            make_event(
                queue_record,
            )
        )


def test_valid_messages_after_failed_message_are_processed() -> None:
    """One failed message should not stop the remaining batch."""
    processor = RecordingProcessor(
        failing_job_ids={
            "job-001",
        }
    )

    response, processor = invoke(
        make_event(
            make_queue_record(
                message_id="message-001",
                s3_records=[
                    make_s3_record(
                        job_id="job-001",
                    )
                ],
            ),
            make_queue_record(
                message_id="message-002",
                s3_records=[
                    make_s3_record(
                        job_id="job-002",
                    )
                ],
            ),
        ),
        processor=processor,
    )

    assert response == {
        "batchItemFailures": [
            {
                "itemIdentifier": "message-001",
            }
        ]
    }
    assert [event.job_id for event in processor.events] == [
        "job-001",
        "job-002",
    ]
