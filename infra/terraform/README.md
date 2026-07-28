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
an API Gateway HTTP control plane
Create Job and Get Job Lambda proxy integrations
two explicit AWS IAM-protected routes
an environment-named auto-deploy stage
structured API access logging
route-specific throttling
route-scoped Lambda invocation permissions
stable API outputs
Processor-only Bedrock environment and IAM
exact Nova Micro foundation-model permission
explicit Lambda JSON / INFO / WARN logging
nine CloudWatch metric alarms
one CloudWatch operations dashboard
operations_dashboard_name output
partial S3 backend declaration
optional expected AWS account guard
explicit dev/staging/prod environment files
S3-native lockfiles (`use_lockfile = true`)
guarded environment workflow (`scripts/terraform_workflow.py`)
offline Bedrock isolation tests
offline observability tests
offline bootstrap and workflow tests
```

Backend declaration, bootstrap root, environment files, and the guarded workflow are implemented in the repository. Real AWS state-bucket creation, remote backend initialization, and environment plan/apply against AWS remain pending.

Credential-free infrastructure CI validation is implemented. Controlled deploy workflow source is implemented. GitHub configuration, AWS activation, and live deployment proof remain pending. Automatic replay, operator recovery tooling, real AWS deployment, and real CloudWatch validation remain separate follow-up work.

## Backend and state

Terraform infrastructure state is operational metadata for this root. It is distinct from DynamoDB `DocumentJob` business state.

| Concern | Location |
| --- | --- |
| Bootstrap (creates account-scoped state bucket) | `infra/bootstrap/terraform-state/` |
| Application backend declaration | `backend.tf` partial `backend "s3" {}` |
| State bucket naming | `${project_name}-${account_id}-terraform-state` (bootstrap) |
| State object keys | `clouddoc/<environment>/terraform.tfstate` per environment |
| Lockfiles | S3-native lock objects alongside state (`use_lockfile = true`; no DynamoDB table) |
| Committed environment inputs | `infra/terraform/environments/*.tfvars` and `*.s3.tfbackend` |
| Runtime bucket and account inputs | `CLOUDDOC_TERRAFORM_STATE_BUCKET`, `CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID` |
| Optional chained-role inputs | `CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN`, `CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN`, `CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN` |
| Optional provider variables | `terraform_plan_role_arn`, `terraform_apply_role_arn` (mutually exclusive) |
| Provider wrong-account guard | optional `expected_aws_account_id` → `allowed_account_ids` |
| Isolated Terraform metadata | `infra/terraform/.terraform-data/<environment>/` via `TF_DATA_DIR` |
| Saved plans and manifests | `artifacts/terraform/<environment>/` (strict JSON manifest, plan SHA-256 binding) |
| Deployment temporary output | runner temp / approved `--output-directory` |
| Local-state migration | rejected when local state exists before remote init |

Full operator workflow, IAM expectations, and integrity rules are documented in [Terraform State and Environment Workflow](../../docs/architecture/terraform-state-and-environment-workflow.md), [Terraform Deployment Authorization](../../docs/architecture/terraform-deployment-authorization.md), and [Terraform Deploy Workflow Runbook](../../docs/operations/terraform-deploy-workflow.md). Bootstrap local state for the state bucket itself is an intentional narrow exception and is not remote or collaborative.

Real bucket creation and remote backend initialization in AWS remain future work.

## Environment configuration

Six committed files define explicit non-secret environment identity (no Terraform workspaces):

| File | Allowed content |
| --- | --- |
| `environments/dev.tfvars` | `aws_region`, `project_name`, `environment` (`dev`) |
| `environments/staging.tfvars` | same fields with `environment = "staging"` |
| `environments/prod.tfvars` | same fields with `environment = "prod"` |
| `environments/dev.s3.tfbackend` | `key`, `region`, `encrypt = true`, `use_lockfile = true` |
| `environments/staging.s3.tfbackend` | environment-specific `key` under `clouddoc/staging/...` |
| `environments/prod.s3.tfbackend` | environment-specific `key` under `clouddoc/prod/...` |

The bucket name is supplied at runtime through `CLOUDDOC_TERRAFORM_STATE_BUCKET`, not committed in backend files. The committed backend key remains authoritative, and there is no GitHub variable for the state key. Do not add `profile`, `dynamodb_table`, or static credentials to committed files.

Local `terraform.tfvars`, state, plans, manifests, and credentials remain outside Git.

## Provider authorization modes

The AWS provider supports three mutually exclusive modes:

```text
ambient
    both plan and apply role ARNs absent
    local approved operation with ambient credentials

plan role
    state role + plan role present
    apply role must be absent
    used by plan

apply role
    state role + apply role present
    plan role must be absent
    used by controlled deploy
```

Plan uses state + plan roles. Deploy uses state + apply roles. The plan role must be absent during deploy. The apply role must be absent during plan. Ambient mode remains supported locally.

## Operator commands

Use the guarded workflow script from the repository root:

```powershell
python scripts/terraform_workflow.py offline-check
python scripts/terraform_workflow.py init --environment dev
python scripts/terraform_workflow.py plan --environment dev
python scripts/terraform_workflow.py plan --environment dev --output-directory <approved-path>
python scripts/terraform_workflow.py show-plan --environment dev
python scripts/terraform_workflow.py apply --environment dev --confirm-environment dev
python scripts/terraform_workflow.py deploy --environment dev --confirm-environment APPLY-DEV
python scripts/terraform_workflow.py output --environment dev
```

* `offline-check` runs bootstrap and application offline validation; no AWS credentials required.
* `init`, `plan`, `apply`, `deploy`, and `output` require future AWS authentication and the runtime bucket/account variables.
* `show-plan` validates a local saved plan and manifest without calling AWS.
* `apply` is the existing local saved-plan contract. It is not the GitHub controlled deployment path.
* `deploy` is the controlled regenerate/compare/apply contract used by the GitHub deploy workflow.

Environment variables:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN
```

The script verifies `artifacts/lambda/clouddoc-app.zip` and its SHA-256 checksum before `plan`, `apply`, and `deploy`. It does not expose `destroy`, `force-unlock`, `-lock=false`, or `-auto-approve`.

Deployment behavior:

* deployment temporary files should use runner temp or an approved output directory;
* a verified no-op succeeds without apply;
* fingerprint mismatch fails closed and requires a new reviewed plan;
* partial apply is a manual incident and must not be blindly rerun;
* automatic rollback is intentionally not claimed;
* convergence verification remains an operator responsibility after successful apply.

## Continuous Integration

The `Infrastructure Quality / Terraform offline` job runs:

```powershell
python scripts/terraform_workflow.py offline-check
```

CI pins Terraform to `1.15.8` with `terraform_wrapper: false`.

Both roots are validated with `backend=false`, while authenticated Terraform plan remains a separate manual operational workflow:

```text
application Terraform root → 29 passing runs
bootstrap Terraform root → 4 passing runs
```

The job supplies:

```text
no AWS credentials
no state bucket
no remote backend initialization
no plan
no apply
```

The Terraform offline job runs independently from `Infrastructure Quality / Lambda package`, so it validates the absent-artifact path on a clean runner.

Lambda package CI builds and verifies the shared ZIP twice and compares SHA-256 digests; it does not publish the artifact. Full packaging and CI contracts are documented in [Infrastructure CI Validation](../../docs/architecture/infrastructure-ci-validation.md).

Intended GitHub check names for branch protection (not claimed as configured):

```text
Python Quality / Format, lint, and test
Infrastructure Quality / Lambda package
Infrastructure Quality / Terraform offline
```

Branch protection should be configured after these workflows run successfully on `main`.

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

#### Runtime platform and logging

All four functions use:

```text
Python 3.12
x86_64
Zip package type
logging_config.log_format = JSON
logging_config.application_log_level = INFO
logging_config.system_log_level = WARN
publish disabled
```

Application events remain visible at INFO. Platform system logs are restricted
below WARN. Log retention and role-scoped log permissions are unchanged.

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

Create Job, Get Job, and Dead-Letter Reconciler do not receive AI or Bedrock
settings.

Configured shared values:

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
| Processor | `dynamodb:GetItem`; `dynamodb:PutItem`; `s3:GetObject`; `s3:GetObjectVersion` under `documents/*`; dedicated processing-queue consumer inline policy; dedicated exact-model `bedrock:InvokeModel` policy |
| Dead-Letter Reconciler | `dynamodb:GetItem`; `dynamodb:PutItem`; dedicated processing-DLQ consumer inline policy |

Each function has its own role. Each role trusts only `lambda.amazonaws.com`.
Logging permissions target only that function's log group streams.
`logs:CreateLogGroup` is not granted. No AWS-managed basic execution policy is
attached.

Only the Processor role may invoke Bedrock. The dedicated policy grants one
action, `bedrock:InvokeModel`, against one exact partition-aware regional
accountless foundation-model ARN for Nova Micro. Streaming actions and Bedrock
wildcards are not granted.

Execution policies intentionally omit:

```text
cloudwatch:PutMetricData
cloudwatch:*
```

Alarms and dashboard panels consume AWS-native service metrics. No custom metric
namespace, Embedded Metric Format publisher, or log metric filter is introduced.

#### Bedrock invocation boundary

```text
data.aws_partition.current
data.aws_iam_policy_document.processor_bedrock_invoke
aws_iam_role_policy.processor_bedrock_invoke
```

Terraform configures Processor runtime selection and grants model invocation
permission. Nova Micro itself is not provisioned by Terraform; model access
readiness remains an AWS account and region concern outside this root.

#### Logging

Terraform owns four `/aws/lambda/<function-name>` log groups and their retention:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

Terraform owns log-group creation and retention. Runtime roles may create streams
and put events only within their own log group.

### Observability

```text
aws_cloudwatch_metric_alarm.control_plane_5xx
aws_cloudwatch_metric_alarm.processor_lambda_errors
aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors
aws_cloudwatch_metric_alarm.processing_queue_age
aws_cloudwatch_metric_alarm.processing_dlq_visible
aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible
aws_cloudwatch_metric_alarm.bedrock_client_errors
aws_cloudwatch_metric_alarm.bedrock_server_errors
aws_cloudwatch_metric_alarm.bedrock_throttles
aws_cloudwatch_dashboard.operations
```

Dashboard name:

```text
${project_name}-${environment}-operations
```

Default local values produce:

```text
clouddoc-dev-operations
```

The dashboard exposes ten widgets:

```text
Operational alarm status
Control plane traffic and errors
Control plane latency
Lambda errors and throttles
Lambda duration and concurrency
Processing queue health
Dead-letter and quarantine health
Amazon Bedrock invocations and errors
Amazon Bedrock invocation latency
Amazon Bedrock token usage
```

Detailed alarm thresholds, dimensions, and widget metric contracts are documented
in [CloudWatch observability](../../docs/architecture/cloudwatch-observability.md).

#### Native metric boundary

Alarms and dashboard panels use AWS-native namespaces and low-cardinality
dimensions only:

```text
AWS/ApiGateway with ApiId + Stage
AWS/Lambda with FunctionName
AWS/SQS with QueueName
AWS/Bedrock with ModelId
```

No custom metric namespace, EMF, or log metric filter is introduced.

#### Alarm notification boundary

Alarm resources intentionally declare no `alarm_actions`, `ok_actions`, or
`insufficient_data_actions`.

This is not accidental incompleteness. Incident routing requires an approved
operator and environment-specific notification channel before actions are
attached.

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

### HTTP control plane

```text
aws_apigatewayv2_api.control_plane
aws_apigatewayv2_integration.create_job
aws_apigatewayv2_integration.get_job
aws_apigatewayv2_route.create_job
aws_apigatewayv2_route.get_job
aws_apigatewayv2_stage.control_plane
aws_cloudwatch_log_group.control_plane_api_access
aws_lambda_permission.control_plane_create_job
aws_lambda_permission.control_plane_get_job
```

API name:

```text
${project_name}-${environment}-control-plane
```

Default local values produce:

```text
clouddoc-dev-control-plane
```

## Control-plane flow

```text
authenticated AWS caller
    → API Gateway HTTP API
        → POST /v1/document-jobs
            → Create Job Lambda
        → GET /v1/document-jobs/{job_id}
            → Get Job Lambda
```

The control plane does not proxy document bytes. Create Job returns a
presigned S3 upload URL. Document processing remains asynchronous through S3,
SQS, and Lambda. DynamoDB remains authoritative for `DocumentJob` state.

## Processing flow

```text
S3 ObjectCreated
    → processing SQS queue
    → Lambda event source mapping
    → Document Processor Lambda
    → S3 / DynamoDB / Amazon Bedrock
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

## HTTP API

Terraform declares:

```text
aws_apigatewayv2_api.control_plane
```

Configured properties:

```text
protocol type = HTTP
environment-scoped name
default execute-api endpoint enabled
```

The default execute-api endpoint remains enabled to support controlled
validation before a custom-domain decision.

## Routes

The API declares exactly two routes:

```text
POST /v1/document-jobs
GET /v1/document-jobs/{job_id}
```

Both routes use:

```text
authorization_type = AWS_IAM
```

No `$default`, `ANY /`, or `ANY /{proxy+}` route exists. Unknown methods and
paths therefore do not reach a Lambda integration.

## Integrations

Both integrations use:

```text
integration type = AWS_PROXY
integration method = POST
payload format version = 2.0
```

The integration method is the Lambda Invoke API method. It is independent of
the client-facing route method.

Configured timeout relationships:

```text
Create Job integration = 15 seconds
Create Job Lambda = 10 seconds

Get Job integration = 10 seconds
Get Job Lambda = 5 seconds
```

Each API integration timeout remains longer than the target Lambda timeout.
This keeps the Lambda function as the primary application timeout boundary
while allowing API Gateway time to receive the result.

## Authorization boundary

Callers must sign requests with AWS Signature Version 4 or Version 4a.
Callers require `execute-api:Invoke` permission matching the route.

This stack does not create caller IAM users, roles, long-lived keys, or caller
policies. Caller identity ownership belongs to the deployment and operations
security boundary.

Request IDs and correlation IDs are traceability values. They are not identity
or authorization.

## Stage

Terraform declares:

```text
aws_apigatewayv2_stage.control_plane
```

Configured properties:

```text
stage name = environment
auto deploy = true
```

No standalone API Gateway deployment resource is declared. Stage updates
publish through auto-deploy.

## Access logs

Terraform owns the managed access-log group:

```text
/aws/apigateway/${control_plane_api_name}
```

Retention:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

The stage emits structured JSON access logs with exactly these fields:

```text
requestId
requestTimeEpoch
routeKey
stage
status
responseLength
integrationStatus
integrationLatency
integrationErrorMessage
sourceIp
userAgent
```

Access logs exclude:

```text
request bodies
response bodies
Authorization headers
presigned upload URLs
document content
credentials
```

`integrationErrorMessage` supports diagnosis of integration and permission
failures without logging sensitive payloads. Lambda application logs remain
separate from API edge access logs.

## Route throttling

Create Job:

```text
rate 2 requests per second
burst 5
```

Get Job:

```text
rate 10 requests per second
burst 20
```

Create Job receives the lower limit because it performs a state mutation and
creates a presigned upload capability. Get Job is read-only and receives a
higher initial threshold.

Throttling is best-effort operational protection. It is not authorization,
billing enforcement, or a hard cost ceiling.

## Route-scoped Lambda permissions

Terraform declares two independent Lambda resource-based permissions.

Create Job:

```text
environment stage + POST + /v1/document-jobs
```

Get Job:

```text
environment stage + GET + /v1/document-jobs/*
```

Each permission targets only its corresponding Lambda. The Get Job wildcard
covers only the dynamic `job_id` segment. No API-wide `/*/*` permission exists.

These concerns are distinct:

```text
AWS_IAM route authorization
    → decides whether a signed caller may invoke the route

