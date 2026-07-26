# ADR-016: Provision Private Versioned Document Ingestion

## Status

Accepted

## Context

CloudDoc creates presigned upload URLs for canonical source-document keys and processes completed uploads asynchronously.

The application contract expects:

```text
documents/{job_id}/source.txt
```

The infrastructure needs a durable ingestion boundary that:

```text
stores raw source documents privately
preserves overwritten object versions
encrypts stored objects
rejects non-TLS access
routes upload-completion events to the processing queue
restricts which bucket may publish to that queue
retains documents long enough for investigation
remains testable without AWS credentials
```

S3 event notifications and SQS both provide at-least-once delivery semantics.

DynamoDB remains the authoritative owner of document-job business state.

## Decision

CloudDoc will provision one private, versioned S3 bucket and connect it directly to the existing standard processing SQS queue.

The bucket will use:

```text
account- and environment-scoped naming
force_destroy = false
all S3 public-access-block controls
BucketOwnerEnforced ownership
AES256 default encryption
versioning enabled
30-day current-version expiration
30-day noncurrent-version expiration
one-day multipart cleanup
HTTPS-only bucket policy
```

The processing queue will receive S3 notifications through a queue policy restricted by:

```text
principal = s3.amazonaws.com
action = sqs:SendMessage
resource = processing queue ARN
aws:SourceArn = documents bucket ARN
aws:SourceAccount = current AWS account ID
```

The bucket notification will use:

```text
event = s3:ObjectCreated:*
prefix = documents/
suffix = source.txt
destination = processing queue ARN
```

Terraform will own exactly one notification configuration resource for the bucket.

## Bucket Naming Decision

The bucket name will be:

```text
${project_name}-${environment}-${account_id}-documents
```

S3 bucket names exist in a global namespace within an AWS partition.

Including the account ID reduces collision risk while preserving a readable and deterministic name.

The design does not introduce the `random` provider.

## Private Access Decision

All public access controls will be enabled:

```text
block_public_acls
block_public_policy
ignore_public_acls
restrict_public_buckets
```

The bucket will not rely solely on account-level defaults.

The resource itself will declare the intended privacy boundary.

## Object Ownership Decision

The bucket will use:

```text
BucketOwnerEnforced
```

ACLs will not be used for object ownership or authorization.

Future presigned uploads and runtime access will rely on IAM and resource policies.

## Encryption Decision

Default bucket encryption will use:

```text
AES256
```

This provides S3-managed server-side encryption without introducing KMS key policies, additional IAM permissions, cross-account key ownership, or KMS request costs.

A customer-managed KMS key remains available when a concrete compliance or ownership requirement exists.

## Versioning Decision

Versioning will be enabled.

The canonical object key may be uploaded more than once.

Versioning ensures a later upload does not erase the only stored copy of the previous source document.

The existing processing event contract can preserve `versionId` when S3 supplies it.

## Lifecycle Decision

The lifecycle rule applies to:

```text
documents/
```

Current versions expire after:

```text
30 days
```

Noncurrent versions expire after:

```text
30 days
```

Incomplete multipart uploads are aborted after:

```text
1 day
```

The 30-day window exceeds the queue and DLQ retention windows and provides time for investigation and controlled replay.

The system does not retain source documents indefinitely.

## HTTPS-Only Decision

The bucket policy will deny:

```text
s3:*
```

for all principals when:

```text
aws:SecureTransport = false
```

The policy covers the bucket ARN and all object ARNs.

This is a deny-only policy and grants no access.

## S3-to-SQS Authorization Decision

The processing queue policy will grant exactly:

```text
s3.amazonaws.com
    → sqs:SendMessage
    → processing queue
```

The permission will require both:

```text
SourceArn = documents bucket ARN
SourceAccount = current AWS account ID
```

These conditions reduce confused-deputy risk and prevent unrelated buckets from publishing to the queue.

The policy will not target the DLQ.

## Notification Decision

The bucket will send:

```text
s3:ObjectCreated:*
```

events to the processing queue.

Using the wildcard covers all supported object-creation methods, including direct PUT, copy, form upload, and completed multipart upload.

The notification filters will be:

```text
prefix = documents/
suffix = source.txt
```

These filters reduce noise but do not replace application validation.

The application remains responsible for validating:

```text
exact canonical key shape
job identifier
expected bucket
content type
object size
job lifecycle state
```

## Single Notification Ownership Decision

Terraform will manage one:

```text
aws_s3_bucket_notification.documents
```

for the bucket.

Future queue, Lambda, or topic destinations must be added as blocks within the same resource.

Multiple Terraform notification resources for one bucket would create competing ownership of the same S3 notification configuration.

