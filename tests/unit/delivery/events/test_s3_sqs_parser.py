"""Tests for parsing SQS-wrapped S3 notifications."""

import json

import pytest

from clouddoc.delivery.events.errors import (
    InvalidDocumentObjectKeyError,
    MalformedQueueEventError,
    MalformedQueueMessageError,
    MalformedS3NotificationError,
    UnexpectedS3BucketError,
    UnsupportedS3EventError,
)
from clouddoc.delivery.events.s3_sqs_parser import (
    parse_sqs_record_with_s3_notification,
    parse_sqs_wrapped_s3_event,
)

EXPECTED_BUCKET = "clouddoc-documents"


def make_s3_record(
    *,
    event_name: object = "ObjectCreated:Put",
    bucket_name: object = EXPECTED_BUCKET,
    object_key: object = ("documents%2Fjob-001%2Fsource.txt"),
    object_size: object = 128,
    etag: object = "etag-001",
    sequencer: object = "0055AED6DCD90281E5",
    version_id: object = None,
) -> dict[str, object]:
    """Create one serialized S3 notification record."""
    object_data: dict[str, object] = {
        "key": object_key,
        "size": object_size,
    }

    if etag is not None:
        object_data["eTag"] = etag

    if sequencer is not None:
        object_data["sequencer"] = sequencer

    if version_id is not None:
        object_data["versionId"] = version_id

    return {
        "eventName": event_name,
        "s3": {
            "bucket": {
                "name": bucket_name,
            },
            "object": object_data,
        },
    }


def make_queue_record(
    *,
    message_id: object = "message-001",
    s3_records: list[object] | None = None,
    body: object | None = None,
) -> dict[str, object]:
    """Create one SQS record containing an S3 notification."""
    serialized_body = (
        json.dumps({"Records": s3_records or [make_s3_record()]})
        if body is None
        else body
    )

    return {
        "messageId": message_id,
        "body": serialized_body,
    }


def make_event(
    *queue_records: object,
) -> dict[str, object]:
    """Create a Lambda SQS event."""
    return {
        "Records": list(queue_records)
        or [
            make_queue_record(),
        ]
    }


def parse(
    event: object,
):
    """Parse with the configured expected bucket."""
    return parse_sqs_wrapped_s3_event(
        event,
        expected_bucket_name=EXPECTED_BUCKET,
    )


def parse_record(
    queue_record: object,
):
    """Parse one queue record with the configured expected bucket."""
    return parse_sqs_record_with_s3_notification(
        queue_record,
        expected_bucket_name=EXPECTED_BUCKET,
    )


def test_parses_one_queue_record_with_one_s3_record() -> None:
    """A valid wrapped notification should become one event."""
    events = parse(
        make_event(),
    )

    assert len(events) == 1

    event = events[0]

    assert event.message_id == "message-001"
    assert event.event_name == "ObjectCreated:Put"
    assert event.bucket_name == EXPECTED_BUCKET
    assert event.object_key == "documents/job-001/source.txt"
    assert event.job_id == "job-001"
    assert event.object_size == 128
    assert event.etag == "etag-001"
    assert event.sequencer == "0055AED6DCD90281E5"
    assert event.version_id is None


def test_parses_multiple_queue_records_in_order() -> None:
    """Queue-batch ordering should be preserved."""
    events = parse(
        make_event(
            make_queue_record(
                message_id="message-001",
                s3_records=[
                    make_s3_record(object_key=("documents%2Fjob-001%2Fsource.txt"))
                ],
            ),
            make_queue_record(
                message_id="message-002",
                s3_records=[
                    make_s3_record(object_key=("documents%2Fjob-002%2Fsource.txt"))
                ],
            ),
        )
    )

    assert [event.message_id for event in events] == [
        "message-001",
        "message-002",
    ]
    assert [event.job_id for event in events] == [
        "job-001",
        "job-002",
    ]