Lambda resource-based invocation permission
    → decides whether API Gateway may invoke the target function
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
API Gateway owns the authenticated HTTP control-plane boundary
S3 owns raw document bytes and object versions
SQS owns delivery attempts and redrive
DynamoDB owns authoritative DocumentJob lifecycle state
the quarantine queue owns terminal operational evidence
```

The control plane returns job metadata and a presigned upload URL. Document
bytes bypass API Gateway through direct S3 upload. SQS delivery state does not
determine business lifecycle state. Message visibility, receive counts, and
dead-letter placement describe transport retries only. Authoritative
`DocumentJob` status lives in DynamoDB.

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

Local offline validation uses `-backend=false` and does not require remote backend configuration:

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
terraform test
```

From the repository root, the guarded offline entry point is:

```powershell
python scripts/terraform_workflow.py offline-check
```

### Application root native tests

Terraform native tests now cover:

```text
processing queue topology
document ingestion topology
document-jobs table topology
Lambda runtime and IAM topology
processing event-source topology
dead-letter reconciliation topology
API Gateway control-plane topology
Processor-only Bedrock runtime and IAM isolation
CloudWatch observability contracts
```

The current validated total is:

```text
29 passed, 0 failed
```

Bedrock isolation coverage lives in:

```text
infra/terraform/tests/bedrock_runtime.tftest.hcl
```

