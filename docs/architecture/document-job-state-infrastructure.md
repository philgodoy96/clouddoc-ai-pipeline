# Document Job State Infrastructure

## Status

Implemented as an incremental Terraform infrastructure slice.

This document describes the DynamoDB table that owns the authoritative `DocumentJob` lifecycle for CloudDoc AI Pipeline.

## Purpose

CloudDoc processes uploaded documents through an asynchronous, at-least-once delivery pipeline.

S3 stores raw document bytes.

SQS owns delivery attempts, visibility, retries, and dead-letter movement.

DynamoDB owns the durable business state that determines whether a processing effect is valid, stale, duplicated, terminal, or eligible for reconciliation.

The provisioned table is the authoritative source for:

```text
DocumentJob lifecycle state
processing-attempt ownership
attempt counters
lease timestamps
workflow identifiers
validated result data
terminal failure data
dead-letter reconciliation state
```

## Provisioned Resource

The Terraform root provisions:

```text
aws_dynamodb_table.document_jobs
```

The root exports:

```text
document_jobs_table_name
document_jobs_table_arn
```

## Table Naming

The table name is environment-scoped:

```text
${project_name}-${environment}-document-jobs
```

Examples:

```text
clouddoc-dev-document-jobs
clouddoc-staging-document-jobs
clouddoc-prod-document-jobs
```

The resource does not include an account identifier because DynamoDB table names are scoped to an AWS Region and account rather than a global namespace.

## Primary Key Contract

The table uses one string partition key:

```text
PK
```

Persisted document-job keys follow the application contract:

```text
JOB#{job_id}
```

The table does not define:

```text
a sort key
a local secondary index
a global secondary index
```

The current approved access pattern is direct retrieval of one job by its identifier.

Additional indexes will be introduced only after a concrete product or operational query becomes part of the system contract.

## Capacity Mode

The table uses:

```text
PAY_PER_REQUEST
```

CloudDoc has an event-driven workload without an established throughput baseline.

On-demand capacity avoids premature read and write capacity planning and allows the table to scale with actual request volume.

Provisioned capacity remains available after real workload measurements justify a different cost or throughput strategy.

## Table Class

The table uses:

```text
STANDARD
```

Document jobs may receive multiple conditional reads and writes during:

```text
creation
processing claim
lease validation
attempt-aware finalization
terminal failure persistence
dead-letter reconciliation
```

The workload is not currently an infrequent-access archival pattern.

## Point-in-Time Recovery

Point-in-time recovery is enabled.

The table contains workflow state that cannot be reconstructed reliably from S3 or SQS alone.

PITR protects against accidental writes and destructive table-level operational mistakes by preserving a managed continuous recovery window.

A restore operation creates a new table. It does not mutate the existing table back in place.

## Deletion Protection

Deletion protection follows the environment boundary:

```text
dev     → disabled
staging → disabled
prod    → enabled
```

Terraform derives this behavior through:

```text
local.is_production = var.environment == "prod"
```

Development and staging environments remain disposable.

Production receives an additional protection against ordinary table-deletion operations.

Deletion protection is not a substitute for:

```text
least-privilege IAM
Terraform review
state protection
PITR
backup and restore procedures
```

## Encryption

No customer-managed KMS key is configured.

DynamoDB default encryption at rest is used.

This avoids introducing:

```text
KMS key policies
additional Lambda permissions
cross-account key ownership
KMS request costs
rotation operations
```

A customer-managed key remains a future option when compliance, explicit key ownership, or cross-account access creates a concrete requirement.

## Streams

DynamoDB Streams are disabled.

No approved component currently consumes state changes from the table.

CloudDoc already uses S3 and SQS as the ingestion and processing event path.

Adding a stream without a consumer would introduce another event source, retention window, retry model, IAM boundary, and operational surface without a system requirement.

## Time to Live

TTL is not configured.

The project does not yet have an approved automatic job-retention policy.

Enabling TTL without that contract could silently remove:

```text
terminal job state
processing evidence
failure context
dead-letter reconciliation evidence
operator investigation data
```

TTL will require a separate decision covering:

```text
eligible statuses
minimum retention
audit requirements
relationship with S3 object expiration
operator visibility
replay and investigation needs
```

## Secondary Indexes

No secondary index is configured.

Current access is keyed by:

```text
job_id
```

Potential future queries such as:

```text
jobs by status
jobs by creation time
jobs by correlation identifier
jobs by tenant
failed jobs by age
```

are intentionally not modeled until they become approved access patterns.

This prevents speculative write amplification and unnecessary cost.

## Tags

The table defines:

```text
Name = local.document_jobs_table_name
TableRole = authoritative-job-state
```

Provider-level shared tags remain:

```text
Project
Environment
ManagedBy
Component
```

The `TableRole` tag makes the business ownership boundary visible during infrastructure inspection.

