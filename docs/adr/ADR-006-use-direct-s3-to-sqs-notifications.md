# ADR-006: Use Direct S3-to-SQS Notifications

## Status

Accepted

## Context

After a client uploads a document to S3, CloudDoc must trigger asynchronous processing.

The processing path needs:

```text
buffering
backpressure
retry delivery
batch consumption
DLQ support
decoupling between upload rate and processing capacity
```

S3 can invoke a Lambda directly, publish to SNS, or publish directly to a standard SQS queue.

An additional publisher Lambda could also receive S3 events and forward custom messages to SQS.

## Decision

CloudDoc will configure S3 to publish `ObjectCreated` notifications directly to a standard SQS queue.

The Processor Lambda will consume SQS batches containing serialized S3 notifications.

```text
S3 ObjectCreated
    → standard SQS
    → Processor Lambda
```

The delivery layer will explicitly parse both envelopes:

```text
Lambda SQS batch
SQS message body containing S3 Records
```

## Rationale

Direct S3-to-SQS notification provides the required asynchronous buffer without introducing an intermediary compute hop.

It supports:

```text
upload-rate buffering
consumer backpressure
Lambda batch consumption
retry behavior
dead-letter queues
failure isolation
```

The design also keeps the upload path independent from processor availability.

## Standard Queue Semantics

CloudDoc will use a standard SQS queue.

The system must assume:

```text
at-least-once delivery
possible duplicates
best-effort ordering
no exactly-once guarantee
```

Application effects must therefore become idempotent.

The system will not rely on SQS message ordering to define document-job state.

## Consequences

### Positive

- No publisher Lambda is required.
- Fewer runtime components are deployed.
- Upload processing is buffered.
- Processor capacity can scale independently.
- SQS retry and DLQ behavior can protect the pipeline.
- Lambda can process records in batches.
- Temporary processor outages do not block uploads.
- The delivery path remains compatible with AWS-managed integrations.

### Negative

- SQS message bodies contain the full S3 notification envelope.
- The consumer must parse two nested record layers.
- Duplicate delivery is expected.
- Strict ordering is unavailable.
- S3 event notification filtering has limited transformation capability.
- Invalid deterministic messages may retry unless the handler defines an explicit acknowledgement policy.
- Direct notification configuration creates an infrastructure relationship between the bucket and queue.

These costs are accepted because the project prioritizes reliable buffering and a small operational surface.

## Alternatives Considered

### Invoke the Processor Lambda directly from S3

Rejected because direct invocation provides less explicit buffering and backpressure control.

A burst of uploads would translate directly into Lambda invocation pressure, and DLQ and retry behavior would be less aligned with the queue-based architecture.

### Add a publisher Lambda between S3 and SQS

Rejected for the current architecture because it adds another deployment unit, IAM role, logging surface, retry boundary, and cost without currently requiring event transformation.

A publisher Lambda may become appropriate if future workflows require enrichment, routing decisions, or a custom event schema before queueing.

### Publish from S3 to SNS and subscribe SQS

Deferred because CloudDoc currently has one consumer path.

SNS becomes useful when one upload event must fan out independently to multiple consumers.

### Use EventBridge

Deferred because the current workflow does not require advanced routing, archive, replay, cross-account event buses, or multiple rules.

EventBridge may become appropriate when the platform introduces broader event distribution requirements.

### Use an SQS FIFO queue

Rejected because S3 event notifications cannot target SQS FIFO queues directly, and the current design does not require strict ordering.

An intermediary publisher would be necessary, adding complexity.

The application will instead use authoritative job state and idempotent transitions.

## Event Validation

The consumer validates:

```text
expected source bucket
ObjectCreated event family
canonical document object key
non-negative object size
valid optional metadata
```

The object key is URL-decoded before validation.

The parser does not query DynamoDB.

Authoritative job validation belongs to the application processing use case.

## Security Considerations

Infrastructure must restrict the queue policy so only the approved S3 bucket can publish messages.

The queue policy should validate:

```text
aws:SourceArn
aws:SourceAccount
```

The processor Lambda execution role should receive only the permissions required to:

```text
consume the queue
read approved document objects
access authoritative job state
invoke the approved AI provider
emit operational telemetry
```

Bucket and queue configuration must not rely only on parser validation.

## Reliability Considerations

SQS delivery is at least once.

The future consumer must support:

```text
partial batch failure responses
visibility timeout aligned with processing duration
bounded retries
DLQ redrive
idempotent job transitions
safe duplicate handling
```

The queue visibility timeout must exceed the effective Lambda processing timeout with sufficient operational margin.

These values will be selected with the processor execution design rather than guessed in this ADR.

## Idempotency Considerations

SQS `messageId` is transport metadata and is not sufficient as the permanent business idempotency key.

S3 `sequencer`, `versionId`, `eTag`, object key, and authoritative job state are available inputs, but the final policy is intentionally deferred until the processing transition is designed.

Exactly-once inference will not be claimed.

## Operational Considerations

Future monitoring should include:

```text
queue depth
age of oldest message
Lambda errors
partial batch failures
retry count
DLQ message count
invalid notification count
unexpected bucket events
objects without authoritative jobs
duplicate deliveries
```

Structured logs should include:

```text
message_id
job_id
bucket_name
object_key
sequencer
request_id when available
correlation_id
```

## Follow-up Work

- Add the Processor Lambda delivery handler.
- Define partial batch failure behavior.
- Add authoritative job lookup.
- Define idempotent processing transitions.
- Add S3 document retrieval.
- Add SQS and Lambda infrastructure through Terraform.
- Configure queue policy and least-privilege IAM.
- Add CloudWatch metrics, alarms, and DLQ reconciliation.