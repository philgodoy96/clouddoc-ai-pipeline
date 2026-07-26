# ADR-021: Connect Processing DLQ to Reconciler Lambda

## Status

Accepted

## Context

CloudDoc already provisions:

```text
a processing queue
a processing DLQ
a Document Processor Lambda
a Dead-Letter Reconciler Lambda
authoritative DynamoDB job state
partial batch response support in the reconciler handler
```

The processing DLQ contains messages that exhausted the primary document-processing retry policy.

Those messages require a bounded reconciliation path that updates authoritative business state.

The reconciler handler may also fail because of:

```text
malformed messages
unexpected event shapes
temporary DynamoDB failures
conditional-state conflicts
unexpected runtime exceptions
```

Without a downstream terminal destination, a permanently invalid message would remain in the processing DLQ retry loop until retention expiration.

The infrastructure must therefore connect the processing DLQ to the reconciler while preserving:

```text
least privilege
bounded retries
bounded concurrency
partial batch semantics
no automatic replay
terminal operational evidence
```

## Decision

CloudDoc will connect the processing DLQ to the Dead-Letter Reconciler Lambda through one SQS event source mapping.

The mapping will use:

```text
enabled = true
batch size = 1
maximum batching window = 0 seconds
function response type = ReportBatchItemFailures
maximum event-source concurrency = 2
```

The processing DLQ will redrive persistent reconciliation failures to a dedicated terminal quarantine queue after three receives.

## Quarantine Queue Decision

CloudDoc will provision:

```text
aws_sqs_queue.reconciliation_failures
```

The queue will use:

```text
Standard queue type
zero delivery delay
180-second visibility timeout
14-day retention
SQS-managed server-side encryption
```

The queue will have no consumer and no redrive policy.

Its purpose is to retain terminal operational evidence for operator investigation.

It is not an archive and is not part of the active workflow.

## Redrive Decision

The processing DLQ will redrive to the reconciliation failure quarantine after:

```text
maxReceiveCount = 3
```

The quarantine queue will use a restrictive redrive allow policy:

```text
redrivePermission = byQueue
sourceQueueArns = [processing DLQ ARN]
```

Only the processing DLQ may use the quarantine queue as a dead-letter destination.

## Reconciler IAM Decision

The Dead-Letter Reconciler execution role will receive a dedicated SQS consumer policy granting exactly:

```text
sqs:DeleteMessage
sqs:GetQueueAttributes
sqs:ReceiveMessage
```

The policy will target only the processing DLQ ARN.

The reconciler will not receive:

```text
primary processing queue access
quarantine queue access
sqs:SendMessage
message-move permissions
queue-administration permissions
wildcard resources
```

## Automatic Replay Decision

CloudDoc will not implement automatic replay.

No Lambda consumes the quarantine queue.

The reconciler cannot publish to the processing queue or invoke SQS redrive APIs.

Replay must remain a future operator-controlled workflow because automated replay could repeat expensive inference, invalid payload handling, stale transitions, or known provider failures.

## Event Source Decision

The processing DLQ event source mapping will target only:

```text
aws_lambda_function.dead_letter_reconciler
```

No `aws_lambda_permission` resource will be created.

The Lambda service polls SQS using the function execution role.

## Batch Size Decision

The mapping will use:

```text
batch_size = 1
```

Each message has already failed repeatedly in the main processing path.

A one-record batch keeps one reconciliation decision, retry, and quarantine outcome aligned to one invocation.

## Batching Window Decision

The mapping will use:

```text
maximum_batching_window_in_seconds = 0
```

There is no batching benefit when the batch size is one.

The design favors immediate reconciliation.

## Partial Batch Response Decision

The mapping will enable:

```text
ReportBatchItemFailures
```

The reconciler handler already returns the corresponding SQS response contract.

A reported failure remains eligible for retry.

A successful message is deleted.

An unhandled invocation exception causes the full invocation to fail.

## Concurrency Decision

The mapping will use:

```text
maximum_concurrency = 2
```

DLQ traffic is exceptional and should not become a high-throughput path.

The low limit bounds:

```text
DynamoDB write pressure
Lambda account concurrency
failure amplification
log volume
```

