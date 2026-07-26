# Dead-Letter Reconciliation Infrastructure

## Status

Implemented as an incremental Terraform infrastructure slice.

This document describes the infrastructure boundary that connects the CloudDoc processing dead-letter queue to the Dead-Letter Reconciler Lambda and isolates repeated reconciliation failures in a terminal quarantine queue.

## Purpose

CloudDoc uses a two-stage failure topology:

```text
primary processing failure
    → processing DLQ

reconciliation failure
    → reconciliation failure quarantine
```

The first stage isolates messages that exhausted normal document-processing retries.

The second stage isolates messages that repeatedly fail reconciliation itself.

This separation prevents malformed, permanently invalid, or operationally unrecoverable messages from remaining in an active retry loop until queue retention expires.

## End-to-End Failure Topology

```text
S3 ObjectCreated
    → processing queue
    → Document Processor Lambda
    → processing DLQ after three receives
    → Dead-Letter Reconciler Lambda
    → reconciliation failure quarantine after three reconciliation receives
```

The quarantine queue is terminal in the current architecture:

```text
no Lambda consumer
no automatic replay
no message-move workflow
no route back to the processing queue
```

## Ownership Boundaries

### Processing Queue

Owns active document-processing delivery.

### Processing DLQ

Owns exhausted primary-processing deliveries awaiting reconciliation.

### Dead-Letter Reconciler

Owns the application decision that maps exhausted delivery into authoritative `DocumentJob` state.

### DynamoDB

Owns authoritative business lifecycle state.

### Reconciliation Failure Quarantine

Owns terminal operational evidence for messages that could not be reconciled after bounded retries.

### Operators

Own future investigation and controlled recovery.

## Reconciliation Failure Quarantine

Terraform declares:

```text
aws_sqs_queue.reconciliation_failures
```

The environment-scoped name is:

```text
${project_name}-${environment}-reconciliation-failures
```

Example:

```text
clouddoc-dev-reconciliation-failures
```

Configured properties:

```text
queue type = Standard
delay = 0 seconds
visibility timeout = 180 seconds
retention = 14 days
encryption = SQS-managed server-side encryption
```

Tags:

```text
Name = environment-scoped queue name
QueueRole = dead-letter-reconciliation-quarantine
```

The queue has no consumer and no redrive policy of its own.

## Processing DLQ Redrive Contract

The existing processing DLQ now has a redrive policy targeting the reconciliation failure quarantine:

```text
maxReceiveCount = 3
deadLetterTargetArn = reconciliation failure queue ARN
```

This creates the bounded reconciliation retry path:

```text
reconciliation attempt 1 fails
    → message returns to processing DLQ

reconciliation attempt 2 fails
    → message returns to processing DLQ

reconciliation attempt 3 fails
    → message moves to reconciliation failure quarantine
```

The original processing queue redrive policy remains unchanged:

```text
processing queue
    → processing DLQ after three receives
```

## Restrictive Redrive Allow Policy

Terraform declares a redrive allow policy on the quarantine queue.

The policy uses:

```text
redrivePermission = byQueue
sourceQueueArns = [processing DLQ ARN]
```

Only the processing DLQ may use the quarantine queue as a dead-letter destination.

The policy does not allow arbitrary source queues.

## Dead-Letter Reconciler Queue Permissions

The reconciler execution role receives a dedicated processing-DLQ consumer policy.

The policy grants exactly:

```text
sqs:DeleteMessage
sqs:GetQueueAttributes
sqs:ReceiveMessage
```

The resource is restricted to:

```text
aws_sqs_queue.processing_dlq.arn
```

The reconciler does not receive access to:

```text
primary processing queue
reconciliation failure quarantine
wildcard SQS resources
```

The reconciler also does not receive:

```text
sqs:SendMessage
sqs:ChangeMessageVisibility
sqs:PurgeQueue
sqs:SetQueueAttributes
sqs:StartMessageMoveTask
sqs:CancelMessageMoveTask
sqs:ListMessageMoveTasks
```

