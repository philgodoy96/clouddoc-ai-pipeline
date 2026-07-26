# Lambda Runtime Infrastructure

## Status

Implemented as an incremental Terraform infrastructure slice.

This document describes the AWS Lambda runtime, execution identity, logging, artifact, and configuration boundaries for CloudDoc AI Pipeline.

## Purpose

CloudDoc exposes two control-plane operations and two asynchronous processing operations:

```text
Create Job
Get Job
Document Processor
Dead-Letter Reconciler
```

Each function executes application code from the same deterministic deployment package while retaining an independent:

```text
function name
handler
execution role
permission boundary
CloudWatch log group
memory budget
timeout budget
runtime purpose
```

The shared artifact reduces package duplication without collapsing runtime authorization boundaries.

## Runtime Functions

Terraform declares four functions:

```text
aws_lambda_function.create_job
aws_lambda_function.get_job
aws_lambda_function.processor
aws_lambda_function.dead_letter_reconciler
```

Environment-scoped names follow:

```text
${project_name}-${environment}-create-job
${project_name}-${environment}-get-job
${project_name}-${environment}-process-document
${project_name}-${environment}-reconcile-dead-letter
```

Examples for development:

```text
clouddoc-dev-create-job
clouddoc-dev-get-job
clouddoc-dev-process-document
clouddoc-dev-reconcile-dead-letter
```

## Shared Artifact Boundary

All functions consume:

```text
artifacts/lambda/clouddoc-app.zip
```

Terraform resolves the artifact through:

```text
local.lambda_artifact_path
local.lambda_source_code_hash
```

The package is produced outside Terraform by the deterministic Lambda package builder.

Terraform does not:

```text
install Python dependencies
compile native dependencies
discover handlers
build the ZIP
publish the ZIP
```

The source-code hash is calculated only when the artifact exists.

This preserves:

```text
offline terraform validate
mocked terraform test
real deployment change detection
```

A controlled deployment workflow must build and verify the artifact before any real plan or apply.

## Runtime Platform

All functions use:

```text
runtime = python3.12
architecture = x86_64
package type = Zip
publish = false
log format = JSON
```

The package builder targets CPython 3.12 and Linux x86_64.

Changing the runtime or architecture requires changing the packaging contract in the same approved engineering decision.

## Handler Contracts

The configured handlers are:

```text
Create Job
clouddoc.handlers.create_job.lambda_handler

Get Job
clouddoc.handlers.get_job.lambda_handler

Document Processor
clouddoc.handlers.process_uploaded_document.lambda_handler

Dead-Letter Reconciler
clouddoc.handlers.reconcile_dead_lettered_document.lambda_handler
```

Every handler module is included in the shared package and exposes a callable `lambda_handler`.

## Function Budgets

### Create Job

```text
memory = 256 MB
timeout = 10 seconds
```

Responsibilities:

```text
create authoritative DocumentJob state
generate a presigned S3 upload URL
return the control-plane response
```

### Get Job

```text
memory = 256 MB
timeout = 5 seconds
```

Responsibility:

```text
retrieve one authoritative DocumentJob
```

### Document Processor

```text
memory = 1024 MB
timeout = 120 seconds
```

Responsibilities:

```text
claim processing ownership
load the source document
invoke the configured AI provider
validate the result
persist attempt-aware completion or failure state
```

The processing queue visibility timeout remains 720 seconds.

The current ratio is:

```text
queue visibility timeout = 720 seconds
processor timeout = 120 seconds
visibility margin = 6x
```

The SQS event-source mapping remains a separate infrastructure slice.

### Dead-Letter Reconciler

```text
memory = 512 MB
timeout = 30 seconds
```

Responsibilities:

```text
interpret exhausted processing delivery
load authoritative job state
persist dead-letter reconciliation state
```

The reconciler does not:

```text
read source-document bytes
invoke the AI provider
replay the message
```

## Runtime Configuration

The functions receive one validated non-secret environment map:

