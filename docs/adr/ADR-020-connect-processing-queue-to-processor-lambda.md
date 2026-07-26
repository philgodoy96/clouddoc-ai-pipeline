# ADR-020: Connect Processing Queue to Processor Lambda

## Status

Accepted

## Context

CloudDoc already provisions:

```text
a standard processing SQS queue
a processing DLQ
a Document Processor Lambda
a separate Processor execution role
attempt-aware processing application services
partial batch response support in the handler
```

The queue and function are not operationally connected until an event source mapping exists.

The integration must preserve:

```text
least-privilege queue access
bounded AI-processing concurrency
at-least-once delivery
partial batch failure semantics
queue redrive behavior
authoritative DynamoDB state
```

The workload is potentially expensive because one message may trigger document retrieval and AI inference.

## Decision

CloudDoc will connect the processing queue to the Document Processor Lambda with one AWS Lambda event source mapping.

The mapping will use:

```text
enabled = true
batch size = 1
maximum batching window = 0 seconds
function response type = ReportBatchItemFailures
maximum event-source concurrency = 5
```

The mapping will depend explicitly on the Processor queue-consumer inline policy.

## IAM Decision

The Processor execution role will receive a dedicated SQS consumer policy granting exactly:

```text
sqs:DeleteMessage
sqs:GetQueueAttributes
sqs:ReceiveMessage
```

The policy will target only:

```text
aws_sqs_queue.processing.arn
```

The policy will not grant queue publication, administration, purge, message movement, DLQ access, wildcard resources, or customer-managed KMS permissions.

## Managed Policy Decision

CloudDoc will not attach:

```text
AWSLambdaSQSQueueExecutionRole
```

The project already owns function-scoped CloudWatch logging permissions.

A dedicated inline policy produces a narrower and more reviewable queue-consumer boundary.

## Lambda Permission Decision

CloudDoc will not create an `aws_lambda_permission` resource for this integration.

The Lambda service polls SQS using the function execution role.

No external service principal directly invokes the function.

## Batch Size Decision

The mapping will use:

```text
batch_size = 1
```

One SQS message represents one document-processing attempt.

A processing attempt may include:

```text
S3 retrieval
DynamoDB conditional writes
AI inference
schema validation
attempt-aware finalization
```

A one-record batch keeps timeout, retry, failure, and inference-cost boundaries aligned to one document.

Larger batches remain deferred until deployed measurements demonstrate a concrete throughput benefit.

## Batching Window Decision

The mapping will use:

```text
maximum_batching_window_in_seconds = 0
```

Waiting to accumulate records provides no benefit when the maximum batch contains one record.

## Partial Batch Response Decision

The mapping will enable:

```text
ReportBatchItemFailures
```

The Processor handler already returns the corresponding partial failure contract.

Enabling the response type prevents drift between handler behavior and infrastructure behavior.

The configuration also keeps the path open for a future measured increase in batch size.

## Concurrency Decision

The mapping will use:

```text
maximum_concurrency = 5
```

This bounds parallel processing from the queue and protects:

```text
future Bedrock quotas
AI spend
DynamoDB write pressure
S3 request volume
Lambda account concurrency
```

The function will not receive reserved concurrency in this slice.

Reserved concurrency must be designed together with event-source concurrency and account-level workload allocation.

## Timeout Decision

The existing values remain:

```text
Processor timeout = 120 seconds
queue visibility timeout = 720 seconds
```

The six-times ratio is preserved.

Any change to either value requires reviewing the integration as one timeout and retry contract.

## Redrive Decision

The existing queue redrive threshold remains:

```text
maxReceiveCount = 3
```

This is intentionally lower than a generic high-retry posture because the workload may perform costly AI inference.

CloudDoc favors earlier DLQ isolation and explicit reconciliation over repeated expensive attempts.

The threshold must be revisited using deployed failure and cost data.

## Encryption Decision

The processing queue and DLQ continue to use SQS-managed encryption.

No `kms:Decrypt` permission is added.

A customer-managed KMS key remains a separate decision.

## Consequences

### Positive

- The processing queue becomes operationally connected to the Processor.
- Queue permissions are restricted to one ARN.
- The Processor cannot publish or administer SQS.
- Each invocation owns one document-processing attempt.
- Partial batch failure semantics match the handler contract.
- AI-processing concurrency is explicitly bounded.
- The timeout and visibility relationship remains reviewable.
- SQS continues to own retry and redrive.
- DynamoDB continues to own business lifecycle state.
- Offline tests validate the integration without AWS access.

### Negative

- Batch size one may reduce throughput compared with multi-record invocations.
- Maximum concurrency five may allow queue age to grow during bursts.
- Enabling maximum event-source concurrency may reduce some low-traffic polling optimization.
- Three receives may dead-letter some transient failures earlier than a generic retry policy.
- No reserved concurrency protects the Processor from concurrency used by other invocation sources.
- Real throughput and cost remain unmeasured until deployment.

## Alternatives Considered

### Use a Larger Batch

Deferred.

AI inference and document processing make per-record duration and cost significant.

A larger batch requires deployed duration, timeout, provider-quota, and retry measurements.

### Use a Batching Window

Rejected.

The batch size is one, so waiting cannot improve batch utilization.

### Disable Partial Batch Responses

Rejected.

The handler already implements the partial batch contract.

Disabling it would create infrastructure and application semantic drift.

### Use Unlimited Event-Source Concurrency

Rejected.

Unbounded parallel AI processing creates unnecessary quota and cost risk.

### Configure Reserved Concurrency Now

Deferred.

Reserved concurrency must account for all function invocation sources and account-level workload allocation.

### Attach AWSLambdaSQSQueueExecutionRole

Rejected.

Its scope is broader than the required dedicated queue-consumer policy and overlaps with separately managed logging permissions.

### Grant ChangeMessageVisibility

Rejected.

The current handler does not own custom visibility extension.

The event source mapping and queue timeout own the current visibility contract.

### Grant Access to the DLQ

Rejected.

The Processor must not consume or replay exhausted messages.

The Dead-Letter Reconciler owns the future DLQ consumer boundary.

### Add a Lambda Permission Resource

Rejected.

SQS event source mappings use the execution role for polling rather than direct service invocation.

### Increase maxReceiveCount

Deferred.

The current threshold reflects a cost-aware AI workload posture and requires deployed evidence before adjustment.

## Offline Test Decision

Terraform native tests will use a mocked AWS provider and `command = plan`.

Computed identifiers will be overridden where necessary.

The tests will validate:

```text
exact queue-consumer actions
queue ARN restriction
dedicated inline policy identity
mapping source and target
enabled status
batch size
batching window
partial failure reporting
maximum concurrency
absence of reserved concurrency
timeout-to-visibility ratio
redrive threshold
retention
encryption
```

The tests will not compare rendered inline policy JSON that remains unknown during plan.

## Follow-Up Decisions

Future work must define:

```text
DLQ Reconciler consumer permissions
DLQ event-source mapping
DLQ batch and concurrency configuration
dead-letter reconciliation retries
automatic replay policy
CloudWatch queue-age alarms
CloudWatch DLQ-depth alarms
Processor throttling alarms
Bedrock quotas and IAM
deployed performance testing
```