This prevents the runtime from replaying or administrating queue contents.

## Event Source Mapping

Terraform declares:

```text
aws_lambda_event_source_mapping.processing_dlq
```

The source is:

```text
aws_sqs_queue.processing_dlq
```

The target is:

```text
aws_lambda_function.dead_letter_reconciler
```

Configured behavior:

```text
enabled = true
batch size = 1
maximum batching window = 0 seconds
function response type = ReportBatchItemFailures
maximum event-source concurrency = 2
```

The mapping explicitly depends on:

```text
aws_iam_role_policy.dead_letter_reconciler_queue_consumer
```

This ensures the Lambda execution role has the required queue-consumer permissions before the event source mapping is created.

## Batch Size

The mapping uses:

```text
batch_size = 1
```

Each invocation owns one exhausted message and one reconciliation decision.

This is intentionally conservative because each message has already failed repeatedly in the primary processing path.

A single-record batch creates a clear boundary for:

```text
parsing
authoritative state inspection
conditional persistence
retry
quarantine
operational investigation
```

## Batching Window

The mapping uses:

```text
maximum_batching_window_in_seconds = 0
```

Waiting to accumulate messages provides no benefit when the batch size is one.

The reconciler therefore begins work without artificial batching delay.

## Partial Batch Failure Reporting

The mapping enables:

```text
ReportBatchItemFailures
```

The handler returns the SQS partial batch response contract:

```json
{
  "batchItemFailures": [
    {
      "itemIdentifier": "message-id"
    }
  ]
}
```

A reported failure remains in the processing DLQ until the visibility timeout expires.

A successful record is deleted by the Lambda-managed SQS integration.

An unhandled invocation exception causes the complete invocation to fail.

## Concurrency Boundary

The mapping uses:

```text
maximum_concurrency = 2
```

DLQ traffic should be exceptional.

A low concurrency boundary prevents a failure storm in the primary pipeline from creating a reconciliation storm.

The limit protects:

```text
DynamoDB write pressure
Lambda account concurrency
log volume
operator signal quality
```

Lambda reserved concurrency remains unconfigured.

In Terraform plan semantics:

```text
reserved_concurrent_executions = null
```

Reserved concurrency remains a future account-level capacity decision.

## Timeout and Visibility Contract

The Dead-Letter Reconciler timeout is:

```text
30 seconds
```

The processing DLQ visibility timeout is:

```text
180 seconds
```

The relationship is:

```text
180 / 30 = 6
```

The zero-second batching window adds no additional delay requirement.

Changing either timeout requires reviewing the integration as one operational contract.

## Quarantine Retention

The quarantine queue retains messages for 14 days.

It is not an archive.

Its purpose is to preserve enough time for:

```text
operator investigation
message inspection
correlation with logs
root-cause analysis
controlled recovery planning
```

For Standard queues, moving a message to a downstream dead-letter queue does not reset its original enqueue timestamp.

The effective remaining retention therefore depends on the message's original age.

The bounded retry path is designed to move persistent reconciliation failures into quarantine within minutes rather than days.

## No Automatic Replay

This slice deliberately adds no automatic replay path.

The reconciler does not receive:

```text
sqs:SendMessage
sqs:StartMessageMoveTask
```

No event source consumes the quarantine queue.

No resource routes quarantined messages back to the processing queue.

Automatic replay could repeat:

```text
expensive AI inference
invalid payload processing
stale business-state transitions
known operational failures
```

Any future replay must be a separately authorized operator workflow with:

```text
explicit message selection
authorization
audit logging
rate limits
idempotency controls
precondition checks
rollback and stop conditions
```

## Terraform Outputs

The root exports:

```text
reconciliation_failures_queue_name
reconciliation_failures_queue_arn
reconciliation_failures_queue_url
```

These outputs create stable boundaries for future:

```text
CloudWatch alarms
operator tooling
manual inspection
runbooks
deployment verification
```

The outputs do not grant access or expose message content.

## Offline Testing

The infrastructure is covered by:

```text
infra/terraform/tests/dead_letter_reconciliation_event_source.tftest.hcl
```

The test uses:

```text
mock_provider "aws"
command = plan
```

Plan-time computed values are overridden where deterministic identifiers are required.

The tests validate:

```text
environment-scoped quarantine naming
Standard queue type
zero delay
180-second visibility timeout
14-day retention
SQS-managed encryption
quarantine tags
processing-DLQ redrive target
three-receive reconciliation threshold
restrictive byQueue redrive allow policy
quarantine outputs
exact reconciler SQS actions
processing-DLQ-only resource scope
absence of primary-queue and quarantine access
absence of replay actions
event-source source and target
enabled mapping
batch size 1
zero batching window
ReportBatchItemFailures
maximum concurrency 2
reserved concurrency remains null
30-second reconciler timeout
180-second source visibility timeout
six-times timeout ratio
retention and encryption preservation
```

The tests do not create AWS resources or require AWS credentials.

## Security Boundary

### Queue Isolation

The reconciler can consume only the processing DLQ.

### Terminal Quarantine

The quarantine queue has no runtime consumer.

### No Replay Capability

The runtime has no send or message-move permissions.

### No Wildcard SQS Permissions

Every queue action targets one explicit ARN.

### Encryption

All involved queues use SQS-managed server-side encryption.

No customer-managed KMS permission is required.

### Bounded Retry

Persistent failures leave the active reconciliation loop after three receives.

## Failure Modes

### Malformed DLQ Message

The reconciler reports the message as failed.

After three receives, SQS moves it to quarantine.

### Temporary DynamoDB Failure

The message remains in the processing DLQ and is retried.

If the failure persists through the configured threshold, the message moves to quarantine.

### Reconciler Timeout

The invocation fails and the message remains eligible for retry after visibility expiration.

### Reconciler Logs Missing

The message may still retry or quarantine, but operational diagnosis becomes difficult.

### Incorrect Redrive Target

Persistent reconciliation failures may be lost from the intended investigation path.

### Quarantine Consumer Added Accidentally

Terminal evidence could be deleted or mutated automatically.

### Replay Permission Added Accidentally

The runtime could restart known-failing workflows without operator control.

### Visibility Timeout Reduced

Concurrent reconciliation attempts may overlap.

### Max Receive Count Increased Excessively

Persistent poison messages may create unnecessary Lambda cost and log noise.

## Cost Posture

This slice introduces potential costs through:

```text
SQS requests
reconciler Lambda invocations
CloudWatch log ingestion
repeated reconciliation attempts
quarantine message storage
```

Cost controls include:

```text
batch size 1
maximum concurrency 2
three-receive reconciliation threshold
no provisioned concurrency
no provisioned pollers
no automatic replay
bounded 14-day quarantine retention
```

The settings prioritize failure isolation and operator signal over maximum retry persistence.

## Intentionally Deferred

The following remain separate decisions:

```text
quarantine queue consumer
automatic replay
operator replay API
message-move permissions
manual recovery runbook
queue-depth alarms
message-age alarms
reconciler failure alarms
quarantine retention automation
reserved concurrency
provisioned concurrency
provisioned pollers
event filtering
real AWS deployment
failure injection
operator recovery testing
```

## Validation Commands

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
```

Repository validation remains:

```bash
make check
make lambda-package-check
git diff --check
```

No AWS credentials or `terraform apply` are required for the automated validation path.

## Follow-Up Work

The next project slice should move to the control-plane invocation boundary or the next approved sequence in the implementation plan.

Operational work related to this topology should later add:

```text
processing DLQ depth alarm
quarantine depth alarm
oldest-message-age alarm
reconciler error alarm
manual inspection runbook
controlled replay decision
```