The function will not configure reserved concurrency in this slice.

Reserved concurrency remains a future account-level capacity decision.

## Timeout Decision

The existing values remain:

```text
Dead-Letter Reconciler timeout = 30 seconds
processing DLQ visibility timeout = 180 seconds
```

The six-times ratio is preserved.

Any future timeout change must review the queue visibility contract at the same time.

## Retention Decision

The processing DLQ and reconciliation failure quarantine each retain messages for 14 days.

For Standard queues, movement to a downstream dead-letter queue does not reset the original enqueue timestamp.

The bounded retry path is therefore designed to move persistent reconciliation failures quickly.

A future archival or compliance requirement would require a separate durable evidence store.

## Encryption Decision

The processing DLQ and quarantine queue use SQS-managed encryption.

No customer-managed KMS permission is added.

## Output Decision

Terraform will export:

```text
reconciliation_failures_queue_name
reconciliation_failures_queue_arn
reconciliation_failures_queue_url
```

These outputs support future alarms, operator tooling, runbooks, and deployment inspection.

## Offline Test Decision

Terraform native tests will use:

```text
mock_provider "aws"
command = plan
```

The tests will validate:

```text
quarantine topology
redrive chain
restrictive source-queue access
reconciler least privilege
absence of replay permissions
event-source mapping behavior
partial batch reporting
concurrency boundary
timeout and visibility compatibility
retention
encryption
outputs
```

Computed identifiers will be overridden where plan-time determinism requires them.

The absence of a quarantine consumer remains a structural Terraform review because native tests do not provide a reliable negative enumeration of undeclared resources.

## Consequences

### Positive

- Exhausted processing messages receive an explicit business-state reconciliation path.
- Persistent reconciliation failures leave the active retry loop.
- Terminal failures remain available for operator investigation.
- The reconciler can consume only the processing DLQ.
- The runtime cannot replay messages.
- Concurrency is bounded.
- Partial batch semantics match the handler.
- Timeout and visibility remain aligned.
- Offline tests validate the topology without AWS access.

### Negative

- The topology adds another queue and redrive relationship.
- A terminal quarantine requires future operator procedures.
- Messages may have less than 14 days of remaining retention because Standard-queue timestamps are preserved.
- Three reconciliation attempts may quarantine some temporary failures.
- No automatic replay reduces convenience during recovery.
- No alarms currently notify operators about quarantine depth.
- Real recovery behavior remains unvalidated until deployment.

## Alternatives Considered

### Leave Failed Reconciliation Messages in the Processing DLQ Until Expiration

Rejected.

Permanent poison messages would create repeated Lambda cost, log noise, and eventual silent expiration.

### Automatically Replay to the Processing Queue

Rejected.

Replay could repeat known-failing or expensive work without operator review.

### Give the Reconciler SendMessage Permission

Rejected.

Reconciliation owns business-state repair, not workflow restart.

### Use SQS Message Move APIs from the Runtime

Rejected.

Message movement is an operator-level recovery action and should require separate authorization and audit controls.

### Use a Shared Quarantine Queue for Multiple Pipelines

Rejected for the current scope.

A dedicated queue provides a clearer ownership and alarm boundary.

### Use a Larger Reconciliation Batch

Rejected.

Messages have already failed repeatedly, so isolation is more valuable than throughput.

### Use Unlimited Reconciliation Concurrency

Rejected.

A primary failure storm must not produce a reconciliation storm.

### Configure Reserved Concurrency Now

Deferred.

Reserved concurrency must account for the complete Lambda workload allocation across the account.

### Use a Customer-Managed KMS Key

Deferred.

No current compliance or explicit key-ownership requirement justifies the additional key and IAM surface.

### Retain Quarantine Messages Indefinitely

Rejected.

SQS is not an archival evidence store.

A future archival requirement should use a purpose-built durable store.

## Follow-Up Decisions

Future work must define:

```text
processing DLQ depth alarms
quarantine depth alarms
oldest-message-age alarms
reconciler error alarms
operator inspection runbook
controlled replay authorization
audit logging for recovery actions
quarantine archival requirements
deployed failure injection
recovery validation
```