# API Gateway Control Plane Infrastructure

## Status

Implemented as an incremental Terraform infrastructure slice.

This document describes the CloudDoc HTTP control plane that exposes document-job creation and retrieval through Amazon API Gateway HTTP API.

## Purpose

The control plane provides a small authenticated HTTP boundary for:

```text
creating a DocumentJob
retrieving a DocumentJob
```

Document upload and document processing remain separate data-plane operations.

The control plane does not proxy document bytes and does not perform synchronous document processing.

## Architecture

```text
Authenticated client
    → API Gateway HTTP API
        → POST /v1/document-jobs
            → Create Job Lambda
                → DynamoDB PutItem
                → S3 presigned upload URL

        → GET /v1/document-jobs/{job_id}
            → Get Job Lambda
                → DynamoDB GetItem
```

The data plane remains:

```text
client
    → presigned S3 upload
    → S3 ObjectCreated
    → processing SQS queue
    → Document Processor Lambda
```

## Resource Naming

Terraform declares the API name as:

```text
${project_name}-${environment}-control-plane
```

Example:

```text
clouddoc-dev-control-plane
```

The managed access-log group is:

```text
/aws/apigateway/${control_plane_api_name}
```

Example:

```text
/aws/apigateway/clouddoc-dev-control-plane
```

## HTTP API Foundation

Terraform declares:

```text
aws_apigatewayv2_api.control_plane
```

Configured properties:

```text
protocol type = HTTP
default execute-api endpoint = enabled
```

The default execute-api endpoint remains enabled to support controlled deployment validation before a custom domain is introduced.

The API is tagged as:

```text
ApiRole = document-job-control-plane
```

## Why HTTP API

CloudDoc uses API Gateway HTTP API rather than REST API or Lambda Function URLs.

HTTP API provides the required capabilities:

```text
explicit routes
Lambda proxy integrations
AWS IAM authorization
named stages
route-level throttling
structured access logs
future JWT authorizer compatibility
```

REST API capabilities such as usage plans, API keys, request models, mapping templates, and gateway-managed response transformations are not required for the current scope.

Lambda Function URLs would create function-specific endpoints instead of one coherent control-plane routing boundary.

## Routes

The API declares exactly two routes:

```text
POST /v1/document-jobs
GET /v1/document-jobs/{job_id}
```

No route uses:

```text
$default
ANY /
ANY /{proxy+}
```

Unknown methods and paths therefore do not reach a Lambda integration.

## Create Job Route

The route is:

```text
POST /v1/document-jobs
```

It targets:

```text
aws_apigatewayv2_integration.create_job
```

The integration targets:

```text
aws_lambda_function.create_job
```

Expected success response:

```text
201 Created
```

The handler creates an authoritative `DocumentJob` and returns a presigned upload URL.

The API does not accept or proxy document contents.

## Get Job Route

The route is:

```text
GET /v1/document-jobs/{job_id}
```

It targets:

```text
aws_apigatewayv2_integration.get_job
```

The integration targets:

```text
aws_lambda_function.get_job
```

Expected success response:

```text
200 OK
```

A missing job returns:

```text
404 Not Found
```

## Lambda Proxy Integrations

Both integrations use:

```text
integration type = AWS_PROXY
integration method = POST
payload format version = 2.0
```

The integration method is `POST` because API Gateway invokes the Lambda Invoke API.

It is independent of the client-facing route method.

Configured integration timeouts:

```text
Create Job integration = 15 seconds
Create Job Lambda = 10 seconds

Get Job integration = 10 seconds
Get Job Lambda = 5 seconds
```

Each API integration timeout remains longer than the target Lambda timeout.

This keeps the Lambda function as the primary application timeout boundary while allowing API Gateway time to receive the result.

## Authorization

Both routes use:

```text
authorization_type = AWS_IAM
```

Callers must sign requests with AWS Signature Version 4 or Version 4a and possess an `execute-api:Invoke` permission matching the route.

This infrastructure stack does not create:

