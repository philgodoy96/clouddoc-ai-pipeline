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
logging_config.log_format = JSON
logging_config.application_log_level = INFO
logging_config.system_log_level = WARN
```

Application events remain visible at INFO. Platform system logs are restricted below WARN.

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

Processing and DLQ event-source mappings are declared in Terraform. See [Processing queue consumer infrastructure](processing-queue-consumer-infrastructure.md) and [Dead-letter reconciliation infrastructure](dead-letter-reconciliation-infrastructure.md).

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

Shared across all four functions:

```text
CLOUDDOC_JOBS_TABLE_NAME
CLOUDDOC_DOCUMENTS_BUCKET_NAME
CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

Processor-only Bedrock settings:

```text
CLOUDDOC_AI_PROVIDER=bedrock
CLOUDDOC_BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS=1200
CLOUDDOC_BEDROCK_TEMPERATURE=0.00001
```

Create Job, Get Job, and Dead-Letter Reconciler do not receive AI or Bedrock settings.

Environment maps are normalized as `map(string)` through `tomap`.

Configured shared values are:

```text
upload URL expiration = 900 seconds
processing lease duration = 300 seconds
maximum document size = 65536 bytes
```

Resource names are provided through direct Terraform references.

Knowing a resource identifier does not grant access to the resource.

Access remains controlled by each function execution role.

Secrets, credentials, and provider API keys must not be added to these maps.

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
cloudwatch:PutMetricData
cloudwatch:*
```

Terraform, rather than the runtime, owns log-group creation and retention.

Execution policies intentionally omit custom CloudWatch metric publication. Alarms and the operations dashboard consume AWS-native service metrics only and declare no notification actions.

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

SQS:

```text
dedicated processing-queue consumer policy
```

Bedrock:

```text
bedrock:InvokeModel
resource = exact Nova Micro foundation-model ARN
```

The processor can load either the current source object or a specific version referenced by the event contract.

The role does not receive:

```text
S3 write access
S3 delete access
DynamoDB Query
DynamoDB Scan
Bedrock streaming actions
Bedrock wildcard actions or resources
```

### Dead-Letter Reconciler

DynamoDB:

```text
dynamodb:GetItem
dynamodb:PutItem
resource = authoritative document-jobs table
```

SQS:

```text
dedicated processing-DLQ consumer policy
```

The role does not receive:

```text
S3 access
Bedrock access
automatic replay permissions
```

Other roles remain explicitly free of Bedrock access.

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

These outputs create stable boundaries for:

```text
API Gateway integrations
Lambda invoke permissions
SQS event-source mappings
CloudWatch alarms
operations dashboard inspection
deployment inspection
```

The root also exports:

```text
operations_dashboard_name
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
infra/terraform/tests/bedrock_runtime.tftest.hcl
infra/terraform/tests/observability.tftest.hcl
```

The tests use:

```text
mock_provider "aws"
command = plan
```

Computed values are overridden where required to keep plan-time assertions deterministic.

The Lambda runtime test validates:

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
shared runtime environment
JSON logging
dedicated execution roles
Lambda trust principal
function-scoped log permissions
control-plane least privilege
processing-plane least privilege
development log retention
production log retention
function outputs
```

The Bedrock runtime test validates:

```text
Processor-only Bedrock environment settings
exact Nova Micro foundation-model ARN
bedrock:InvokeModel only
absence of streaming and wildcard Bedrock actions
absence of Bedrock settings and permissions on other functions
```

The observability test validates:

```text
nine CloudWatch alarms
ten-widget operations dashboard
JSON / INFO / WARN Lambda logging
AWS-native metric namespaces and dimensions
absence of alarm notification actions
absence of cloudwatch:PutMetricData and cloudwatch:*
operations_dashboard_name output
```

Native metric dimensions used by alarms and dashboard panels are:

```text
AWS/ApiGateway with ApiId + Stage
AWS/Lambda with FunctionName
AWS/SQS with QueueName
AWS/Bedrock with ModelId
```

The tests do not create AWS resources, require AWS credentials, or perform real Bedrock or CloudWatch calls.

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

The SQS event-source mapping becomes invalid or causes duplicate overlap risk.

