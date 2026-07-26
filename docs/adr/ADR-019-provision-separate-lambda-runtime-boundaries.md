# ADR-019: Provision Separate Lambda Runtime Boundaries

## Status

Accepted

## Context

CloudDoc has four application entrypoints:

```text
Create Job
Get Job
Document Processor
Dead-Letter Reconciler
```

The functions share one Python codebase and deterministic deployment package, but they do not share the same operational responsibilities or resource access.

A shared execution role would couple unrelated permissions:

```text
control-plane writes
control-plane reads
document retrieval
processing state transitions
dead-letter reconciliation
```

The AWS infrastructure must provide deployable runtime resources without prematurely adding invocation sources, Bedrock access, or queue-consumer permissions.

The project also requires:

```text
deterministic packaging
offline Terraform validation
explicit log retention
environment-scoped names
stable future integration outputs
```

## Decision

CloudDoc will provision four AWS Lambda functions from one shared deterministic ZIP artifact.

Each function will have an independent:

```text
function resource
handler
execution role
business permission policy
logging policy
CloudWatch log group
memory budget
timeout budget
name and ARN output
```

All functions will use:

```text
Python 3.12
x86_64
Zip package type
JSON logging
unpublished function code
```

Invocation sources remain outside this decision.

## Shared Artifact Decision

All functions will consume:

```text
artifacts/lambda/clouddoc-app.zip
```

Terraform will not build the artifact.

The package builder remains responsible for:

```text
dependency installation
platform targeting
handler discovery
deterministic ZIP metadata
checksum generation
```

Terraform will calculate `source_code_hash` when the artifact exists.

Artifact absence will not block offline `terraform validate` or mocked `terraform test`.

A future controlled deployment workflow must verify the package before real infrastructure operations.

## Function Separation Decision

The four functions will remain distinct resources:

```text
create_job
get_job
processor
dead_letter_reconciler
```

A single routing Lambda was rejected because it would:

```text
couple permissions
couple timeout budgets
couple memory budgets
increase blast radius
hide workload-specific scaling
blur operational ownership
```

## Execution Role Decision

Each function will receive a dedicated IAM execution role.

Every role will trust only:

```text
lambda.amazonaws.com
```

The roles will not share one generic permission policy.

This preserves least privilege and makes each function's external-effect boundary independently reviewable.

## Logging Decision

Terraform will pre-create one CloudWatch log group per function.

Retention will be:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

Each function role will receive only:

```text
logs:CreateLogStream
logs:PutLogEvents
```

against its own log-group streams.

`logs:CreateLogGroup` is excluded because Terraform owns log-group creation.

The AWS-managed basic execution policy is not attached because its wildcard logging scope is broader than required.

## Control-Plane Permission Decision

### Create Job

The Create Job function will receive:

```text
dynamodb:PutItem
s3:PutObject
```

The DynamoDB action targets only the authoritative jobs table.

The S3 action targets only:

```text
documents/*
```

The S3 permission allows the function's credentials to back a presigned upload URL.

The function will not receive S3 read access or DynamoDB read access.

### Get Job

The Get Job function will receive:

```text
dynamodb:GetItem
```

against the authoritative jobs table.

It will not receive DynamoDB writes or S3 access.

## Processing-Plane Permission Decision

### Document Processor

The Processor will receive:

```text
dynamodb:GetItem
dynamodb:PutItem
s3:GetObject
s3:GetObjectVersion
```

DynamoDB actions target the authoritative jobs table.

S3 actions target only:

```text
documents/*
```

`GetObjectVersion` preserves the version-aware document-loading contract.

SQS consumer and Bedrock permissions are intentionally excluded until their integration slices.

### Dead-Letter Reconciler

The reconciler will receive:

```text
dynamodb:GetItem
dynamodb:PutItem
```

against the authoritative jobs table.

It will not receive S3 or Bedrock access.

SQS DLQ consumer permissions remain tied to the future event-source mapping.

## Runtime Configuration Decision

All functions will receive one validated `map(string)` containing:

```text
CLOUDDOC_JOBS_TABLE_NAME
CLOUDDOC_DOCUMENTS_BUCKET_NAME
CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

The map contains no secrets.

Using the same validated settings contract across functions keeps startup configuration consistent while IAM still controls actual access.

## Runtime Budget Decision

Configured budgets are:

```text
Create Job
256 MB
10 seconds

