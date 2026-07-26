# Processing Queue Consumer Infrastructure

## Status

Implemented as an incremental Terraform infrastructure slice.

This document describes the SQS-to-Lambda consumption boundary that connects the CloudDoc processing queue to the Document Processor Lambda function.

## Purpose

CloudDoc receives document-upload notifications through Amazon S3 and publishes them to a standard SQS processing queue.

This slice connects that queue to the Document Processor Lambda through an AWS Lambda event source mapping.

The integration is responsible for:

```text
polling the processing queue
invoking the Document Processor
deleting successfully processed messages
returning failed messages to visibility
enforcing a bounded concurrency limit
preserving partial batch failure semantics
```

The integration does not own business lifecycle state.

DynamoDB remains authoritative for:

```text
DocumentJob lifecycle
processing-attempt ownership
lease state
idempotent effects
terminal completion
terminal failure
```

SQS remains authoritative for:

```text
message delivery
receive count
visibility timeout
retry timing
redrive to the processing DLQ
```

## Provisioned Resource

Terraform declares:

```text
aws_lambda_event_source_mapping.processing_queue
```

The event source is:

```text
aws_sqs_queue.processing
```

The target is:

```text
aws_lambda_function.processor
```

The mapping is enabled.

## Event Source Configuration

The approved mapping configuration is:

```text
batch size = 1
maximum batching window = 0 seconds
function response type = ReportBatchItemFailures
maximum event-source concurrency = 5
```

The mapping explicitly depends on:

```text
aws_iam_role_policy.processor_queue_consumer
```

This prevents the integration from being created before the Processor execution role has the required queue-consumer permissions.

## Queue Consumer IAM Boundary

The Document Processor receives a dedicated inline SQS policy.

The policy grants exactly:

```text
sqs:DeleteMessage
sqs:GetQueueAttributes
sqs:ReceiveMessage
```

The resource is restricted to:

```text
aws_sqs_queue.processing.arn
```

The policy does not grant:

```text
sqs:SendMessage
sqs:PurgeQueue
sqs:SetQueueAttributes
sqs:ChangeMessageVisibility
sqs:DeleteQueue
sqs:StartMessageMoveTask
sqs:*
```

The Processor does not receive access to the processing DLQ.

The project does not attach:

```text
AWSLambdaSQSQueueExecutionRole
```

The existing logging permissions remain separate and function-scoped.

## Why No Lambda Permission Resource

The integration does not require an `aws_lambda_permission` resource.

For an SQS event source mapping, the Lambda service polls the queue using the function execution role.

This differs from integrations such as API Gateway, where another service directly invokes the function and therefore requires an explicit Lambda resource-based permission.

## Batch Size

The event source mapping uses:

```text
batch_size = 1
```

One queue message represents one document-processing attempt.

Each attempt may involve:

```text
S3 object retrieval
DynamoDB claim acquisition
AI provider invocation
schema validation
attempt-aware finalization
```

A batch size of one creates one bounded failure and cost domain per invocation.

Benefits include:

```text
clearer timeout reasoning
simpler attempt ownership
predictable inference cost attribution
easier failure investigation
lower risk of one slow document delaying unrelated work
```

A larger batch size remains a future option after deployed measurements establish that multi-record invocations improve throughput without harming timeout, cost, retry, or provider-quota behavior.

## Batching Window

The mapping uses:

```text
maximum_batching_window_in_seconds = 0
```

There is no benefit in waiting to accumulate records while the batch size is one.

The configuration favors immediate consumption over artificial batching latency.

## Partial Batch Failure Reporting

The mapping enables:

```text
ReportBatchItemFailures
```

The Processor handler returns the Lambda partial batch response contract:

```json
{
  "batchItemFailures": [
    {
      "itemIdentifier": "message-id"
    }
  ]
}
```

With a batch size of one, this configuration still matters because it preserves alignment between:

```text
handler response semantics
event-source mapping semantics
future measured batch-size changes
```

An unhandled exception still causes the entire invocation to fail.

## Concurrency Boundary

The mapping uses:

```text
maximum_concurrency = 5
```

This limits the number of concurrent Processor invocations created by this event source.

The boundary protects:

```text
future Bedrock quotas
AI inference spend
DynamoDB write pressure
S3 request volume
account-level Lambda concurrency
```

The function does not configure reserved concurrency in this slice.

In Terraform plan semantics, the absence of that configuration is represented as:

```text
reserved_concurrent_executions = null
```

Reserved concurrency remains a future decision that must be coordinated with:

```text
event-source concurrency
batch size
Bedrock quotas
DynamoDB capacity
retry behavior
account-level concurrency
```

## Timeout and Visibility Contract