Its three runs are:

```text
bedrock_processor_runtime_configuration
bedrock_processor_model_permissions
bedrock_runtime_isolation
```

Those runs assert Processor-only Bedrock environment variables, the exact Nova
Micro foundation-model ARN permission, and the absence of Bedrock settings or
actions on the other three functions.

Observability coverage lives in:

```text
infra/terraform/tests/observability.tftest.hcl
```

Its four runs are:

```text
cloudwatch_alarm_contracts
operations_dashboard_contract
lambda_structured_logging_contract
observability_isolation_boundaries
```

Those runs assert the nine approved alarms, the ten-widget operations dashboard,
JSON / INFO / WARN Lambda logging, AWS-native metric namespaces only, the
absence of notification actions, and the absence of `cloudwatch:PutMetricData`
or `cloudwatch:*` in execution policies.
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

The API Gateway control-plane tests validate:

```text
environment naming
HTTP protocol
development and production log retention
integration ownership
payload format
timeout relationships
exact route keys
AWS_IAM authorization
stage behavior
access-log fields
route throttling
route-scoped Lambda permissions
outputs
stage base URL
```

Tests use a mocked AWS provider and create no resources. Plan-time computed
values use deterministic overrides. The tests validate the dedicated inline
policy identity rather than comparing rendered policy JSON that remains unknown
during plan.