### Artifact Hash Not Updated

Terraform may not detect changed application code.

### Missing Bedrock Model ID

Processor startup fails configuration validation when Bedrock is selected without a model ID.

### Model Access Unavailable

Invocation fails as an operational dependency failure until account and region model access is ready.

### Processor Role Missing InvokeModel

Bedrock Converse calls fail with access denied.

### Bedrock Configuration Added to Another Lambda

Non-Processor functions receive AI settings they must not own, breaking isolation guarantees.

### Wildcard Model Permission Introduced

The exact-model IAM boundary collapses and unused models become reachable.

### Incorrect Alarm Dimension

An alarm watches the wrong resource and fails to signal the intended failure mode.

### Dashboard Has No Data

Declared panels remain empty until the corresponding AWS resources emit native metrics in a deployed environment.

### Alarm Has No Action

Alarm state can change without notifying an operator because notification actions are intentionally absent.

### Logging Level Suppresses Required Events

Raising the application log level above INFO can hide required structured operational events.

### High-Cardinality Metric Dimension Introduced

Per-job or per-request dimensions inflate metric cardinality and cost without improving aggregate health signals.

### PutMetricData Permission Introduced

Execution roles gain custom metric publication capability outside the approved native-metric strategy.

## Cost Posture

This slice introduces potential costs for:

text
Lambda invocation duration
Lambda memory allocation
CloudWatch Logs ingestion
CloudWatch Logs retention
nine CloudWatch metric alarms
one CloudWatch operations dashboard


Cost-aware decisions include:

text
small control-plane memory budgets
short control-plane timeouts
explicit log retention
native AWS metrics instead of custom metrics
one dashboard per environment
nine focused alarms
no PutMetricData publisher
no provisioned concurrency
no Lambda versions or aliases
no VPC attachment
no layers
no tracing
no duplicate artifacts
Amazon Nova Micro
1,200 output tokens
maximum event-source concurrency five
two total SDK attempts
mock inference for automated tests


The processor receives a larger memory budget because it owns document loading, validation, and AI orchestration.

Its final budget should be revisited after deployed measurements.

## Intentionally Deferred

The following remain separate implementation slices:

```text
reserved concurrency
alarm notification actions
X-Ray tracing
Secrets Manager
Lambda aliases and versions
artifact publication to S3
code signing
VPC integration
real state-bucket bootstrap in AWS
real remote backend initialization
CI/CD deployment gates
real AWS deployment
real AWS dashboard and alarm validation
operator recovery tooling
SLOs
```

These concerns are intentionally sequenced around concrete operational and deployment boundaries.

## Validation Commands

```bash
python scripts/terraform_workflow.py offline-check
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

No Terraform apply or AWS credentials are required for the automated validation path.

## Follow-Up Work

Terraform state, partial S3 backend declaration, environment files, S3-native locking, and the guarded workflow are implemented in the repository. Real state-bucket bootstrap, remote backend initialization, and environment plan/apply against AWS remain pending.

Real Lambda deployment still requires a verified `artifacts/lambda/clouddoc-app.zip` artifact and authenticated guarded plan/apply when AWS access is available.

Real AWS dashboard and alarm validation, controlled deployment, CI/CD gates, notification routing, and operator recovery remain subsequent work.

## Related Documentation

- [Terraform State and Environment Workflow](terraform-state-and-environment-workflow.md)
- [ADR-025: Use S3 Native Locking and Explicit Environment State](../adr/ADR-025-use-s3-native-locking-and-explicit-environment-state.md)
- [CloudWatch Observability](cloudwatch-observability.md)
- [Bedrock AI Provider Integration](bedrock-ai-provider-integration.md)
- [Processing queue consumer infrastructure](processing-queue-consumer-infrastructure.md)
- [Dead-letter reconciliation infrastructure](dead-letter-reconciliation-infrastructure.md)
- [Runtime Composition](runtime-composition.md)
- [ADR-023: Use Amazon Nova Micro through Bedrock Converse](../adr/ADR-023-use-amazon-nova-micro-through-bedrock-converse.md)
- [ADR-024: Use Native AWS Metrics and Structured Application Logs](../adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)