## Explicit Dependency Decision

The notification resource will explicitly depend on:

```text
aws_sqs_queue_policy.processing_s3_publish
```

S3 validates the destination when applying the notification configuration.

The queue permission must exist before that validation occurs.

## At-Least-Once Position

The system does not claim exactly-once S3 notification delivery or exactly-once SQS delivery.

Duplicate and out-of-order events are expected operational behaviors.

Correctness comes from:

```text
canonical event validation
DynamoDB authoritative state
processing-attempt ownership
idempotent terminal effects
conditional persistence
```

## Offline Test Decision

Terraform native tests will use:

```text
mock_provider "aws"
command = plan
```

The tests will validate:

```text
bucket naming
public access blocking
ownership controls
encryption
versioning
lifecycle
HTTPS-only policy
queue publishing policy
SourceArn and SourceAccount restrictions
notification event and filters
bucket outputs
```

The automated validation path will not require AWS credentials or create resources.

## Consequences

### Positive

- Source documents are stored privately.
- Stored objects are encrypted.
- Non-TLS access is explicitly rejected.
- ACL ownership ambiguity is removed.
- Previous uploads remain recoverable through versioning.
- Document retention is bounded.
- Abandoned multipart uploads are cleaned up.
- Only the approved bucket and account may publish to the processing queue.
- Notifications are filtered before entering SQS.
- The application retains exact canonical-key validation.
- The design remains compatible with at-least-once delivery.
- Infrastructure behavior is testable offline.
- Bucket identifiers are exported for future runtime integration.

### Negative

- Versioning increases storage usage until lifecycle cleanup occurs.
- A 30-day lifecycle may remove documents needed for investigations discovered later.
- S3 event notifications may be duplicated or delivered out of order.
- Direct S3-to-SQS delivery does not provide event transformation.
- Account-scoped naming reduces but does not mathematically eliminate global bucket-name collisions.
- Runtime IAM permissions are not yet provisioned.
- Real AWS destination validation remains untested until deployment.
- The notification filter cannot fully express the canonical object-key grammar.

## Alternatives Considered

### Use an Unversioned Bucket

Rejected.

A repeated upload could erase the only copy of the previous document bytes.

### Keep Objects Indefinitely

Rejected.

The portfolio system needs a deliberate retention and cost boundary.

Thirty days preserves the initial investigation window without indefinite storage.

### Use a Customer-Managed KMS Key Immediately

Deferred.

No current compliance, cross-account, or key-ownership requirement justifies the added policy and operational complexity.

### Rely Only on Default S3 Encryption

Rejected as an infrastructure-expression strategy.

The bucket explicitly declares the intended encryption algorithm so the security posture is testable and reviewable.

### Rely Only on Account-Level Public Access Block

Rejected.

The bucket resource must preserve its own explicit privacy boundary.

### Use ACLs for Upload Ownership

Rejected.

`BucketOwnerEnforced` removes ACL complexity and aligns authorization with IAM and bucket policies.

### Publish to the Processing DLQ

Rejected.

New uploads belong in the normal processing queue.

The DLQ is reserved for exhausted processing deliveries.

### Use EventBridge Instead of Direct S3-to-SQS Delivery

Deferred.

Direct delivery is simpler and sufficient for the current single-destination ingestion path.

EventBridge may become useful when routing, enrichment, archiving, or multiple independent consumers justify it.

### Use SNS Between S3 and SQS

Deferred.

The current design has one processing consumer and does not yet require fan-out.

### Use Only `s3:ObjectCreated:Put`

Rejected.

Presigned uploads may later use other valid object-creation mechanisms, and multipart completion should remain compatible with the ingestion boundary.

### Depend Only on Prefix and Suffix Filters

Rejected.

S3 filters cannot fully validate `documents/{job_id}/source.txt`.

The application retains exact validation.

### Create Multiple Bucket Notification Resources

Rejected.

S3 exposes one notification configuration per bucket.

Terraform must have one owner for that configuration.

### Add CORS Immediately

Deferred.

The current system is API-first and has no deployed browser frontend.

CORS will be introduced with a concrete browser-origin requirement.

### Add Malware Scanning in the Same Slice

Deferred.

Malware scanning introduces quarantine storage, asynchronous scan state, additional compute, failure handling, and policy decisions that require a separate architecture slice.

## Follow-Up Decisions

Future work must define:

```text
API Lambda IAM for presigned uploads
Processor Lambda GetObject and GetObjectVersion permissions
runtime bucket environment variables
Lambda packaging
SQS event-source mappings
partial batch failures
timeouts and concurrency
CloudWatch logging and alarms
operator replay permissions
malware scanning and quarantine
real AWS deployment validation
```