### Bootstrap root tests

Bootstrap coverage lives in:

```text
infra/bootstrap/terraform-state/tests/terraform_state.tftest.hcl
```

Four native test runs validate the account-scoped state bucket contract, security controls, recovery controls, and destroy protection.

Seven static Python tests in `tests/unit/infrastructure/test_terraform_state_bootstrap.py` enforce bootstrap file contracts without AWS.

### Workflow unit tests

Fifty-five tests in `tests/unit/scripts/test_terraform_workflow.py` cover environment file parsing, remote input validation, local-state migration guards, Lambda artifact verification, subprocess invocation, plan manifests, and approved CLI commands (subprocess mocking; no AWS).

Run bootstrap and workflow tests:

```powershell
python -m pytest tests/unit/infrastructure/test_terraform_state_bootstrap.py tests/unit/scripts/test_terraform_workflow.py
```

## Authenticated role contract

When chained mode is used, the S3 backend assumes the state role and the AWS provider assumes the plan role. Both sessions use 15-minute durations. The role ARNs are identifiers, not credentials, and a caller-selected `--output-directory` can place saved plan artifacts outside the repository for approved runner-temporary workflows. The summary utility remains separate from plan generation and does not replace Terraform planning itself.

See [Terraform Plan Authorization](../../docs/architecture/terraform-plan-authorization.md), [Terraform Plan Workflow Runbook](../../docs/operations/terraform-plan-workflow.md), and [Terraform Authorization Bootstrap](../bootstrap/terraform-authorization/README.md).