```text
CLOUDDOC_JOBS_TABLE_NAME
CLOUDDOC_DOCUMENTS_BUCKET_NAME
CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

The map is normalized as `map(string)` through `tomap`.

Configured values are:

```text
upload URL expiration = 900 seconds
processing lease duration = 300 seconds
maximum document size = 65536 bytes
```

Resource names are provided through direct Terraform references.

Knowing a resource identifier does not grant access to the resource.

Access remains controlled by each function execution role.

Secrets, credentials, and provider API keys must not be added to this map.

## Execution Identity Model

Each function has a dedicated IAM execution role:

```text
aws_iam_role.create_job
aws_iam_role.get_job
aws_iam_role.processor
aws_iam_role.dead_letter_reconciler
```

Every role trusts only:

```text
service principal = lambda.amazonaws.com
action = sts:AssumeRole
```

The project does not use one shared all-purpose execution role.

This limits permission coupling and keeps function responsibilities independently reviewable.

## Logging Permissions

Terraform owns four CloudWatch log groups:

```text
/aws/lambda/${create_job_function_name}
/aws/lambda/${get_job_function_name}
/aws/lambda/${processor_function_name}
/aws/lambda/${dead_letter_reconciler_function_name}
```

Retention is:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

Each role may write only to its own log group streams with:

```text
logs:CreateLogStream
logs:PutLogEvents
```

The roles do not receive:

```text
logs:CreateLogGroup
Resource = *
```

Terraform, rather than the runtime, owns log-group creation and retention.

## Control-Plane Permissions

### Create Job

DynamoDB:

```text
dynamodb:PutItem
resource = authoritative document-jobs table
```

S3:

```text
s3:PutObject
resource = documents bucket under documents/*
```

The S3 permission enables the function to generate a presigned upload URL backed by its own credentials.

The role does not receive:

```text
DynamoDB read access
S3 read access
S3 bucket listing
SQS access
Bedrock access
```

### Get Job

DynamoDB:

```text
dynamodb:GetItem
resource = authoritative document-jobs table
```

The role is read-only against the job table and receives no S3, SQS, or Bedrock access.

## Processing-Plane Permissions

### Document Processor

DynamoDB:

```text
dynamodb:GetItem
dynamodb:PutItem
resource = authoritative document-jobs table
```

S3:

```text
s3:GetObject
s3:GetObjectVersion
resource = documents bucket under documents/*
```

The processor can load either the current source object or a specific version referenced by the event contract.

The role does not receive:

```text
S3 write access
S3 delete access
DynamoDB Query
DynamoDB Scan
SQS consumer actions
Bedrock actions
```

SQS and Bedrock permissions remain tied to their respective future integration slices.

### Dead-Letter Reconciler

DynamoDB:

```text
dynamodb:GetItem
dynamodb:PutItem
resource = authoritative document-jobs table
```

The role does not receive:

```text
S3 access
Bedrock access
SQS consumer actions
automatic replay permissions
```

DLQ consumer permissions remain part of the future dead-letter event-source mapping slice.

## Terraform Outputs

The root exports names and ARNs for all four functions:

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

These outputs create stable boundaries for future:

```text
API Gateway integrations
Lambda invoke permissions
SQS event-source mappings
CloudWatch alarms
deployment inspection
```

The root does not export:

```text
execution-role ARNs
inline-policy identifiers
artifact paths
source hashes
environment values
secrets
```

## Offline Testing

The runtime infrastructure is covered by:

```text
infra/terraform/tests/lambda_runtime_functions.tftest.hcl
```

The test uses:

```text
mock_provider "aws"
command = plan
```

Computed values are overridden where required to keep plan-time assertions deterministic.

The test validates:

```text
function names
handler strings
Python runtime
architecture
package type
artifact path
source-code hash contract
memory budgets
timeout budgets
runtime environment
JSON logging
dedicated execution roles
Lambda trust principal
function-scoped log permissions
control-plane least privilege
processing-plane least privilege
absence of SQS actions
absence of Bedrock actions
development log retention
production log retention
function outputs
```

The test does not create AWS resources or require AWS credentials.

## Security Boundary

### Shared Artifact, Separate Authorization

All functions use the same code package.

IAM determines which portions of that package can produce valid external effects.

Code availability does not imply resource authorization.

### Function-Specific Roles

A compromised or misconfigured function does not automatically inherit another function's permissions.

### Object Prefix Restriction

S3 access is restricted to:

```text
documents/*
```

The application further enforces the canonical key shape:

```text
documents/{job_id}/source.txt
```

IAM constrains the approved prefix while application validation owns the exact key grammar.

### No Wildcard Business Permissions

Business policies target explicit:

```text
DynamoDB table ARN
S3 object-prefix ARN
function-specific log-group streams
```

### No Runtime Secrets

The environment map contains resource identifiers and operational limits only.

## Failure Modes

### Missing Artifact

A real deployment cannot create or update the function package.

Offline Terraform validation may still succeed because artifact absence is handled deliberately.

### Incorrect Artifact Architecture

The function may fail to import dependencies or execute native code.

### Incorrect Handler

Lambda fails during handler import or invocation.

### Missing Runtime Environment Value

The application fails startup validation.

### Shared Role Introduced

Function authorization boundaries collapse and unrelated permissions become coupled.

### Create Job Missing S3 PutObject

Generated presigned upload URLs fail with access denied.

### Processor Missing GetObjectVersion

Version-specific source retrieval fails.

### Logging Permission Targets Wrong Group

Runtime logs may be unavailable or written outside the intended ownership boundary.

### Function Timeout Exceeds Queue Visibility

The future SQS event-source mapping becomes invalid or causes duplicate overlap risk.

### Artifact Hash Not Updated

Terraform may not detect changed application code.

## Cost Posture

This slice introduces potential costs for:

```text
Lambda invocation duration
Lambda memory allocation
CloudWatch Logs ingestion
CloudWatch Logs retention
```

Cost-aware decisions include:

```text
small control-plane memory budgets
short control-plane timeouts
explicit log retention
no provisioned concurrency
no Lambda versions or aliases
no VPC attachment
no layers
no tracing
no duplicate artifacts
```

The processor receives a larger memory budget because it owns document loading, validation, and AI orchestration.

Its final budget should be revisited after deployed measurements.

## Intentionally Deferred

The following remain separate implementation slices:

```text
API Gateway resources
Lambda invoke permissions for API Gateway
processing queue event-source mapping
processing queue consumer permissions
DLQ event-source mapping
DLQ consumer permissions
partial batch response configuration
batch sizes and batching windows
event-source maximum concurrency
reserved concurrency
Bedrock provider integration
Bedrock permissions
CloudWatch alarms
CloudWatch dashboards
X-Ray tracing
Secrets Manager
Lambda aliases and versions
artifact publication to S3
code signing
VPC integration
real AWS deployment
```

These concerns are intentionally sequenced around concrete invocation and operational boundaries.

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

The next slice should connect the processing queue to the Document Processor Lambda.

That work must define:

```text
SQS consumer IAM actions
event-source mapping
batch size
batching window
partial batch failure support
maximum event-source concurrency
timeout compatibility
failure and retry behavior
```