def test_parses_multiple_s3_records_inside_one_message() -> None:
    """One SQS body may contain multiple S3 records."""
    events = parse(
        make_event(
            make_queue_record(
                s3_records=[
                    make_s3_record(object_key=("documents%2Fjob-001%2Fsource.txt")),
                    make_s3_record(object_key=("documents%2Fjob-002%2Fsource.txt")),
                ]
            )
        )
    )

    assert [event.job_id for event in events] == [
        "job-001",
        "job-002",
    ]
    assert all(event.message_id == "message-001" for event in events)


def test_decodes_plus_sign_before_key_validation() -> None:
    """S3 plus encoding should be decoded before validation."""
    with pytest.raises(InvalidDocumentObjectKeyError):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        make_s3_record(object_key=("documents%2Fjob+001%2Fsource.txt"))
                    ]
                )
            )
        )


@pytest.mark.parametrize(
    "event_name",
    [
        "ObjectCreated:Put",
        "ObjectCreated:Post",
        "ObjectCreated:Copy",
        "ObjectCreated:CompleteMultipartUpload",
    ],
)
def test_accepts_object_created_event_family(
    event_name: str,
) -> None:
    """All concrete ObjectCreated subtypes are supported."""
    events = parse(
        make_event(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        event_name=event_name,
                    )
                ]
            )
        )
    )

    assert events[0].event_name == event_name


@pytest.mark.parametrize(
    "event_name",
    [
        "ObjectRemoved:Delete",
        "ObjectRestore:Completed",
        "ReducedRedundancyLostObject",
    ],
)
def test_rejects_unsupported_s3_event(
    event_name: str,
) -> None:
    """Non-creation notifications should not enter processing."""
    with pytest.raises(
        UnsupportedS3EventError,
        match="unsupported S3 event",
    ):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        make_s3_record(
                            event_name=event_name,
                        )
                    ]
                )
            )
        )


def test_rejects_unexpected_bucket() -> None:
    """The parser should enforce the configured source bucket."""
    with pytest.raises(
        UnexpectedS3BucketError,
        match="unexpected S3 bucket",
    ):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        make_s3_record(
                            bucket_name="other-bucket",
                        )
                    ]
                )
            )
        )


@pytest.mark.parametrize(
    "object_key",
    [
        "documents%2Fjob-001%2Fother.txt",
        "documents%2Fjob-001%2Fsource.pdf",
        "uploads%2Fjob-001%2Fsource.txt",
        "documents%2Fsource.txt",
        "documents%2F%2Fsource.txt",
        "documents%2Fjob-001%2Fnested%2Fsource.txt",
    ],
)
def test_rejects_invalid_document_object_key(
    object_key: str,
) -> None:
    """Only canonical document source keys are accepted."""
    with pytest.raises(
        InvalidDocumentObjectKeyError,
        match="invalid canonical document object key",
    ):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        make_s3_record(
                            object_key=object_key,
                        )
                    ]
                )
            )
        )


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
        {
            "Records": [],
        },
    ],
)
def test_rejects_malformed_outer_queue_event(
    event: object,
) -> None:
    """The Lambda SQS envelope must contain records."""
    with pytest.raises(MalformedQueueEventError):
        parse(event)


@pytest.mark.parametrize(
    "queue_record",
    [
        None,
        [],
        "record",
        123,
        {},
        {
            "messageId": "message-001",
        },
        {
            "body": "{}",
        },
        {
            "messageId": "",
            "body": "{}",
        },
        {
            "messageId": "message-001",
            "body": "",
        },
    ],
)
def test_rejects_malformed_queue_record(
    queue_record: object,
) -> None:
    """Each queue record requires message ID and JSON body."""
    with pytest.raises(MalformedQueueMessageError):
        parse(make_event(queue_record))