## Data Ownership Boundary

### DynamoDB Owns

```text
DocumentJob status
processing-attempt ownership
attempt count
lease state
request and correlation identifiers
validated processing result
terminal failure information
dead-letter reconciliation state
```

### S3 Owns

```text
raw source-document bytes
object metadata
object versions
upload-completion events
```

### SQS Owns

```text
message delivery
receive count
visibility timeout
redrive behavior
dead-letter storage
```

### CloudWatch Will Own

```text
logs
metrics
alarms
operational diagnostics
```

CloudWatch infrastructure remains a future slice.

## Consistency and Concurrency Position

The table is not merely a persistence container.

It is the authority used by the application to enforce:

```text
conditional state transitions
processing-attempt ownership
lease freshness
idempotent terminal effects
stale-write rejection
duplicate-delivery handling
dead-letter reconciliation eligibility
```

The repository adapters use conditional operations so concurrent or duplicated processing attempts cannot both apply the same lifecycle effect.

The infrastructure primary-key design preserves that application contract.

## Terraform Outputs

The root exports:

```text
document_jobs_table_name
document_jobs_table_arn
```

These outputs form a stable boundary for future:

```text
Lambda environment variables
API Lambda IAM policies
Processor Lambda IAM policies
DLQ Reconciler IAM policies
CloudWatch alarms
deployment inspection
```

The outputs do not expose table contents or credentials.

## Offline Testing

The table topology is covered by:

```text
infra/terraform/tests/document_jobs_table.tftest.hcl
```

The test uses:

```text
mock_provider "aws"
command = plan
```

It validates:

```text
development table naming
staging table naming
production table naming
production-environment detection
PAY_PER_REQUEST capacity
PK string partition key
absence of a sort key
STANDARD table class
point-in-time recovery
environment-aware deletion protection
disabled streams
absence of TTL
absence of secondary indexes
default encryption posture
authoritative-state tags
table outputs
```

The tests do not require AWS credentials and do not create resources.

## Security Boundary

### Accidental Production Deletion

Mitigation:

```text
production deletion protection
PITR
future least-privilege IAM
```

### Unencrypted Durable State

Mitigation:

```text
DynamoDB default encryption at rest
```

### Broad Cross-Account Access

Mitigation:

```text
no resource-based policy
future identity-based Lambda roles
```

### Silent Automatic Deletion

Mitigation:

```text
no TTL before an approved retention policy
```

### Speculative Query Surface

Mitigation:

```text
no secondary indexes without approved access patterns
```

### Unbounded Model Result Storage

Mitigation:

```text
application-level validated and bounded result schemas
```

## Failure Modes

### Incorrect Partition-Key Name

Application reads and writes fail because the repository contract expects `PK`.

### Sort Key Added Accidentally

The infrastructure key schema diverges from the current repository key contract.

### Point-in-Time Recovery Disabled

Managed continuous recovery is unavailable for the authoritative workflow state.

### Production Deletion Protection Disabled

An ordinary delete-table request may remove production state.

### TTL Added Without a Retention Contract

Authoritative jobs may disappear asynchronously and without normal application state transitions.

### Streams Enabled Without a Consumer

The system gains another event path without a defined owner or processing contract.

### Secondary Index Added Speculatively

Every write may incur additional cost and operational complexity for an unused query.

### Table Name Changed

Future Lambda environment configuration and IAM policies may target the wrong table.

### Provisioned Capacity Selected Prematurely

Guessed throughput may cause idle cost or throttling.

## Cost Posture

This slice introduces:

```text
DynamoDB on-demand read requests
DynamoDB on-demand write requests
PITR storage and backup charges
table storage
```

Cost controls include:

```text
no unused secondary indexes
no streams
no global tables
no DAX
no customer-managed KMS key
no speculative provisioned capacity
```

The table uses the `STANDARD` class because active workflow state is not an infrequent-access archival workload.

## Intentionally Deferred

The following remain separate implementation slices:

```text
Lambda execution roles
Lambda table permissions
Lambda environment variables
Lambda resources
DynamoDB Streams
TTL and automatic retention
global secondary indexes
local secondary indexes
global tables
DAX
customer-managed KMS keys
resource-based policies
Contributor Insights
CloudWatch metrics and alarms
AWS Backup plans
cross-region disaster recovery
real AWS deployment
restore testing
```

These are intentionally sequenced after the authoritative table contract is stable.

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

No `terraform apply` or AWS credentials are required for the automated validation path.

## Follow-Up Work

The next infrastructure stage should provision Lambda execution identities and runtime functions.

That work must define:

```text
separate Lambda execution roles
least-privilege DynamoDB actions
least-privilege S3 actions
SQS permissions
runtime environment variables
shared artifact integration
handler strings
memory and timeout budgets
CloudWatch log groups
event-source mappings
partial batch failures
concurrency controls
```