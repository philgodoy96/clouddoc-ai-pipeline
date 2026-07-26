# ADR-018: Provision Authoritative Document Job State

## Status

Accepted

## Context

CloudDoc processes documents asynchronously through S3 and SQS.

Both delivery systems are at-least-once and may produce duplicate, delayed, or out-of-order processing attempts.

The system therefore requires one durable authority that determines:

```text
whether a job exists
which lifecycle state is current
which processing attempt owns the work
whether a lease is active or expired
whether a terminal effect has already been applied
whether a dead-letter reconciliation may proceed
```

Raw document bytes and queue delivery metadata cannot provide that business authority.

The repository's application and persistence boundaries already model `DocumentJob` state under the partition-key contract:

```text
PK = JOB#{job_id}
```

The AWS infrastructure must preserve that contract before Lambda execution roles and functions are provisioned.

## Decision

CloudDoc will provision one DynamoDB table as the authoritative owner of document-job lifecycle state.

The table will use:

```text
name = ${project_name}-${environment}-document-jobs
billing mode = PAY_PER_REQUEST
partition key = PK
partition-key type = String
table class = STANDARD
point-in-time recovery = enabled
DynamoDB Streams = disabled
TTL = absent
secondary indexes = absent
customer-managed KMS key = absent
```

Deletion protection will be:

```text
dev = disabled
staging = disabled
prod = enabled
```

The table will export its name and ARN for future runtime and IAM integration.

## Primary-Key Decision

The table will use one string partition key:

```text
PK
```

The application stores document jobs as:

```text
JOB#{job_id}
```

No sort key will be introduced.

The current approved access pattern is direct retrieval and conditional update of one document job by identifier.

Adding a sort key would change the persistence contract without an approved entity relationship or access pattern.

## Capacity Decision

The table will use:

```text
PAY_PER_REQUEST
```

CloudDoc has an intermittent event-driven workload and no measured steady-state throughput.

On-demand capacity avoids speculative read and write capacity planning.

Provisioned capacity may be reconsidered after deployed workload measurements establish predictable traffic and a clear cost advantage.

## Table-Class Decision

The table will use:

```text
STANDARD
```

Document-job state is active workflow data.

A job may be read and conditionally updated multiple times during creation, processing claims, retries, finalization, and reconciliation.

The workload does not currently match an infrequent-access archival profile.

## Point-in-Time Recovery Decision

Point-in-time recovery will be enabled from the initial table provisioning.

The table owns state that cannot be reconstructed safely from S3 object history or SQS delivery state alone.

PITR provides a managed recovery path for accidental writes or destructive operational events.

A restored table is a new resource and requires a controlled recovery procedure before application traffic is redirected.

## Deletion-Protection Decision

Production deletion protection will be enabled.

Development and staging deletion protection will remain disabled.

This preserves disposable lower environments while adding an explicit safeguard around production workflow state.

Deletion protection is an additional control and does not replace IAM, Terraform review, state protection, or recovery procedures.

## Encryption Decision

CloudDoc will rely on DynamoDB default encryption at rest with an AWS-owned key.

A customer-managed KMS key is intentionally deferred until there is a concrete requirement for:

```text
explicit key ownership
custom key policy
cross-account access
compliance controls
independent rotation policy
```

The current decision avoids additional IAM permissions, key-policy complexity, and KMS request costs.

## Stream Decision

DynamoDB Streams will remain disabled.

No approved consumer exists.

The processing workflow already begins through S3 object-created events and SQS.

Adding a second event source from table mutations would introduce a new retry, retention, IAM, and operational boundary without a defined responsibility.

## TTL Decision

TTL will not be configured.

CloudDoc does not yet have an approved automatic document-job retention policy.

TTL deletion is asynchronous and occurs outside normal application lifecycle transitions.

Introducing it prematurely could remove terminal state, processing evidence, or investigation context.

A future TTL decision must define:

```text
eligible statuses
retention period
audit requirements
operator visibility
relationship with S3 object expiration
replay and investigation requirements
```

## Secondary-Index Decision

