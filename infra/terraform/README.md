# Terraform Infrastructure

This directory contains the executable Terraform root for CloudDoc AI Pipeline.

Infrastructure is introduced in reviewable slices. The current root declares:

```text
processing SQS topology
private S3 document ingestion
authoritative DynamoDB document-job state
four Lambda runtime functions
four independent Lambda execution roles
four managed CloudWatch log groups
the processing queue consumer IAM boundary
the processing queue to Processor Lambda event source mapping
the processing DLQ to Dead-Letter Reconciler event source mapping
the Dead-Letter Reconciler processing-DLQ consumer boundary
the reconciliation failure quarantine queue
the processing-DLQ-to-quarantine redrive path
```

API Gateway, Bedrock permissions, CloudWatch alarms, automatic replay,
operator recovery tooling, and real AWS deployment remain separate follow-up
work.

## Current resources

### Processing queues

```text
aws_sqs_queue.processing
aws_sqs_queue.processing_dlq
aws_sqs_queue_redrive_policy.processing
aws_sqs_queue_redrive_allow_policy.processing_dlq
aws_sqs_queue.reconciliation_failures
aws_sqs_queue_redrive_policy.processing_dlq_reconciliation
aws_sqs_queue_redrive_allow_policy.reconciliation_failures
```

Queue names are scoped by project and environment:

```text
${project_name}-${environment}-processing
${project_name}-${environment}-processing-dlq
${project_name}-${environment}-reconciliation-failures
```

Default local values produce:

```text
clouddoc-dev-processing
clouddoc-dev-processing-dlq
clouddoc-dev-reconciliation-failures
```

Processing queue:

```text
FIFO: false
Delay: 0 seconds
Visibility timeout: 720 seconds
Message retention: 345600 seconds (4 days)
Encryption: SQS-managed server-side encryption
```

Processing dead-letter queue:

```text
FIFO: false
Delay: 0 seconds
Visibility timeout: 180 seconds
Message retention: 1209600 seconds (14 days)
Encryption: SQS-managed server-side encryption
```

Primary redrive behavior:

```text
processing queue → processing DLQ after three receives
maxReceiveCount = 3
deadLetterTargetArn = processing DLQ
redrivePermission = byQueue
sourceQueueArns = [processing queue ARN]
```

### Document ingestion

```text
data.aws_caller_identity.current
aws_s3_bucket.documents
aws_s3_bucket_public_access_block.documents
aws_s3_bucket_ownership_controls.documents
aws_s3_bucket_server_side_encryption_configuration.documents
aws_s3_bucket_versioning.documents
aws_s3_bucket_lifecycle_configuration.documents
data.aws_iam_policy_document.documents_https_only
aws_s3_bucket_policy.documents
data.aws_iam_policy_document.processing_queue_allow_s3
aws_sqs_queue_policy.processing_s3_publish
aws_s3_bucket_notification.documents
```

S3 bucket configuration:

```text
account- and environment-scoped name
force_destroy disabled
all public access blocked
BucketOwnerEnforced
AES256 encryption
versioning enabled
30-day current and noncurrent retention
one-day incomplete multipart cleanup
HTTPS-only access
```

S3-to-SQS event delivery:

```text
principal = s3.amazonaws.com
action = sqs:SendMessage
SourceArn = documents bucket ARN
SourceAccount = current account ID
event = s3:ObjectCreated:*
prefix = documents/
suffix = source.txt
destination = processing queue
```

Infrastructure filters reduce event noise. They do not replace application
validation of the canonical object key:

```text
documents/{job_id}/source.txt
```

### Document-job state

```text
aws_dynamodb_table.document_jobs
```

Table configuration:

```text
environment-scoped name
PAY_PER_REQUEST billing
PK string partition key
no sort key
STANDARD table class
point-in-time recovery enabled
production deletion protection
DynamoDB Streams disabled
no TTL
no secondary indexes
DynamoDB default encryption at rest
```

### Lambda runtime functions

```text
aws_lambda_function.create_job
aws_lambda_function.get_job
aws_lambda_function.processor
aws_lambda_function.dead_letter_reconciler
```

Each function has a separate least-privilege execution identity:

```text
aws_iam_role.create_job
aws_iam_role.get_job
aws_iam_role.processor
aws_iam_role.dead_letter_reconciler
```

Managed CloudWatch log groups:

```text
aws_cloudwatch_log_group.create_job
aws_cloudwatch_log_group.get_job
aws_cloudwatch_log_group.processor
aws_cloudwatch_log_group.dead_letter_reconciler
```

| Function | Handler | Memory | Timeout | Purpose |
| --- | --- | --- | --- | --- |
| Create Job | `clouddoc.handlers.create_job.lambda_handler` | 256 MB | 10 seconds | Creates authoritative job state and returns a presigned upload URL |
| Get Job | `clouddoc.handlers.get_job.lambda_handler` | 256 MB | 5 seconds | Retrieves one authoritative document job |
| Document Processor | `clouddoc.handlers.process_uploaded_document.lambda_handler` | 1024 MB | 120 seconds | Processes uploaded source documents and persists attempt-aware outcomes |
| Dead-Letter Reconciler | `clouddoc.handlers.reconcile_dead_lettered_document.lambda_handler` | 512 MB | 30 seconds | Reconciles exhausted deliveries into authoritative job state |

#### Runtime platform

All four functions use:

```text
Python 3.12
x86_64
Zip package type
JSON logging
publish disabled
```

The runtime architecture matches the deterministic package builder. Changing the
runtime or architecture requires updating the packaging contract in the same
approved engineering decision.

#### Shared artifact

All functions consume the same deployment package:

```text
artifacts/lambda/clouddoc-app.zip
```

The build system produces the ZIP. Terraform consumes the ZIP. `source_code_hash`
is calculated when the artifact exists. Offline `validate` and mocked tests remain
possible without the generated artifact. Real deployment must build and verify
the artifact first.

Package the shared artifact:

```bash
make lambda-package
```

Build and verify the artifact SHA-256:

```bash
make lambda-package-check
```

Generated ZIP and checksum files under `artifacts/lambda/` are local build
outputs. Do not commit them.

#### Runtime environment

Every function receives the same non-secret environment map:

