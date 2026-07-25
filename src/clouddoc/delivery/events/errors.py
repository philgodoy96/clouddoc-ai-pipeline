"""Errors raised while parsing asynchronous delivery events."""


class EventParsingError(Exception):
    """Base error for deterministic event-payload failures."""


class MalformedQueueEventError(EventParsingError):
    """Raised when the outer Lambda SQS event is malformed."""


class MalformedQueueMessageError(EventParsingError):
    """Raised when an individual SQS record is malformed."""


class MalformedS3NotificationError(EventParsingError):
    """Raised when an SQS message does not contain a valid S3 notification."""


class UnsupportedS3EventError(EventParsingError):
    """Raised when an S3 notification is not an ObjectCreated event."""


class UnexpectedS3BucketError(EventParsingError):
    """Raised when an S3 event references an unexpected bucket."""


class InvalidDocumentObjectKeyError(EventParsingError):
    """Raised when an S3 object key is not a canonical document key."""