No global or local secondary index will be provisioned.

The only approved access pattern is direct job lookup by identifier.

Potential queries by status, time, tenant, correlation identifier, or failure age remain future product or operational decisions.

Avoiding speculative indexes prevents unnecessary write amplification and cost.

## Tagging Decision

The table will include:

```text
Name = environment-scoped table name
TableRole = authoritative-job-state
```

Provider-level shared tags remain in effect.

The role tag communicates that this resource owns business state rather than delivery buffering or raw document bytes.

## Output Decision

Terraform will export:

```text
document_jobs_table_name
document_jobs_table_arn
```

These outputs create a stable integration boundary for:

```text
Lambda environment variables
Lambda execution policies
CloudWatch alarms
deployment inspection
```

The outputs do not expose application data.

## Offline Test Decision

Terraform native tests will use:

```text
mock_provider "aws"
command = plan
```

The tests will validate:

```text
environment-aware names
production detection
on-demand capacity
PK string key
absence of a sort key
STANDARD table class
PITR
environment-aware deletion protection
disabled streams
absence of TTL
absence of secondary indexes
default encryption posture
tags
outputs
```

The automated validation path will not require AWS credentials or create resources.

## Consequences

### Positive

- Document-job lifecycle state has one explicit infrastructure owner.
- The table matches the existing application partition-key contract.
- On-demand capacity avoids speculative throughput planning.
- PITR is available from the first deployment.
- Production receives deletion protection.
- Development and staging remain disposable.
- Default encryption protects stored data without additional KMS operations.
- No unused stream or index creates cost and operational complexity.
- Future Lambda IAM can reference the exact table ARN.
- Future runtime configuration can reference the exact table name.
- Infrastructure behavior is testable offline.

### Negative

- On-demand capacity may cost more than provisioned capacity for stable high-volume traffic.
- PITR adds backup-related cost.
- Lower environments remain deletable.
- Direct lookup is the only efficient access pattern.
- Queries by status or time require scans until an approved index exists.
- Default encryption does not provide customer-owned key control.
- No TTL means job state remains until a future retention process removes it.
- No stream means state-change integrations require a later design.

## Alternatives Considered

### Use a Sort Key

Rejected.

The current repository contract identifies one job by one partition key.

No approved child-entity or multi-item aggregate requires a sort key.

### Use Provisioned Capacity Immediately

Deferred.

There is no measured traffic baseline for accurate capacity planning.

### Use the Infrequent Access Table Class

Rejected.

Document jobs are active workflow state and may receive several reads and conditional writes.

### Disable Point-in-Time Recovery Initially

Rejected.

The table owns authoritative workflow state that cannot be reconstructed reliably from queue or object storage state.

### Enable Deletion Protection in Every Environment

Rejected.

Development and staging must remain intentionally disposable for iterative infrastructure work.

### Disable Production Deletion Protection

Rejected.

Production business state warrants an explicit delete-table safeguard.

### Configure a Customer-Managed KMS Key

Deferred.

No current compliance, ownership, or cross-account requirement justifies the additional key-policy and IAM surface.

### Enable DynamoDB Streams

Deferred.

There is no approved stream consumer.

### Configure TTL Immediately

Deferred.

The product has no approved automatic job-retention contract.

### Add a Status Index

Deferred.

No current API or operator workflow requires a status query.

### Add Multiple Secondary Indexes for Portfolio Breadth

Rejected.

Infrastructure components must serve approved access patterns rather than demonstrate technology collection.

### Store Raw Document Bytes in DynamoDB

Rejected.

S3 owns document bytes and object versions.

DynamoDB owns bounded workflow state.

### Treat SQS or the DLQ as Authoritative Job State

Rejected.

Queue state represents delivery behavior, not business lifecycle truth.

## Follow-Up Decisions

Future work must define:

```text
Lambda execution roles
table-specific IAM actions
runtime environment variables
Lambda functions
CloudWatch log groups
SQS event-source mappings
partial batch failures
timeout and concurrency budgets
deployed PITR validation
restore procedures
job-retention policy
future index access patterns
```