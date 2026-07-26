# Terraform Infrastructure

This directory contains the executable Terraform root for CloudDoc AI Pipeline.

Infrastructure is introduced in reviewable slices. The current root provisions
the document-processing SQS topology, the private source-document S3 ingestion
boundary, and authoritative DynamoDB document-job state. Lambda packaging, IAM
roles, event-source mappings, and deployed AWS environments remain separate
follow-up work.

## Current resources

### Processing queues

```text
aws_sqs_queue.processing
aws_sqs_queue.processing_dlq
aws_sqs_queue_redrive_policy.processing
aws_sqs_queue_redrive_allow_policy.processing_dlq
```

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

Redrive behavior:

```text
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

## Ownership boundary

Each store owns a distinct concern:

```text
S3 owns raw document bytes and object versions
SQS owns delivery attempts and redrive
DynamoDB owns authoritative DocumentJob lifecycle state
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

Terraform native tests cover:

```text
processing queue topology
document ingestion topology
document-jobs table topology
```

Tests use a mocked AWS provider and create no resources.

## Outputs

Queue outputs:

```text
processing_queue_name
processing_queue_arn
processing_queue_url
processing_dlq_name
processing_dlq_arn
processing_dlq_url
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

Future Lambda environment variables and execution policies will consume these
identifiers. Outputs expose resource identifiers only; they do not expose
credentials or object content.

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

Both queues enable SQS-managed encryption at rest. The documents bucket uses
AES256 default encryption and an explicit `aws:SecureTransport` deny.

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

## State management and deployment safety

The root intentionally uses local state for offline validation.

Remote state, shared backends, and controlled deployment workflows remain
deferred until shared or automated deployment is introduced.

Do not treat `terraform apply` as part of the documented validation path for
this repository slice. Offline `init`, `fmt`, `validate`, and `test` are the
approved checks.

Terraform state files remain excluded from Git.

## Intentionally deferred

The following remain intentionally sequenced follow-up work:

```text
API Lambda IAM
Processor Lambda S3 access
Lambda packaging and deployment
SQS event-source mappings
CORS
CloudTrail S3 data events
S3 access logging
customer-managed KMS
malware scanning
quarantine workflow
real AWS deployment validation
```

Additional deferred items from the queue slice also remain separate:

```text
DLQ Reconciler Lambda packaging and deployment
ReportBatchItemFailures
Lambda timeout and concurrency controls
CloudWatch log groups, metrics, and alarms
remote Terraform state
CI plan and controlled deployment workflows
operator replay tooling
```

Document-job state capabilities remain intentionally sequenced follow-up work:

```text
Lambda table permissions
Lambda environment variables
DynamoDB Streams
TTL and retention automation
secondary indexes
global tables
DAX
customer-managed KMS keys
Contributor Insights
CloudWatch alarms
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
