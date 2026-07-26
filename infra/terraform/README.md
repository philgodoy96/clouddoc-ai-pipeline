# Terraform Infrastructure

This directory contains the executable Terraform root for CloudDoc AI Pipeline.

Infrastructure is introduced in reviewable slices. The current root provisions
the document-processing SQS topology, the private source-document S3 ingestion
boundary, and S3-to-SQS event delivery. Lambda packaging, IAM roles, and
deployed AWS environments remain separate follow-up work.

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

The processing queue owns delivery buffering, retries, and dead-letter
movement. DynamoDB remains the authoritative source for `DocumentJob`
lifecycle state.

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

Terraform tests cover both:

```text
processing queue topology
document ingestion topology
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

Future Lambda and IAM slices will consume these identifiers. Outputs expose
resource identifiers only; they do not expose credentials or object content.

## Security

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

Malware scanning, Object Lock, access logging, and CloudTrail data events are
not part of this slice.

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

## Related documentation

- [Processing queue infrastructure](../../docs/architecture/processing-queue-infrastructure.md)
- [ADR-015: Provision standard processing queues with Terraform](../../docs/adr/ADR-015-provision-standard-processing-queues-with-terraform.md)
- [Document ingestion infrastructure](../../docs/architecture/document-ingestion-infrastructure.md)
- [ADR-016: Provision private versioned document ingestion](../../docs/adr/ADR-016-provision-private-versioned-document-ingestion.md)
