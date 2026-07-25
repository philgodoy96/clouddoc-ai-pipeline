# ADR-007: Use Partial SQS Batch Failures

## Status

Accepted

## Context

The Processor Lambda consumes batches from a standard SQS queue.

Without partial batch failure reporting, one failed record causes the entire batch to be retried.

Example:

```text
message A succeeds
message B fails
message C succeeds
```

Without partial response:

```text
A, B, and C are all delivered again
```

This increases duplicate work and expands the idempotency burden.

AWS Lambda supports returning failed SQS message identifiers so only those records are retried.

## Decision

The Processor Lambda will use partial SQS batch failure responses.

Response shape:

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

Each SQS record is parsed and processed independently.

## Per-Record Isolation

The handler continues processing sibling SQS records after one message fails.

```text
message-001 succeeds
message-002 fails
message-003 succeeds
```

Only `message-002` is returned as failed.

This isolates retries at the SQS message boundary.

## Multiple S3 Records per Message

One SQS message may contain multiple S3 notification records.

The retry boundary remains the SQS message, not the individual S3 record.

If one contained event fails, the entire SQS message is returned as failed.

The handler stops processing remaining events in that message after the first failure.

This fail-fast policy limits additional side effects before retry.

## Invalid Deterministic Messages

Malformed or unsupported messages with a valid `messageId` are returned as failures.

Examples:

```text
invalid JSON body
unexpected bucket
unsupported S3 event
invalid canonical object key
invalid object size
```

They are not silently acknowledged.

This allows the queue redrive policy to move persistent invalid messages to a DLQ for investigation.

## Outer Envelope Failures

A malformed outer Lambda event cannot always be associated with a safe SQS `messageId`.

Examples:

```text
event is not an object
Records is missing
Records is not a list
```

The handler raises and fails the entire invocation.

Similarly, an individual record without a valid `messageId` raises because the required partial failure identifier is unavailable.

## Processing Failures

Retryable application failures and unexpected processor exceptions both mark the current SQS message as failed.

The Lambda boundary contains the exception and returns the message identifier.

Internal exception details are not exposed in the response.

## Consequences

### Positive

- Successful sibling messages are not retried unnecessarily.
- Retry behavior aligns with the SQS message boundary.
- Malformed deterministic messages can reach the DLQ.
- Processor failures remain isolated.
- Batch throughput remains available.
- The handler can continue after one failed sibling message.
- AWS-managed retry and redrive behavior remains in use.

### Negative

- Earlier successful events inside a failed multi-event message may run again.
- Partial batch response does not provide exactly-once processing.
- Missing `messageId` values cannot be represented safely.
- Unexpected exceptions are currently classified only as message failures.
- Invalid deterministic messages consume retry attempts before reaching the DLQ.
- Correct behavior depends on enabling the Lambda event-source mapping partial-response feature.

These costs are accepted because partial failure reporting materially reduces unnecessary batch retries without introducing custom queue acknowledgement logic.

## Alternatives Considered

### Fail the entire Lambda invocation

Rejected because one failed message would cause all successful sibling messages to be retried.

### Acknowledge deterministic invalid messages as successful

Rejected because invalid uploads or configuration problems would be discarded without durable operational evidence.

A future quarantine mechanism could support this policy, but no such mechanism exists yet.

### Publish invalid messages to a separate quarantine queue

Deferred because it introduces additional infrastructure, permissions, and publishing failure modes.

The existing DLQ redrive path is sufficient for the current stage.

### Process all remaining S3 events after one event fails in the same message

Rejected because the entire SQS message will be retried anyway.

Continuing would increase the number of effects requiring deduplication.

### Split one SQS message into independent internal retry units

Rejected because Lambda partial batch response operates at the SQS message level.

A custom republishing layer would add complexity and new delivery semantics.

## Idempotency Implications

Partial batch failure reduces duplicate delivery across successful sibling messages.

It does not eliminate duplicate processing.

Future processor behavior must be idempotent because:

```text
standard SQS is at least once
failed messages are retried
successful earlier events in one failed message may repeat
Lambda may time out after producing partial effects
```

The final idempotency policy will use authoritative job state and event metadata rather than relying only on SQS `messageId`.

## Security Considerations

Malformed messages are not trusted.

The handler relies on the parser to validate:

```text
expected bucket
canonical object key
ObjectCreated event family
strict field types
```

Internal exception details are not returned through the Lambda response.

Future structured logs must avoid exposing document contents or sensitive infrastructure details.

## Operational Considerations

The event-source mapping must enable:

```text
ReportBatchItemFailures
```

The DLQ redrive policy must use a bounded receive count.

Monitoring should include:

```text
Lambda errors
partial batch failure count
failed message identifiers
approximate receive count
DLQ depth
age of oldest message
invalid payload classification
unexpected processor failures
```

The SQS visibility timeout must exceed the effective Lambda processing duration with operational margin.

Exact timeout values will be selected after the real processing workflow is introduced.

## Current Processor

Runtime composition currently returns:

```text
NoOpUploadedDocumentProcessor
```

This is intentional.

The current slice validates delivery and retry behavior before introducing job state, S3 reads, and AI inference.

## Follow-up Work

- Replace the no-op processor with an application processing service.
- Add authoritative job lookup.
- Define idempotent job-state transitions.
- Add S3 document retrieval.
- Add structured logs and metrics.
- Configure `ReportBatchItemFailures` in Terraform.
- Add DLQ and redrive infrastructure.
- Add operational alarms and reconciliation.