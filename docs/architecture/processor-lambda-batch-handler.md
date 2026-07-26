# Processor Lambda Batch Handler

## Purpose

CloudDoc processes SQS-triggered uploaded-document notifications through a Lambda handler that isolates failures at the individual SQS message level.

The handler is responsible for:

```text
reading the outer Lambda SQS event
processing each SQS record independently
parsing S3 notifications inside each message
invoking the uploaded-document processor once per normalized event
returning AWS partial batch failures
```

It does not perform:

```text
DynamoDB job lookup
job state transitions
S3 object download
content validation
AI inference
idempotency persistence
```

## Batch Flow

```text
Lambda SQS event
    ↓
extract outer Records
    ↓
for each SQS record
    ↓
extract messageId
    ↓
parse S3 notification records
    ↓
process normalized uploaded-document events
    ↓
record failed message IDs
    ↓
return batchItemFailures
```

## Success Response

When all messages succeed:

```json
{
  "batchItemFailures": []
}
```

## Partial Failure Response

When one message fails:

```json
{
  "batchItemFailures": [
    {
      "itemIdentifier": "message-002"
    }
  ]
}
```

The `itemIdentifier` is the SQS `messageId`.

Only failed SQS records are returned.

Successful sibling messages are acknowledged by the Lambda-SQS integration.

## Per-Message Isolation

Each SQS record is parsed and processed independently.

Example:

```text
message-001 succeeds
message-002 fails
message-003 succeeds
```

Response:

```json
{
  "batchItemFailures": [
    {
      "itemIdentifier": "message-002"
    }
  ]
}
```

The failure of `message-002` does not prevent `message-003` from being processed.

## Multiple S3 Records in One SQS Message

One SQS message may contain multiple S3 records:

```text
message-001
    ├── uploaded event A
    ├── uploaded event B
    └── uploaded event C
```

The partial failure unit remains the entire SQS message.

If event B fails:

```text
process A
process B → failure
do not process C
mark message-001 as failed
```

The message will be retried as a whole.

Event A may therefore be processed again on retry.

This reinforces that future application effects must be idempotent.

## Fail-Fast Within One Message

The handler stops processing remaining S3 records after the first failure in the same SQS message.

This decision reduces avoidable side effects before the whole message is retried.

It does not eliminate duplicate processing for earlier successful records in that same message.

## Failure Classification

### Malformed Outer Event

Examples:

```text
event is not an object
Records is missing
Records is not a list
```

Behavior:

```text
raise MalformedQueueEventError
```

The entire Lambda invocation fails because no trustworthy per-message boundary can be established.

### Missing or Invalid messageId

Examples:

```text
SQS record is not an object
messageId missing
messageId blank
messageId is not a string
```

Behavior:

```text
raise MalformedQueueMessageError
```

A partial batch response cannot be constructed safely without the SQS message identifier.

### Deterministically Invalid Message

Examples:

```text
invalid JSON body
unexpected S3 bucket
unsupported S3 event
invalid canonical object key
invalid object size
```

Behavior:

```text
include messageId in batchItemFailures
```

The message is retried and may eventually reach the DLQ according to the queue redrive policy.

The handler does not silently acknowledge invalid messages.

### Processing Failure

Examples:

```text
UploadedDocumentProcessingError
unexpected processor exception
```

Behavior:

```text
include messageId in batchItemFailures
```

The error remains inside the Lambda boundary and the message is retried.

## Processing Port

The handler depends on:

```text
UploadedDocumentProcessor
```

Contract:

```python
def process(
    *,
    event: UploadedDocumentEvent,
) -> None: ...
```

The handler does not know the concrete processing implementation.

## Current Processor Adapter

The current runtime composition maps:

```text
UploadedDocumentProcessor
    → ApplicationUploadedDocumentProcessor
    → StartDocumentProcessing
```

The processor now:

```text
loads the authoritative job through the repository
validates canonical object ownership
acquires or reconciles a bounded ProcessingAttempt claim
treats active processing and succeeded states idempotently
```

It still does not:

```text
download S3 content
invoke the AI provider
persist processing results
```

Authoritative processing-start ownership and claim semantics are documented separately.

The handler slice continues to stabilize:

```text
batch isolation
partial failure semantics
event fan-out
handler composition
retry classification
```

S3 reads, AI execution, and attempt-aware result persistence remain intentionally deferred.

## Handler Structure

The Lambda entrypoint:

```python
def lambda_handler(event, context): ...
```

loads runtime settings, obtains the cached processor, and delegates to:

```python
def handle(
    event,
    context,
    *,
    processor,
    expected_bucket_name,
): ...
```

The testable `handle()` function does not access AWS.

## Cold-Start Composition

The processor is cached at module scope:

```text
first invocation
    → build processor
    → cache processor

warm invocation
    → reuse processor
```

The composition root itself remains stateless and returns a new processor for each explicit call.

Caching belongs to the Lambda delivery adapter, not the composition function.

## Expected Bucket

The handler passes:

```text
settings.documents_bucket_name
```

to the single-record parser.

The parser enforces the expected source bucket before producing normalized events.

## Reliability Semantics

The queue is standard SQS.

The system assumes:

```text
at-least-once delivery
possible duplicate delivery
best-effort ordering
whole-message retry
```

Partial batch response reduces unnecessary retries for successful sibling messages.

It does not provide exactly-once processing.

## Error Visibility

The handler catches exceptions associated with a valid SQS message ID and converts them into partial failures.

Internal exception details are not returned.

Structured logging is intentionally deferred to a dedicated observability slice.

## Testing Strategy

Unit tests verify:

```text
empty successful batch
one successful message
multiple successful messages
multiple S3 records in one message
message processing order
malformed-message isolation
processor-failure isolation
unexpected exception isolation
continuation after failed sibling messages
fail-fast behavior within one message
unique failed message identifiers
malformed outer event failure
missing message identity failure
no AWS access
```

## Intentionally Deferred

```text
S3 GetObject
UTF-8 validation
AI provider invocation
attempt-aware result persistence
retry release and terminal failure persistence
lease heartbeat or extension
structured logging
CloudWatch metrics
visibility timeout configuration
DLQ reconciliation
Terraform
real Lambda deployment
```