Get Job
256 MB
5 seconds

Document Processor
1024 MB
120 seconds

Dead-Letter Reconciler
512 MB
30 seconds
```

The Processor receives the largest budget because it performs document loading, AI orchestration, result validation, and attempt-aware persistence.

The Processor timeout remains below the existing 720-second processing queue visibility timeout.

Budgets are initial production-minded defaults and must be revisited after deployed measurements.

## Output Decision

Terraform will export the name and ARN of every Lambda function.

These outputs are the stable integration boundary for future:

```text
API Gateway
Lambda invoke permissions
SQS event-source mappings
CloudWatch alarms
deployment inspection
```

Role ARNs and policy identifiers are not exported because no approved external consumer requires them.

## Offline Test Decision

Terraform native tests will use:

```text
mock_provider "aws"
command = plan
```

The tests will override computed identifiers where plan-time assertions require deterministic values.

They will verify:

```text
function configuration
handler contracts
runtime and architecture
artifact boundary
runtime environment
dedicated roles
trust policy
logging permissions
least-privilege business permissions
absence of SQS permissions
absence of Bedrock permissions
environment-aware retention
outputs
```

The automated validation path will not require AWS credentials or create resources.

## Consequences

### Positive

- Each runtime responsibility has an explicit function resource.
- Shared packaging avoids duplicated build pipelines.
- Dedicated roles preserve least privilege.
- Logging scope is narrower than the AWS-managed basic execution policy.
- Log retention is explicit.
- Runtime settings are validated and non-secret.
- Function budgets are workload-specific.
- Future API Gateway and SQS integrations can reference stable outputs.
- Terraform can validate and test offline.
- The implementation remains compatible with the deterministic packaging foundation.

### Negative

- Four functions create more Terraform resources than one routing function.
- Four roles and multiple inline policies increase policy-document volume.
- Shared artifacts can include code paths a function is not authorized to execute.
- Initial memory and timeout budgets are not yet based on deployed measurements.
- Inline policies are not reusable across unrelated functions.
- Offline tests require explicit overrides for some computed values.
- Environment variables are duplicated across functions.
- Artifact absence remains possible during offline validation.

## Alternatives Considered

### Use One Shared Execution Role

Rejected.

It would combine control-plane, document-read, reconciliation, and future queue or Bedrock permissions.

### Use AWSLambdaBasicExecutionRole

Rejected.

Terraform owns log groups, and each function can be restricted to its own streams without wildcard `CreateLogGroup` permission.

### Use One Routing Lambda

Rejected.

It would couple memory, timeout, authorization, scaling, and operational ownership.

### Build the ZIP Inside Terraform

Rejected.

Terraform is an infrastructure declarative engine, not the application build system.

The existing deterministic package builder owns compilation and packaging.

### Publish One ZIP Per Function

Deferred.

The functions currently share the same application and dependency set.

Independent artifacts become useful only if package size, deployment cadence, security policy, or cold-start measurements justify the additional build complexity.

### Use ARM64

Deferred.

The current deterministic package contract targets x86_64.

Changing architecture requires rebuilding and validating dependencies for that target.

### Enable Function Versions and Aliases

Deferred.

No deployment promotion or traffic-shifting workflow exists yet.

### Configure Reserved Concurrency Immediately

Deferred.

Concurrency must be designed together with SQS polling, batch size, Bedrock quotas, DynamoDB pressure, and retry behavior.

### Grant SQS Permissions Now

Rejected.

No event-source mapping exists in this slice.

Queue permissions will be added with the consumer boundary that requires them.

### Grant Bedrock Permissions Now

Rejected.

The real Bedrock provider and model access contract have not yet been provisioned.

### Store Secrets in Environment Variables

Rejected.

The current values are non-secret resource identifiers and operational limits.

Future secrets require a dedicated secret-management decision.

## Follow-Up Decisions

Future work must define:

```text
processing queue event-source mapping
processor SQS consumer permissions
partial batch failure reporting
batch size and batching window
event-source maximum concurrency
DLQ reconciler event-source mapping
DLQ consumer permissions
API Gateway routes and integrations
Lambda invocation permissions
Bedrock model and IAM permissions
CloudWatch alarms and dashboards
deployed performance measurements
reserved concurrency
deployment promotion strategy
```