```text
IAM users
long-lived access keys
operator roles
caller policies
CI caller identities
```

Caller identity ownership belongs to the deployment and operations security boundary.

The default execute-api endpoint is internet-reachable, but the declared routes are not anonymous.

## Request and Correlation Identifiers

The Lambda handlers return:

```text
x-request-id
x-correlation-id
```

These identifiers support traceability.

They are not:

```text
authentication
authorization
tenant identity
trusted caller identity
```

## Stage

Terraform declares:

```text
aws_apigatewayv2_stage.control_plane
```

The stage name is:

```text
var.environment
```

Supported environments are:

```text
dev
staging
prod
```

The stage uses:

```text
auto_deploy = true
```

No standalone API Gateway deployment resource is required.

The deployed base URL follows:

```text
https://{api-id}.execute-api.{region}.amazonaws.com/{environment}
```

## Structured Access Logging

Terraform owns:

```text
aws_cloudwatch_log_group.control_plane_api_access
```

Retention:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

The stage emits structured JSON access logs with exactly:

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

The access logs exclude:

```text
request bodies
response bodies
Authorization headers
presigned upload URLs
document contents
AWS credentials
```

`integrationErrorMessage` is included to make integration and permission failures diagnosable without logging sensitive payloads.

Lambda application logs remain separate from API edge access logs.

## Route Throttling

The Create Job route uses:

```text
rate = 2 requests per second
burst = 5 requests
```

The Get Job route uses:

```text
rate = 10 requests per second
burst = 20 requests
```

Create Job receives the lower limit because it performs a state mutation and creates a presigned upload capability.

Get Job is read-only and receives a higher initial threshold.

These settings are best-effort operational protections.

They are not:

```text
authorization
billing enforcement
a hard cost ceiling
a tenant quota system
```

The limits must be revisited using deployed traffic, latency, and throttling measurements.

## Route-Scoped Lambda Invocation Permissions

API Gateway receives two independent Lambda resource-based permissions.

### Create Job

```text
principal = apigateway.amazonaws.com
action = lambda:InvokeFunction
source = environment stage + POST + /v1/document-jobs
target = Create Job Lambda
```

### Get Job

```text
principal = apigateway.amazonaws.com
action = lambda:InvokeFunction
source = environment stage + GET + /v1/document-jobs/*
target = Get Job Lambda
```

The wildcard in the Get Job permission covers only the dynamic `job_id` path segment.

No permission uses:

```text
execution-arn/*/*
```

One route therefore cannot invoke the other route's Lambda through an API-wide permission.

## Authentication and Invocation Separation

The API uses two independent controls:

```text
AWS_IAM route authorization
    → controls which caller may invoke the HTTP route

aws_lambda_permission
    → controls whether API Gateway may invoke the Lambda
```

A Lambda resource-based permission does not make the HTTP route public.

## Terraform Outputs

The root exports:

```text
control_plane_api_id
control_plane_api_execution_arn
control_plane_api_base_url
control_plane_api_stage_name
control_plane_api_access_log_group_name
```

The base URL includes the named stage but excludes route paths.

Example:

```text
https://abc123.execute-api.us-east-1.amazonaws.com/dev
```

These outputs support:

```text
deployment verification
manual API testing
future CI smoke tests
future caller IAM policies
access-log inspection
```

## Security Boundary

### Explicit Route Surface

Only the approved Create Job and Get Job routes exist.

### AWS IAM Authorization

Both routes require signed and authorized requests.

### Route-Scoped Lambda Permissions

Each API route may invoke only its corresponding Lambda.

### No Data-Service Permissions

API Gateway receives no DynamoDB, S3, SQS, or Bedrock permissions.

### No Payload Access Logging

Sensitive request and response content is excluded from API access logs.

### No Caller Credentials

The Terraform stack creates no long-lived caller credential.

### No Browser Boundary Yet

The API declares no CORS policy and no browser-focused identity provider.

## Failure Semantics

### Unsigned Request