@pytest.mark.parametrize(
    "body",
    [
        "{",
        "not-json",
        "[]",
        "null",
        "{}",
        '{"Records": null}',
        '{"Records": {}}',
        '{"Records": []}',
    ],
)
def test_rejects_invalid_s3_notification_body(
    body: str,
) -> None:
    """Queue bodies must contain valid S3 notifications."""
    expected_error = (
        MalformedQueueMessageError
        if body in {"{", "not-json"}
        else MalformedS3NotificationError
    )

    with pytest.raises(expected_error):
        parse(
            make_event(
                make_queue_record(
                    body=body,
                )
            )
        )


@pytest.mark.parametrize(
    "s3_record",
    [
        None,
        [],
        "record",
        123,
        {},
        {
            "eventName": "ObjectCreated:Put",
        },
        {
            "eventName": "ObjectCreated:Put",
            "s3": None,
        },
    ],
)
def test_rejects_malformed_s3_record(
    s3_record: object,
) -> None:
    """Each S3 record must contain bucket and object data."""
    with pytest.raises(MalformedS3NotificationError):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        s3_record,
                    ]
                )
            )
        )


@pytest.mark.parametrize(
    "object_size",
    [
        -1,
        True,
        False,
        128.0,
        "128",
        None,
    ],
)
def test_rejects_invalid_object_size(
    object_size: object,
) -> None:
    """Object size must be a non-negative integer."""
    with pytest.raises(
        MalformedS3NotificationError,
        match="size must be a non-negative integer",
    ):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        make_s3_record(
                            object_size=object_size,
                        )
                    ]
                )
            )
        )


def test_accepts_zero_byte_object() -> None:
    """Transport parsing may represent an empty object."""
    events = parse(
        make_event(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        object_size=0,
                    )
                ]
            )
        )
    )

    assert events[0].object_size == 0


def test_accepts_optional_s3_metadata() -> None:
    """Optional metadata may be absent."""
    events = parse(
        make_event(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        etag=None,
                        sequencer=None,
                        version_id=None,
                    )
                ]
            )
        )
    )

    event = events[0]

    assert event.etag is None
    assert event.sequencer is None
    assert event.version_id is None


@pytest.mark.parametrize(
    "field_name",
    [
        "eTag",
        "sequencer",
        "versionId",
    ],
)
def test_rejects_blank_optional_metadata(
    field_name: str,
) -> None:
    """Present optional metadata must not be blank."""
    record = make_s3_record()
    object_data = record["s3"]["object"]
    object_data[field_name] = "   "

    with pytest.raises(MalformedS3NotificationError):
        parse(
            make_event(
                make_queue_record(
                    s3_records=[
                        record,
                    ]
                )
            )
        )


def test_rejects_blank_expected_bucket_name() -> None:
    """Parser configuration requires a bucket identity."""
    with pytest.raises(
        ValueError,
        match="expected_bucket_name must not be empty",
    ):
        parse_sqs_wrapped_s3_event(
            make_event(),
            expected_bucket_name="   ",
        )


def test_single_record_parses_one_s3_record() -> None:
    """A valid SQS record with one S3 record returns one event."""
    events = parse_record(make_queue_record())

    assert len(events) == 1

    event = events[0]

    assert event.message_id == "message-001"
    assert event.event_name == "ObjectCreated:Put"
    assert event.bucket_name == EXPECTED_BUCKET
    assert event.object_key == "documents/job-001/source.txt"
    assert event.job_id == "job-001"
    assert event.object_size == 128
    assert event.etag == "etag-001"
    assert event.sequencer == "0055AED6DCD90281E5"
    assert event.version_id is None


def test_single_record_parses_multiple_s3_records_in_order() -> None:
    """One SQS body may contain multiple S3 records."""
    events = parse_record(
        make_queue_record(
            s3_records=[
                make_s3_record(object_key=("documents%2Fjob-001%2Fsource.txt")),
                make_s3_record(object_key=("documents%2Fjob-002%2Fsource.txt")),
            ]
        )
    )

    assert [event.job_id for event in events] == [
        "job-001",
        "job-002",
    ]


