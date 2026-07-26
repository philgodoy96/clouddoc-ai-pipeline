# Processing Queue Infrastructure

## Status

Implemented as the first executable Terraform infrastructure slice for CloudDoc AI Pipeline.

This document describes the processing queue topology provisioned under `infra/terraform`.

## Purpose

CloudDoc processes uploaded documents asynchronously.

The queue topology separates normal processing delivery from exhausted-message retention:

```text
Future S3 ObjectCreated notification
    ↓
CloudDoc processing queue
    ↓ bounded delivery attempts
CloudDoc processing dead-letter queue
```

The processing queue owns delivery state.

DynamoDB remains the authoritative source for the `DocumentJob` lifecycle.

A message reaching the dead-letter queue means queue delivery attempts were exhausted. It does not independently determine whether the related job should become `dead`.

## Provisioned Resources

The Terraform root module provisions:

```text
aws_sqs_queue.processing
aws_sqs_queue.processing_dlq
aws_sqs_queue_redrive_policy.processing
aws_sqs_queue_redrive_allow_policy.processing_dlq
```

The module also exports the name, ARN, and URL for both queues.

## Resource Naming

Queue names are scoped by project and environment:

```text
${project_name}-${environment}-processing
${project_name}-${environment}-processing-dlq
```

Default local values produce:

```text
clouddoc-dev-processing
clouddoc-dev-processing-dlq
```

The approved environments are:

```text
dev
staging
prod
```

## Shared Tags

The AWS provider applies shared tags:

```text
Project
Environment
ManagedBy
Component
```

Each queue also receives:

```text
Name
QueueRole
```

Queue roles are:

```text
processing-source
processing-dead-letter
```

## Processing Queue

The source queue is a standard SQS queue.

```text
FIFO: false
Delay: 0 seconds
Visibility timeout: 720 seconds
Message retention: 345600 seconds
Encryption: SQS-managed server-side encryption
```

### Standard Queue Decision

The processing workflow does not require global ordering.

The application is designed for at-least-once delivery and idempotent effects, so duplicate delivery is handled by authoritative state transitions rather than FIFO deduplication.

A standard queue also preserves compatibility with the planned direct S3 event-notification topology.

### Visibility Timeout

The processing queue uses:

```text
720 seconds
```

This reserves a future Processor Lambda timeout budget of:

```text
120 seconds
```

with a six-times visibility-timeout margin.

The Lambda resource is intentionally deferred, but the queue is provisioned with the approved runtime budget so later event-source mapping does not require redesigning the queue.

### Message Retention

The processing queue retains messages for:

```text
345600 seconds
4 days
```

This provides bounded source-queue retention while relying on the dead-letter queue for longer investigation.

## Processing Dead-Letter Queue

The dead-letter queue is also a standard SQS queue.

```text
FIFO: false
Delay: 0 seconds
Visibility timeout: 180 seconds
Message retention: 1209600 seconds
Encryption: SQS-managed server-side encryption
```

### Retention

The dead-letter queue retains messages for:

```text
1209600 seconds
14 days
```

Its retention period is intentionally longer than the source queue retention period.

This gives operators more time to investigate exhausted deliveries without expanding normal processing retention.

### Visibility Timeout

The dead-letter queue uses:

```text
180 seconds
```

The future DLQ Reconciler Lambda is expected to perform a narrow DynamoDB-backed control-plane workflow rather than document retrieval or AI inference.

Its timeout and event-source mapping remain separate infrastructure decisions.

## Encryption

Both queues enable:

```hcl
sqs_managed_sse_enabled = true
```

CloudDoc uses SQS-managed encryption instead of a customer-managed KMS key in this slice.

This provides explicit encryption at rest without introducing:

- KMS key-policy administration
- additional IAM permissions
- cross-account key ownership
- KMS request costs
- key rotation operations

A customer-managed key can be introduced later when a compliance, cross-account, or ownership requirement justifies the operational complexity.

## Redrive Policy

The processing queue uses a dedicated Terraform resource:

```text
aws_sqs_queue_redrive_policy.processing
```

The policy declares:

```text
Dead-letter target: processing DLQ
Maximum receive count: 3
```

The effective flow is:

```text
delivery attempt 1
    ↓ failure
delivery attempt 2
    ↓ failure
delivery attempt 3
    ↓ failure
processing DLQ
```

`maxReceiveCount` is represented as an integer.

The redrive policy does not define business failure semantics. It only defines SQS delivery behavior.

## Redrive Allow Policy

The processing DLQ uses:

```text
aws_sqs_queue_redrive_allow_policy.processing_dlq
```

The policy declares:

```text
redrivePermission = byQueue
sourceQueueArns = [processing queue ARN]
```

Only the CloudDoc processing queue may designate the processing DLQ as its dead-letter destination.

The policy does not replay messages and does not return messages to the source queue.

Automatic replay remains intentionally absent.

## Terraform Outputs

The root module exports:

```text
processing_queue_name
processing_queue_arn
processing_queue_url

processing_dlq_name
processing_dlq_arn
processing_dlq_url
```

These outputs form the infrastructure integration boundary for later slices.

They will support:

- S3 queue policies
- S3 event notifications
- Lambda IAM policies
- Lambda event-source mappings
- CloudWatch alarms
- operational inspection

Outputs expose identifiers only. They do not expose credentials or message content.

## Terraform Root Configuration

The Terraform root requires:

```text
Terraform >= 1.7.0 and < 2.0.0
AWS provider ~> 6.0
```

The AWS Region is an explicit input.

The project name defaults to:

```text
clouddoc
```

The environment defaults to:

```text
dev
```

The root currently uses local state.

Remote state is intentionally deferred until shared or automated deployment is introduced.

## Offline Testing

The queue topology is covered by:

```text
infra/terraform/tests/processing_queues.tftest.hcl
```

The test uses a mocked AWS provider and executes Terraform planning without creating real resources.

The test verifies:

- environment-scoped naming
- shared tags
- queue-specific tags
- standard queue behavior
- SQS-managed encryption
- source visibility timeout
- source retention
- DLQ visibility timeout
- DLQ retention
- longer DLQ retention
- maximum receive count
- dedicated DLQ target
- restrictive redrive permission
- exactly one authorized source queue
- queue outputs

No AWS credentials are required for the offline test path.

## Validation Commands

```bash
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform init -backend=false
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
```

Repository validation remains:

```bash
python -m ruff format . --check
python -m ruff check .
python -m pytest
git diff --check
```

This slice does not require:

```text
terraform apply
terraform destroy
real AWS integration tests
```

## Security Boundary

The queue topology establishes several infrastructure controls:

- both queues are encrypted at rest
- queue names are environment-scoped
- the DLQ accepts only the approved source queue
- no credentials are stored in Terraform configuration
- Terraform state files remain excluded from Git
- automatic replay is absent
- no public queue access policy is introduced

IAM permissions and the future S3 queue policy remain intentionally separate.

## Failure Modes

### Visibility Timeout Is Too Short

A message may become visible while a Processor Lambda invocation is still running.

That can increase duplicate processing and concurrency pressure.

The approved timeout margin reduces this risk.

### Source Retention Is Too Short

Messages may expire before delivery recovers from an extended outage.

The four-day value balances recovery time and bounded retention for the initial environment.

### DLQ Retention Is Too Short

Exhausted messages may disappear before investigation.

The DLQ therefore uses the fourteen-day maximum approved for this slice.

### Redrive Allow Policy Is Too Broad

Unrelated queues could use the CloudDoc processing DLQ.

The `byQueue` policy restricts the destination to one source queue ARN.

### Redrive Policy Is Missing

Poison messages could remain in the processing queue indefinitely.

The bounded receive count moves exhausted messages to the dedicated DLQ.

### Automatic Replay Is Enabled Prematurely

Poison messages could repeatedly return to the processing queue without investigation.

Automatic replay is intentionally deferred.

## Cost Posture

Standard SQS queues and SQS-managed encryption keep the initial infrastructure operationally simple.

This slice does not introduce:

- provisioned throughput
- KMS customer-managed key requests
- Lambda execution
- S3 storage
- CloudWatch alarms
- cross-region resources

The infrastructure establishes the durable queue boundary before compute and observability costs are introduced.

## Intentionally Deferred

The following are separate infrastructure slices:

- private document-storage S3 bucket
- S3 queue access policy
- S3 ObjectCreated notification
- Processor Lambda packaging and deployment
- DLQ Reconciler Lambda packaging and deployment
- Lambda execution roles
- least-privilege IAM policies
- SQS event-source mappings
- `ReportBatchItemFailures`
- Lambda timeout configuration
- reserved and maximum concurrency
- CloudWatch log groups
- metrics and alarms
- remote Terraform state
- CI plan workflow
- controlled deployment workflow
- operator replay tooling
- deployed AWS validation

## Follow-Up Work

The next infrastructure slice should connect the document-ingestion boundary:

```text
private documents S3 bucket
    ↓ bucket policy and queue policy
S3 ObjectCreated notification
    ↓
processing queue
```

Lambda packaging, IAM, and event-source mappings should follow as independent, reviewable changes.