```text
CLOUDDOC_JOBS_TABLE_NAME
CLOUDDOC_DOCUMENTS_BUCKET_NAME
CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

Configured values:

```text
upload URL expiration = 900 seconds
processing lease duration = 300 seconds
maximum document size = 65536 bytes
```

Resource names identify tables and buckets; they do not grant resource access.
Access remains controlled by each function's execution role. Secrets are not
stored in Lambda environment variables.

#### IAM boundaries

| Function | Permissions |
| --- | --- |
| Create Job | `dynamodb:PutItem`; `s3:PutObject` under `documents/*` |
| Get Job | `dynamodb:GetItem` |
| Processor | `dynamodb:GetItem`; `dynamodb:PutItem`; `s3:GetObject`; `s3:GetObjectVersion` under `documents/*`; dedicated processing-queue consumer inline policy |
| Dead-Letter Reconciler | `dynamodb:GetItem`; `dynamodb:PutItem`; dedicated processing-DLQ consumer inline policy |

Each function has its own role. Each role trusts only `lambda.amazonaws.com`.
Logging permissions target only that function's log group streams.
`logs:CreateLogGroup` is not granted. No AWS-managed basic execution policy is
attached.

Bedrock permissions remain intentionally absent. Provider integration remains a
separate follow-up slice.

#### Logging

Terraform owns four `/aws/lambda/<function-name>` log groups and their retention:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

Terraform owns log-group creation and retention. Runtime roles may create streams
and put events only within their own log group.

### Processing queue consumer

```text
aws_lambda_event_source_mapping.processing_queue
data.aws_iam_policy_document.processor_queue_consumer
aws_iam_role_policy.processor_queue_consumer
```

Terraform declares the enabled event source mapping from the processing queue to
the Document Processor Lambda, plus a dedicated Processor queue-consumer inline
policy.

### Dead-letter reconciliation consumer

```text
aws_lambda_event_source_mapping.processing_dlq
data.aws_iam_policy_document.dead_letter_reconciler_queue_consumer
aws_iam_role_policy.dead_letter_reconciler_queue_consumer
```

Terraform declares the enabled event source mapping from the processing DLQ to
the Dead-Letter Reconciler Lambda, plus a dedicated Dead-Letter Reconciler
processing-DLQ inline policy.

## Processing flow

```text
S3 ObjectCreated
    → processing SQS queue
    → Lambda event source mapping
    → Document Processor Lambda
    → S3 / DynamoDB / future AI provider
```

## Failure flow

```text
processing queue
    → Document Processor
    → processing DLQ after three receives
    → Dead-Letter Reconciler
    → reconciliation failure quarantine after three reconciliation receives
```

Ownership remains split:

```text
DynamoDB owns authoritative DocumentJob state
SQS owns delivery, retry, and redrive
the quarantine queue owns terminal operational evidence
```

## Quarantine queue

Terraform declares a terminal reconciliation failure quarantine:

```text
Standard queue
zero delay
180-second visibility timeout
14-day retention
SQS-managed encryption
no consumer
no redrive policy
```

Queue tags:

```text
QueueRole = dead-letter-reconciliation-quarantine
```

The quarantine queue is terminal in the current architecture. It preserves
operational evidence for investigation; it does not continue the processing
pipeline.

## Processing-DLQ redrive

The processing DLQ now redrives exhausted reconciliation attempts:

```text
processing DLQ maxReceiveCount = 3
dead-letter target = reconciliation failure quarantine
```

The quarantine queue accepts redrive only from the processing DLQ:

```text
redrivePermission = byQueue
source = processing DLQ only
```

The primary processing redrive path is unchanged:

```text
processing queue → processing DLQ after three receives
```

## Queue-consumer IAM

The Processor receives a dedicated inline SQS consumer policy that grants exactly:

```text
sqs:DeleteMessage
sqs:GetQueueAttributes
sqs:ReceiveMessage
```

The resource is restricted to:

```text
processing queue ARN only
```

The Processor cannot:

```text
send messages
purge the queue
administer the queue
consume the DLQ
```

No AWS-managed SQS execution policy is attached. No KMS permission is needed
because the queue uses SQS-managed encryption.

## Reconciler IAM

The Dead-Letter Reconciler receives a dedicated inline SQS consumer policy that
grants exactly:

```text
sqs:DeleteMessage
sqs:GetQueueAttributes
sqs:ReceiveMessage
```

The resource is restricted to:

```text
processing DLQ ARN only
```

The reconciler cannot:

```text
consume the primary processing queue
consume the quarantine queue
send messages
move messages
purge or administer queues
replay work
```

No AWS-managed SQS execution policy is attached. No KMS permission is needed
because the queues use SQS-managed encryption.

## Event source mapping

The processing-queue mapping is configured as:

```text
enabled = true
batch size = 1
maximum batching window = 0 seconds
ReportBatchItemFailures enabled
maximum concurrency = 5
```

Decisions:

```text
batch size 1 creates one document-processing failure and cost domain
zero batching window avoids unnecessary delay
partial batch reporting matches the handler contract
maximum concurrency 5 bounds AI-processing parallelism and cost
```

## Reconciliation event source mapping

The processing-DLQ mapping is configured as:

```text
enabled = true
batch size = 1
maximum batching window = 0 seconds
ReportBatchItemFailures enabled
maximum concurrency = 2
```

Decisions:

```text
batch size 1 isolates one exhausted message
zero batching window avoids unnecessary delay
partial batch reporting matches the handler
maximum concurrency 2 prevents a failure storm from creating a reconciliation storm
```

## Timeout and retry contract

The Processor and processing queues share this contract:

```text
Processor timeout = 120 seconds
processing queue visibility timeout = 720 seconds
ratio = 6x
maxReceiveCount = 3
processing queue retention = 4 days
processing DLQ retention = 14 days
```

Three receives are a cost-aware decision for potentially expensive AI
processing. The threshold isolates exhausted work earlier rather than repeating
inference indefinitely. It is not claimed to be universally optimal and should
be revisited after deployed measurement.

The Dead-Letter Reconciler and processing DLQ share this contract:

```text
Dead-Letter Reconciler timeout = 30 seconds
processing DLQ visibility timeout = 180 seconds
ratio = 6x
```

Reserved concurrency remains unconfigured and is represented as `null` in
Terraform plan semantics.

## Concurrency

Event-source maximum concurrency is configured. Lambda reserved concurrency
remains unconfigured.

In plan semantics, the unconfigured reserved concurrency is represented as
`null`.

Reserved concurrency must be designed with account-level concurrency, Bedrock
quotas, and all future invocation sources before it is introduced.

## No automatic replay

This root deliberately declares no automatic replay path:

```text
the reconciler has no SendMessage permission
the reconciler has no SQS message-move permission
the quarantine queue has no consumer
no resource routes messages back to the processing queue
```

Future replay requires a separately approved operator workflow with
authorization, auditability, idempotency, and rate controls.

## Ownership boundary

Each store owns a distinct concern:

```text
S3 owns raw document bytes and object versions
SQS owns delivery attempts and redrive
DynamoDB owns authoritative DocumentJob lifecycle state
the quarantine queue owns terminal operational evidence
```

SQS delivery state does not determine business lifecycle state. Message
visibility, receive counts, and dead-letter placement describe transport
retries only. Authoritative `DocumentJob` status lives in DynamoDB.

## Configuration

Required and optional inputs:

| Variable | Default | Purpose |
| --- | --- | --- |
| `aws_region` | _(required)_ | AWS Region for all resources |
| `project_name` | `clouddoc` | Stable project identifier in names and tags |
| `environment` | `dev` | One of `dev`, `staging`, `prod` |

Example values are provided in `terraform.tfvars.example`:

```hcl
aws_region   = "us-east-1"
project_name = "clouddoc"
environment  = "dev"
```

The AWS account ID is read through `data.aws_caller_identity.current` and
contributes to the documents-bucket name. There is no account-ID input
variable.

Example bucket name:

```text
clouddoc-dev-123456789012-documents
```

The document-jobs table name is derived from the project name, environment, and
`document-jobs` suffix:

```text
${project_name}-${environment}-document-jobs
```

Examples:

```text
clouddoc-dev-document-jobs
clouddoc-staging-document-jobs
clouddoc-prod-document-jobs
```

Production deletion protection is derived from `environment`. There is no
separate deletion-protection variable:

```text
dev = disabled
staging = disabled
prod = enabled
```

Shared provider tags:

```text
Project
Environment
ManagedBy
Component
```

## Initialization and validation

Local offline validation uses local state and does not require remote backend
configuration:

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
terraform test
```

Terraform native tests now cover:

```text
processing queue topology
document ingestion topology
document-jobs table topology
Lambda runtime and IAM topology
processing event-source topology
dead-letter reconciliation topology
```

The current validated total is:

```text
17 passed, 0 failed
```

The dead-letter reconciliation tests validate:

```text
quarantine topology
redrive chain
reconciler least privilege
absence of replay actions
event-source mapping
partial failure behavior
concurrency
timeout ratio
retention
encryption
outputs
```

Tests use a mocked AWS provider and create no resources. Plan-time computed
values use deterministic overrides. The tests validate the dedicated inline
policy identity rather than comparing rendered policy JSON that remains unknown
during plan.

## Outputs

Queue outputs:

```text
processing_queue_name
processing_queue_arn
processing_queue_url
processing_dlq_name
processing_dlq_arn
processing_dlq_url
reconciliation_failures_queue_name
reconciliation_failures_queue_arn
reconciliation_failures_queue_url
```

Document-ingestion outputs:

```text
documents_bucket_name
documents_bucket_arn
```

Document-job state outputs:

```text
document_jobs_table_name
document_jobs_table_arn
```

Lambda runtime outputs:

```text
create_job_function_name
create_job_function_arn
get_job_function_name
get_job_function_arn
processor_function_name
processor_function_arn
dead_letter_reconciler_function_name
dead_letter_reconciler_function_arn
```

These identifiers will support future API Gateway, alarm, runbook, operator
inspection, and deployment verification integrations. Outputs expose resource
identifiers only; they do not expose credentials or object content.

## Security and durability

The current root establishes these controls:

```text
public access blocked
ACLs disabled
SSE-S3
HTTPS-only deny
S3 principal restricted to SendMessage
SourceArn and SourceAccount restrictions
versioning
bounded lifecycle retention
```

The processing, processing-DLQ, and quarantine queues enable SQS-managed
encryption at rest. The documents bucket uses AES256 default encryption and an
explicit `aws:SecureTransport` deny.

The document-jobs table declares these durability and security controls:

```text
PITR enabled
production deletion protection
DynamoDB default encryption
no resource-based cross-account policy
no TTL without an approved retention contract
no streams without an approved consumer
no speculative indexes
```

Malware scanning, Object Lock, access logging, and CloudTrail data events are
not part of this slice. AWS Backup, global tables, DAX, Contributor Insights,
customer-managed KMS, and CloudWatch alarms are not declared for the table.

## Retention nuance

For Standard queues, the original enqueue timestamp is preserved when messages
move to a DLQ. Effective remaining quarantine retention therefore depends on
message age. Messages do not automatically receive a fresh full 14 days after
redrive.

## Cost posture

The document-jobs table makes these intentional cost decisions:

```text
PAY_PER_REQUEST for an unmeasured event-driven workload
no unused secondary indexes
no streams
no global tables
no DAX
no customer-managed KMS requests
```

Lambda runtime cost decisions:

```text
small control-plane memory budgets
explicit timeouts
explicit log retention
no provisioned concurrency
no versions or aliases
no VPC attachment
no tracing
one shared artifact
```

Processing-queue consumer cost decisions:

```text
batch size 1
maximum concurrency 5
three-receive redrive threshold
no provisioned concurrency
no provisioned pollers
no automatic DLQ replay
```

These settings prioritize bounded AI parallelism and predictable per-document
failure domains over maximum throughput.

Dead-letter reconciliation cost decisions:

```text
batch size 1
maximum concurrency 2
three reconciliation receives
14-day bounded quarantine retention
no provisioned concurrency
no provisioned pollers
no automatic replay
```

These settings prioritize bounded retry cost, failure isolation, and operator
signal.

The Processor memory budget is intentionally larger because it owns document
loading, validation, and AI orchestration. That budget requires deployed
measurement later.

## State management and deployment safety

The root intentionally uses local state for offline validation.

Remote state, shared backends, and controlled deployment workflows remain
deferred until shared or automated deployment is introduced.

Do not treat `terraform apply` as part of the documented validation path for
this repository slice. Offline `init`, `fmt`, `validate`, and `test` are the
approved checks.

Artifact absence is accepted for offline validation but not for real
deployment. A controlled deployment workflow must build and verify
`artifacts/lambda/clouddoc-app.zip` before any real plan or apply.

Terraform state files remain excluded from Git.

## Intentionally deferred

The following remain intentionally sequenced follow-up work:

```text
API Gateway
Lambda invoke permissions
quarantine consumer
automatic replay
operator replay API
message-move permissions
processing DLQ depth alarm
quarantine depth alarm
message-age alarm
reconciler failure alarm
manual recovery runbook
reserved concurrency
provisioned concurrency
provisioned pollers
batch size greater than 1
event filtering
queue-age alarms
DLQ-depth alarms
Lambda throttling alarms
Bedrock integration
Bedrock permissions
CloudWatch alarms and dashboards
X-Ray
Secrets Manager
versions and aliases
artifact publication to S3
code signing
real AWS deployment
load testing
failure injection
recovery testing
```

Additional deferred items from earlier slices also remain separate:

```text
CORS
CloudTrail S3 data events
S3 access logging
customer-managed KMS
malware scanning
quarantine workflow
remote Terraform state
CI plan and controlled deployment workflows
operator replay tooling
DynamoDB Streams
TTL and retention automation
secondary indexes
global tables
DAX
Contributor Insights
AWS Backup plans
cross-region disaster recovery
real AWS deployment and restore validation
```

## Related documentation

- [Processing queue infrastructure](../../docs/architecture/processing-queue-infrastructure.md)
- [ADR-015: Provision standard processing queues with Terraform](../../docs/adr/ADR-015-provision-standard-processing-queues-with-terraform.md)
- [Document ingestion infrastructure](../../docs/architecture/document-ingestion-infrastructure.md)
- [ADR-016: Provision private versioned document ingestion](../../docs/adr/ADR-016-provision-private-versioned-document-ingestion.md)
- [Document job state infrastructure](../../docs/architecture/document-job-state-infrastructure.md)
- [ADR-018: Provision authoritative document job state](../../docs/adr/ADR-018-provision-authoritative-document-job-state.md)
- [Lambda runtime infrastructure](../../docs/architecture/lambda-runtime-infrastructure.md)
- [ADR-019: Provision separate Lambda runtime boundaries](../../docs/adr/ADR-019-provision-separate-lambda-runtime-boundaries.md)
- [Processing queue consumer infrastructure](../../docs/architecture/processing-queue-consumer-infrastructure.md)
- [ADR-020: Connect processing queue to Processor Lambda](../../docs/adr/ADR-020-connect-processing-queue-to-processor-lambda.md)
- [Dead-letter reconciliation infrastructure](../../docs/architecture/dead-letter-reconciliation-infrastructure.md)
- [ADR-021: Connect processing DLQ to Reconciler Lambda](../../docs/adr/ADR-021-connect-processing-dlq-to-reconciler-lambda.md)