def test_single_record_preserves_message_id_across_s3_records() -> None:
    """All S3 events from one SQS record share that message ID."""
    events = parse_record(
        make_queue_record(
            message_id="message-shared",
            s3_records=[
                make_s3_record(object_key=("documents%2Fjob-001%2Fsource.txt")),
                make_s3_record(object_key=("documents%2Fjob-002%2Fsource.txt")),
            ],
        )
    )

    assert all(event.message_id == "message-shared" for event in events)


@pytest.mark.parametrize(
    "queue_record",
    [
        None,
        [],
        "record",
        123,
        {},
        {
            "messageId": "message-001",
        },
        {
            "body": "{}",
        },
        {
            "messageId": "",
            "body": "{}",
        },
        {
            "messageId": "message-001",
            "body": "",
        },
        {
            "messageId": "message-001",
            "body": "{",
        },
        {
            "messageId": "message-001",
            "body": "not-json",
        },
    ],
)
def test_single_record_rejects_malformed_queue_record(
    queue_record: object,
) -> None:
    """Malformed SQS record structures raise MalformedQueueMessageError."""
    with pytest.raises(MalformedQueueMessageError):
        parse_record(queue_record)


def test_single_record_rejects_invalid_decoded_notification() -> None:
    """Valid SQS envelopes with invalid S3 notifications raise accordingly."""
    with pytest.raises(MalformedS3NotificationError):
        parse_record(
            make_queue_record(
                body="{}",
            )
        )


def test_single_record_rejects_blank_expected_bucket_name() -> None:
    """Single-record parser configuration requires a bucket identity."""
    with pytest.raises(
        ValueError,
        match="expected_bucket_name must not be empty",
    ):
        parse_sqs_record_with_s3_notification(
            make_queue_record(),
            expected_bucket_name="   ",
        )


def test_single_record_rejects_unsupported_s3_event() -> None:
    """Single-record parser preserves UnsupportedS3EventError."""
    with pytest.raises(
        UnsupportedS3EventError,
        match="unsupported S3 event",
    ):
        parse_record(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        event_name="ObjectRemoved:Delete",
                    )
                ]
            )
        )


def test_single_record_rejects_unexpected_bucket() -> None:
    """Single-record parser preserves UnexpectedS3BucketError."""
    with pytest.raises(
        UnexpectedS3BucketError,
        match="unexpected S3 bucket",
    ):
        parse_record(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        bucket_name="other-bucket",
                    )
                ]
            )
        )


def test_single_record_rejects_invalid_document_object_key() -> None:
    """Single-record parser preserves InvalidDocumentObjectKeyError."""
    with pytest.raises(
        InvalidDocumentObjectKeyError,
        match="invalid canonical document object key",
    ):
        parse_record(
            make_queue_record(
                s3_records=[
                    make_s3_record(
                        object_key="documents%2Fjob-001%2Fother.txt",
                    )
                ]
            )
        )


def test_batch_flattens_multiple_queue_records_in_input_order() -> None:
    """Batch parsing flattens SQS records while preserving input order."""
    events = parse(
        make_event(
            make_queue_record(
                message_id="message-001",
                s3_records=[
                    make_s3_record(object_key=("documents%2Fjob-001%2Fsource.txt")),
                    make_s3_record(object_key=("documents%2Fjob-002%2Fsource.txt")),
                ],
            ),
            make_queue_record(
                message_id="message-002",
                s3_records=[
                    make_s3_record(object_key=("documents%2Fjob-003%2Fsource.txt")),
                ],
            ),
        )
    )

    assert [event.message_id for event in events] == [
        "message-001",
        "message-001",
        "message-002",
    ]
    assert [event.job_id for event in events] == [
        "job-001",
        "job-002",
        "job-003",
    ]
