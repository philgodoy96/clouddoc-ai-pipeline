# Document Ingestion Infrastructure

## Status

Implemented as an incremental Terraform infrastructure slice.

This document describes how CloudDoc provisions a private, versioned Amazon S3 bucket and routes canonical document-upload events to the existing processing SQS queue.

## Purpose

CloudDoc accepts source documents through presigned uploads and processes them asynchronously.

The infrastructure path is:

```text
Client
    ↓ presigned PUT
Private documents bucket
    ↓ s3:ObjectCreated:*
Processing queue
```

The bucket stores raw document bytes.

SQS owns delivery buffering, retries, and dead-letter movement.

DynamoDB remains the authoritative owner of the `DocumentJob` lifecycle.

An S3 object-created event does not independently authorize a business-state transition.

## Provisioned Resources

The Terraform root provisions:

```text
data.aws_caller_identity.current

aws_s3_bucket.documents
aws_s3_bucket_public_access_block.documents
aws_s3_bucket_ownership_controls.documents
aws_s3_bucket_server_side_encryption_configuration.documents
aws_s3_bucket_versioning.documents
aws_s3_bucket_lifecycle_configuration.documents
aws_s3_bucket_policy.documents

data.aws_iam_policy_document.documents_https_only
data.aws_iam_policy_document.processing_queue_allow_s3
aws_sqs_queue_policy.processing_s3_publish

aws_s3_bucket_notification.documents
```

The root also exports:

```text
documents_bucket_name
documents_bucket_arn
```

## Bucket Naming

The bucket name is account- and environment-scoped:

```text
${project_name}-${environment}-${account_id}-documents
```

Example:

```text
clouddoc-dev-123456789012-documents
```

The AWS account ID reduces collision risk in the global S3 bucket namespace without introducing an additional random provider.

## Ownership Boundary

S3 owns:

```text
raw document bytes
object metadata
object versions
upload-completion events
```

SQS owns:

```text
delivery buffering
receive attempts
visibility timeout
redrive to the processing DLQ
```

DynamoDB owns:

```text
DocumentJob status
processing-attempt ownership
terminal results
terminal failures
dead state
```

The application still validates the expected job, bucket, object key, metadata, content type, and size before processing.

## Private Access Controls

The bucket enables all four S3 public-access-block controls:

```text
block_public_acls = true
block_public_policy = true
ignore_public_acls = true
restrict_public_buckets = true
```

This creates an explicit bucket-level protection boundary independent of account-level settings.

No public bucket policy or public ACL is introduced.

## Object Ownership

The bucket uses:

```text
BucketOwnerEnforced
```

ACL-based object ownership is disabled.

Authorization is controlled through IAM and resource policies.

This avoids ownership ambiguity and keeps future presigned uploads aligned with bucket-owner control.

## Encryption

Default bucket encryption uses:

```text
AES256
```

This is Amazon S3 managed server-side encryption.

A customer-managed KMS key is intentionally deferred until there is a concrete compliance, cross-account, or key-ownership requirement.

## Versioning

Bucket versioning is enabled.

Repeated uploads to the same canonical object key create independent object versions rather than destructively replacing the only stored copy.

The S3 event contract may include a version ID, which allows later processing and investigation flows to identify the exact stored version.

## Lifecycle Management

The lifecycle rule applies to:

```text
documents/
```

The rule configures:

```text
current-version expiration: 30 days
noncurrent-version expiration: 30 days
abort incomplete multipart uploads: 1 day
```

The 30-day document-retention window exceeds the processing queue and processing DLQ retention windows.

This preserves source documents long enough for investigation and controlled replay while preventing indefinite storage.

The lifecycle configuration depends on bucket versioning because noncurrent-version retention has meaning only after versioning is enabled.

## HTTPS-Only Policy

The bucket policy contains one explicit deny statement:

```text
SID: DenyInsecureTransport
Effect: Deny
Action: s3:*
Principal: *
Condition: aws:SecureTransport = false
```

The policy covers:

```text
bucket ARN
bucket ARN/*
```

Any principal using non-TLS transport is denied even when another IAM policy would otherwise allow the request.

The policy does not grant access.

## S3-to-SQS Permission

The processing queue resource policy grants exactly:

```text
Principal: s3.amazonaws.com
Action: sqs:SendMessage
Resource: processing queue ARN
```

The permission is restricted through:

```text
ArnEquals aws:SourceArn = documents bucket ARN
StringEquals aws:SourceAccount = current AWS account ID
```

These conditions prevent unrelated buckets and accounts from publishing notifications to the queue.

The queue policy targets the processing queue, not the processing DLQ.

## Bucket Notification

The bucket has one Terraform-owned notification configuration:

```text
aws_s3_bucket_notification.documents
```

It sends events to the existing processing queue.

Configuration:

```text
event: s3:ObjectCreated:*
prefix: documents/
suffix: source.txt
```

The stable notification identifier is:

```text
document-upload-created
```

The notification explicitly depends on the processing queue policy so S3 can validate the destination after the required permission exists.

## Canonical Object-Key Boundary

The infrastructure filters reduce event noise through:

```text
prefix = documents/
suffix = source.txt
```

They do not fully validate the application contract:

```text
documents/{job_id}/source.txt
```

Terraform and S3 filters cannot validate:

```text
the exact number of path segments
the job identifier format
the existence of the related job
the expected content type
the expected object size
```

Those remain application responsibilities.

## At-Least-Once Delivery

S3 event notifications may be duplicated and are not globally ordered.

The processing queue is a standard queue and may also redeliver messages.

CloudDoc therefore does not depend on exactly-once delivery.

Correctness comes from:

```text
authoritative DynamoDB state
attempt ownership
idempotent lifecycle effects
conditional persistence
canonical event validation
```

## Terraform Outputs

The root exports:

```text
documents_bucket_name
documents_bucket_arn
```

These outputs provide a stable integration boundary for future:

```text
presigned-upload runtime settings
API Lambda IAM
Processor Lambda IAM
CloudWatch alarms
deployment inspection
```

No credentials or object content are exposed.

## Offline Testing

The ingestion topology is covered by:

```text
infra/terraform/tests/document_ingestion.tftest.hcl
```

The test uses:

```text
mock_provider "aws"
command = plan
```

It validates:

```text
account- and environment-scoped naming
force-destroy protection
bucket tags
public access blocking
BucketOwnerEnforced
AES256 encryption
versioning
current-version retention
noncurrent-version retention
multipart cleanup
HTTPS-only policy
S3 service principal
SendMessage-only queue permission
SourceArn restriction
SourceAccount restriction
processing-queue destination
ObjectCreated event wildcard
documents/ prefix
source.txt suffix
bucket outputs
```

The tests do not require AWS credentials or create real resources.

## Security Boundary

The infrastructure protects against:

### Public Document Exposure

Mitigation:

```text
all public-access-block settings enabled
no public resource policy
no public ACL ownership
```

### ACL Ownership Ambiguity

Mitigation:

```text
BucketOwnerEnforced
```

### Unencrypted Stored Objects

Mitigation:

```text
default AES256 encryption
```

### Non-TLS Access

Mitigation:

```text
explicit aws:SecureTransport deny
```

### Unapproved S3 Publishers

Mitigation:

```text
S3 service principal only
SourceArn restricted to the documents bucket
SourceAccount restricted to the current account
```

### Unexpected Object Notifications

Mitigation:

```text
documents/ prefix
source.txt suffix
application-level canonical-key validation
```

### Destructive Overwrite

Mitigation:

```text
bucket versioning
```

### Indefinite Storage

Mitigation:

```text
30-day current and noncurrent retention
multipart cleanup after one day
```

## Failure Modes

### Queue Policy Missing

S3 cannot validate or publish to the processing queue.

The bucket notification apply fails or delivery is unavailable.

### Notification Applied Before Queue Permission

S3 destination validation fails.

The explicit Terraform dependency preserves the required creation order.

### Incorrect Prefix or Suffix

Valid uploads do not generate processing messages.

### Filters Too Broad

Unrelated object creations increase queue traffic and processing noise.

Application validation still prevents unauthorized lifecycle effects.

### Duplicate Notification

The same upload may produce duplicate processing deliveries.

DynamoDB-backed idempotency handles duplicate effects.

### Object Overwrite

A new version and a new notification may be created for the same key.

Versioning preserves the earlier bytes.

### Retention Too Short

Source documents may expire before investigation or controlled replay.

The approved 30-day window exceeds queue investigation windows.

### Bucket-Name Collision

Bucket creation fails because the S3 namespace is global.

Including the AWS account ID materially reduces this risk.

### Policy Scope Becomes Broader

Unapproved buckets or accounts could publish to the processing queue.

Offline tests preserve the current least-privilege conditions.

## Cost Posture

This slice introduces:

```text
S3 object storage
S3 request costs
SQS messages generated by S3 notifications
```

Cost controls include:

```text
30-day lifecycle
noncurrent-version expiration
multipart cleanup
prefix and suffix event filtering
SSE-S3 instead of customer-managed KMS
```

The design does not add:

```text
replication
Object Lock
access logging
CloudTrail data events
malware scanning
KMS request costs
```

## Intentionally Deferred

The following remain separate implementation slices:

```text
API Lambda IAM for presigned uploads
Processor Lambda S3 read permissions
GetObjectVersion permissions
Lambda packaging and deployment
SQS event-source mappings
ReportBatchItemFailures
Lambda concurrency controls
CORS configuration
CloudTrail S3 data events
S3 access logging
replication
Object Lock
customer-managed KMS keys
malware scanning
quarantine workflow
operator replay tooling
real AWS deployment validation
```

CORS is intentionally deferred because the current project flow is API-first and no browser frontend is deployed.

## Validation Commands

```bash
terraform -chdir=infra/terraform fmt -check -recursive
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

No `terraform apply` or AWS credentials are required for the automated validation path.

## Follow-Up Work

The next infrastructure stage should package and deploy the application runtimes:

```text
API Lambda
Processor Lambda
DLQ Reconciler Lambda
```

That stage must define:

```text
deployment artifacts
runtime environment variables
separate execution roles
least-privilege S3 and DynamoDB permissions
SQS event-source mappings
partial batch failure configuration
timeouts and concurrency
CloudWatch log groups
```