## State access boundary (future IAM)

When state access IAM is introduced, operators or CI roles will need conceptually:

* `s3:ListBucket` on the state bucket prefix
* `s3:GetObject` and `s3:PutObject` on state objects
* `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on lockfile objects

These roles and policies are not declared yet.

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

HTTP control-plane outputs:

```text
control_plane_api_id
control_plane_api_execution_arn
control_plane_api_base_url
control_plane_api_stage_name
control_plane_api_access_log_group_name
```

Observability outputs:

```text
operations_dashboard_name
```

The base URL includes the named stage and excludes route paths. These
identifiers support alarm wiring, runbook inspection, caller policy design, and
deployment verification. Outputs expose resource identifiers only; they do not
expose credentials or object content.

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

The HTTP control plane declares these security controls:

```text
AWS_IAM on both routes
route-scoped Lambda invoke permissions
structured access logging without payload bodies
no anonymous default or catch-all routes
```

Malware scanning, Object Lock, access logging, and CloudTrail data events are
not part of this slice. AWS Backup, global tables, DAX, Contributor Insights,
and customer-managed KMS are not declared for the table.

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

HTTP control-plane cost decisions:

```text
two explicit routes
route-level throttling
bounded log retention
no payload-body access logging
no provisioned concurrency
no custom domain
no API Gateway caching
```

Observability cost decisions:

```text
native AWS metrics instead of custom metrics
one dashboard per environment
nine focused alarms
bounded log retention
no route-level detailed metrics
no event-source mapping detailed metrics
no X-Ray
no PutMetricData publisher
```

Document bytes bypass API Gateway through presigned S3 upload. The control
plane therefore remains a low-volume authenticated boundary rather than a
document-transfer path.

The Processor memory budget is intentionally larger because it owns document
loading, validation, and AI orchestration. That budget requires deployed
measurement later.

## Deployment safety

Do not treat unguarded `terraform apply` as part of the documented validation path. Offline `offline-check`, `fmt`, `validate`, and `test` are the approved checks for pull requests. CI invokes the same `offline-check` command without AWS credentials.

Artifact absence is accepted for offline validation but not for real deployment. A controlled workflow must build and verify `artifacts/lambda/clouddoc-app.zip` before any future real plan or apply.

Terraform state, saved plans, manifests, and local `terraform.tfvars` remain excluded from Git.

## Intentionally deferred

The following remain intentionally sequenced follow-up work:

```text
JWT authorizer
Amazon Cognito
OAuth
browser frontend
CORS
custom domain
ACM certificate
API keys
usage plans
request models
request transformation
response transformation
API Gateway caching
AWS WAF
X-Ray tracing
synthetic monitoring
caller IAM identities
CI caller identity
reserved Lambda concurrency
deployed smoke tests
load testing
quarantine consumer
automatic replay
operator replay API
message-move permissions
alarm notification actions
manual recovery runbook
provisioned concurrency
provisioned pollers
batch size greater than 1
event filtering
Secrets Manager
versions and aliases
artifact publication to S3
code signing
real AWS deployment
real CloudWatch dashboard and alarm validation
model-access readiness validation
real inference validation
failure injection
recovery testing
SLOs
```

OAuth and JWT remain intentionally deferred while the project establishes a
secure first-party AWS control plane and explicit invocation boundaries.

Additional deferred items from earlier slices also remain separate:

```text
CloudTrail S3 data events
S3 access logging
customer-managed KMS
malware scanning
quarantine workflow
real state-bucket creation in AWS
real remote backend initialization
GitHub OIDC
Terraform state access IAM
remote plan
remote apply
deployment workflow
branch protection activation
AWS CI identities
artifact publication
real environment plan/apply against AWS
state audit logging
cross-region replication
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

- [Infrastructure CI Validation](../../docs/architecture/infrastructure-ci-validation.md)
- [Terraform State and Environment Workflow](../../docs/architecture/terraform-state-and-environment-workflow.md)
- [Terraform state bootstrap README](../bootstrap/terraform-state/README.md)
- [ADR-025: Use S3 Native Locking and Explicit Environment State](../../docs/adr/ADR-025-use-s3-native-locking-and-explicit-environment-state.md)
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
- [API Gateway control-plane infrastructure](../../docs/architecture/api-gateway-control-plane-infrastructure.md)
- [ADR-022: Use API Gateway HTTP API for the control plane](../../docs/adr/ADR-022-use-http-api-for-control-plane.md)
- [Bedrock AI provider integration](../../docs/architecture/bedrock-ai-provider-integration.md)
- [ADR-023: Use Amazon Nova Micro through Bedrock Converse](../../docs/adr/ADR-023-use-amazon-nova-micro-through-bedrock-converse.md)
- [CloudWatch observability](../../docs/architecture/cloudwatch-observability.md)
- [ADR-024: Use native AWS metrics and structured application logs](../../docs/adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)
