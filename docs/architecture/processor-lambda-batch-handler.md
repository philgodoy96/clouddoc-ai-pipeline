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

Those effects belong to the authoritative processing adapter and application workflow.

## Evolution Note

Earlier slices stabilized the batch-handler contract with a NoOp processor while S3 retrieval, AI invocation, Terraform event-source mapping, and structured logging remained sequenced follow-up work.

The current repository state advances that contract:

```text
ApplicationUploadedDocumentProcessor is the authoritative processing adapter
S3 retrieval and AI invocation are implemented in the processing workflow
Terraform event-source mapping is implemented
structured operational logging is implemented
```

The original partial-batch semantics remain unchanged.

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
    → ProcessUploadedDocument
```

The authoritative processing adapter:

```text
loads the authoritative job through the repository
validates canonical object ownership
acquires or reconciles a bounded ProcessingAttempt claim
loads the source document from S3
invokes the configured AI provider
persists attempt-aware completion or terminal failure
treats already-applied effects idempotently
```

Authoritative processing-start ownership, claim semantics, and attempt-aware finalization are documented separately.

The handler continues to own:

```text
batch isolation
partial failure semantics
event fan-out
handler composition
retry classification for reportable failures
```

## Processing Telemetry Ownership

Telemetry ownership is split:

```text
adapter emits processing.record_completed
handler emits processing.record_failed
handler emits processing.batch_completed
```

Successful authoritative workflow outcomes emit one `processing.record_completed` event from the adapter. The handler does not emit a duplicate successful record event.

The handler emits `processing.record_failed` for reportable per-message failures that enter `batchItemFailures`.

The handler emits one `processing.batch_completed` summary per invocation.

Malformed outer-event and missing-message-ID cases still emit best-effort `processing.batch_completed` telemetry with `outcome=event_rejected` before the original exception propagates.

Logging failure cannot change acknowledgement or partial-batch behavior.

Detailed field contracts are documented in [CloudWatch Observability](cloudwatch-observability.md).

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
    logger=...,
    timer=...,
): ...
```

Production `lambda_handler` uses `StandardOperationalLogger`.

Direct `handle` tests default to `NullOperationalLogger`.

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

Structured operational logging is implemented for record and batch telemetry. Logs remain best-effort operational evidence and do not claim exactly-once delivery.

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
processing.record_completed ownership on the adapter
processing.record_failed ownership on the handler
processing.batch_completed summaries
logging-failure isolation
no AWS access
```

## Intentionally Deferred

```text
lease heartbeat or extension
custom metrics
distributed tracing
operator recovery tooling
real Lambda deployment and end-to-end AWS validation
```

## Related Documentation

- [CloudWatch Observability](cloudwatch-observability.md)
- [Runtime Composition](runtime-composition.md)
- [Bedrock AI Provider Integration](bedrock-ai-provider-integration.md)
- [ADR-024: Use Native AWS Metrics and Structured Application Logs](../adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)