The Document Processor timeout is:

```text
120 seconds
```

The processing queue visibility timeout is:

```text
720 seconds
```

The ratio remains:

```text
720 / 120 = 6
```

This gives one Processor invocation a six-times visibility margin.

The zero-second batching window adds no additional delay requirement.

Changing the Processor timeout or the queue visibility timeout requires reviewing this relationship as one system contract.

## Retry and Redrive Behavior

The processing queue retains:

```text
message retention = 4 days
maximum receive count = 3
```

The processing DLQ retains:

```text
message retention = 14 days
```

The lifecycle is:

```text
attempt 1 fails
    → message becomes visible again

attempt 2 fails
    → message becomes visible again

attempt 3 fails
    → SQS redrives the message to the processing DLQ
```

CloudDoc intentionally uses three receives for a potentially expensive AI-processing workload.

This favors earlier dead-letter isolation and explicit reconciliation over excessive repeated inference.

The decision must be revisited after deployed measurements of:

```text
transient provider failures
throttling recovery
successful retry distribution
DLQ volume
average inference cost
```

## Failure Semantics

### Successful Processing

The handler returns no failed item.

Lambda deletes the queue message.

### Retryable Record Failure

The handler returns the message identifier in `batchItemFailures`.

The message remains in the queue and becomes visible after the visibility timeout.

### Unhandled Exception

The entire invocation fails.

The message remains eligible for retry.

### Exhausted Delivery

SQS moves the message to the processing DLQ after the configured receive threshold.

The Dead-Letter Reconciler consumer remains a separate slice.

## Security Boundary

### Queue Scope

The Processor can consume only:

```text
aws_sqs_queue.processing
```

### No Queue Administration

The Processor cannot:

```text
publish
purge
delete
reconfigure
move
or enumerate queues
```

### No DLQ Access

The Processor cannot consume or replay the processing DLQ.

### Encryption

The processing queue and DLQ use SQS-managed server-side encryption.

No customer-managed KMS permission is required.

### No Wildcard SQS Access

The consumer policy uses one explicit queue ARN.

## Scaling Position

With:

```text
batch size = 1
maximum concurrency = 5
```

The approximate steady-state throughput depends on average processing duration.

For example:

```text
average duration = 30 seconds
maximum concurrency = 5
approximate upper bound = 10 documents per minute
```

This is not a capacity guarantee.

Real throughput is affected by:

```text
cold starts
S3 latency
DynamoDB contention
AI provider latency
provider throttling
retry volume
Lambda service scaling behavior
```

Operational tuning requires deployed metrics.

## Offline Testing

The integration is covered by:

```text
infra/terraform/tests/processing_event_source.tftest.hcl
```

The test uses:

```text
mock_provider "aws"
command = plan
```

Computed resource identifiers are overridden where plan-time assertions require deterministic values.

The test validates:

```text
exact SQS consumer actions
processing queue ARN restriction
absence of DLQ and wildcard access
dedicated inline policy naming
Processor function target
processing queue source
enabled mapping
batch size 1
zero batching window
ReportBatchItemFailures
maximum concurrency 5
reserved concurrency remains unconfigured
Processor timeout 120 seconds
queue visibility timeout 720 seconds
six-times timeout ratio
redrive threshold 3
queue and DLQ retention
SQS-managed encryption
```

The test deliberately validates the configured inline policy name rather than comparing rendered policy JSON that remains unknown during `command = plan`.

The tests do not create AWS resources or require AWS credentials.

## Cost Posture

This slice may increase costs through:

```text
Lambda invocations
Lambda duration
SQS receive requests
AI-processing retries
```

Cost controls include:

```text
batch size 1 for bounded per-document cost
maximum concurrency 5
three-receive redrive threshold
no provisioned concurrency
no provisioned pollers
no automatic DLQ replay
```

The current settings prioritize predictable failure domains and bounded AI parallelism over maximum throughput.

## Intentionally Deferred

The following remain separate implementation slices:

```text
DLQ Reconciler event-source mapping
DLQ consumer IAM permissions
automatic DLQ replay
reserved concurrency
provisioned concurrency
provisioned SQS pollers
event filtering
batch size greater than 1
CloudWatch queue-age alarms
CloudWatch DLQ-depth alarms
Lambda throttling alarms
Bedrock integration
Bedrock IAM permissions
real AWS deployment
load testing
failure injection
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

The next slice should connect the processing DLQ to the Dead-Letter Reconciler Lambda.

That work must define:

```text
DLQ consumer IAM actions
DLQ event-source mapping
batch size
partial batch response behavior
concurrency boundary
reconciliation retry behavior
automatic replay exclusion
```