API Gateway rejects the request before Lambda invocation.

### Unauthorized Caller

API Gateway rejects the request because the caller lacks `execute-api:Invoke`.

### Unknown Route or Method

No Lambda is invoked.

### Route Throttling

API Gateway may return:

```text
429 Too Many Requests
```

Clients must retry with bounded exponential backoff.

### Missing Lambda Permission

API Gateway cannot invoke the target Lambda.

The client receives an integration failure and the access log records an integration error.

### Lambda Timeout

The Lambda invocation terminates at its configured timeout.

API Gateway returns an integration failure.

### Dependency Failure

The existing handlers map approved DynamoDB or S3 dependency failures to structured application responses.

### Access Log Delivery Failure

The API may continue serving traffic, but edge-level operational visibility is degraded.

## Scaling Position

API Gateway scales independently of Lambda.

The Create Job and Get Job Lambdas do not configure reserved concurrency in this slice.

DynamoDB uses on-demand capacity.

Document bytes bypass API Gateway through presigned S3 uploads.

Document processing remains asynchronous through SQS.

The control plane remains intentionally small and latency-bounded.

## Cost Posture

Potential cost sources include:

```text
API Gateway requests
Lambda invocations
CloudWatch access-log ingestion
CloudWatch access-log retention
DynamoDB requests
S3 presigned upload operations
```

Cost controls include:

```text
two explicit routes
route-level throttling
bounded log retention
no request or response body logging
no provisioned concurrency
no custom domain
no WAF
no API Gateway caching
```

The current settings prioritize a secure and observable control-plane boundary over feature breadth.

## Offline Testing

The infrastructure is covered by:

```text
infra/terraform/tests/api_gateway_control_plane.tftest.hcl
```

The test uses:

```text
mock_provider "aws"
command = plan
```

Computed identifiers are overridden where plan-time determinism is required.

The tests validate:

```text
environment-scoped API naming
HTTP protocol
default endpoint behavior
development log retention
production log retention
Lambda integration ownership
AWS_PROXY integration type
Lambda Invoke POST method
payload format 2.0
integration timeout boundaries
exact route keys
AWS_IAM authorization
absence of default or ANY routing in declared resources
environment-named stage
automatic deployment
managed access-log destination
exact structured log fields
Create Job throttling
Get Job throttling
route-scoped Lambda permissions
absence of API-wide Lambda source ARNs
API outputs
environment-stage base URL
```

The current locally validated Terraform suite is:

```text
22 passed, 0 failed
```

The tests do not create AWS resources or require AWS credentials.

## Invariants

```text
Only POST /v1/document-jobs invokes Create Job.

Only GET /v1/document-jobs/{job_id} invokes Get Job.

Both routes require AWS IAM authorization.

No default route exists.

No wildcard route exists.

Each Lambda permission is route-scoped.

The Create Job route cannot invoke Get Job.

The Get Job route cannot invoke Create Job.

API Gateway has no direct data-service permission.

Request and response bodies are not included in access logs.

DynamoDB remains authoritative for DocumentJob state.

Document uploads bypass API Gateway.
```

## Intentionally Deferred

The following remain separate decisions:

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
CloudWatch alarms
dashboards
synthetic monitoring
caller IAM identities
CI caller identity
reserved Lambda concurrency
deployed smoke tests
load testing
edge-protection evaluation
```

OAuth and JWT remain intentionally deferred because the current slice establishes a secure first-party AWS control plane, explicit routing, invocation isolation, operational logging, and deployable HTTP infrastructure.

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

No AWS credentials or `terraform apply` are required for the automated validation path.

## Follow-Up Work

The next slice should add the Amazon Bedrock runtime boundary or follow the next approved implementation-plan sequence.

Later operational work should add:

```text
caller IAM policy
controlled deployment
signed smoke tests
API latency alarms
API 4xx and 5xx alarms
Lambda error alarms
synthetic monitoring
load testing
custom-domain decision
browser identity decision
```