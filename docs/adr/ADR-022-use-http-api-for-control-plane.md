# ADR-022: Use API Gateway HTTP API for the Control Plane

## Status

Accepted

## Context

CloudDoc requires a small HTTP control plane for:

```text
creating a DocumentJob
retrieving a DocumentJob
```

The application already contains separate Create Job and Get Job Lambda handlers.

Document upload uses a presigned S3 URL.

Document processing is asynchronous through SQS.

The infrastructure needs one coherent HTTP routing boundary with:

```text
explicit routes
caller authentication
Lambda proxy integration
route-scoped invocation permissions
access logging
route throttling
environment stages
```

The initial control plane is intended for trusted AWS operators, deployment validation, and trusted automation.

It is not yet a browser-facing or anonymous public product API.

## Decision

CloudDoc will use Amazon API Gateway HTTP API as the document-job control-plane boundary.

The API will expose exactly:

```text
POST /v1/document-jobs
GET /v1/document-jobs/{job_id}
```

Both routes will use AWS IAM authorization.

Each route will use an independent Lambda proxy integration and an independent route-scoped Lambda resource-based permission.

## HTTP API Decision

CloudDoc will provision:

```text
aws_apigatewayv2_api.control_plane
```

The API will use:

```text
protocol type = HTTP
default execute-api endpoint = enabled
```

The default endpoint remains enabled for controlled deployment and smoke-test validation.

A custom domain remains a separate decision.

## Route Decision

The API will declare only:

```text
POST /v1/document-jobs
GET /v1/document-jobs/{job_id}
```

The API will not declare:

```text
$default
ANY /
ANY /{proxy+}
```

This prevents unknown methods or paths from reaching a Lambda integration.

## Integration Decision

Both routes will use Lambda proxy integrations:

```text
integration type = AWS_PROXY
integration method = POST
payload format version = 2.0
```

The Create Job integration timeout will be:

```text
15 seconds
```

The Get Job integration timeout will be:

```text
10 seconds
```

These remain longer than the corresponding Lambda timeouts.

## Authorization Decision

Both routes will use:

```text
authorization_type = AWS_IAM
```

Callers must sign requests and possess a matching `execute-api:Invoke` permission.

This stack will not create caller users, long-lived access keys, operator roles, or caller policies.

Caller identity remains part of the deployment and operations boundary.

## OAuth and JWT Decision

OAuth, Amazon Cognito, and JWT authorization are deferred.

The current slice focuses on:

```text
first-party AWS authentication
explicit route ownership
Lambda invocation isolation
operational logging
deployable HTTP infrastructure
```

The architecture retains room for a future JWT authorizer without changing the application-service boundaries.

## Lambda Permission Decision

CloudDoc will create two independent Lambda resource-based permissions.

The Create Job permission will allow:

```text
environment stage
POST
/v1/document-jobs
```

to invoke only the Create Job Lambda.

The Get Job permission will allow:

```text
environment stage
GET
/v1/document-jobs/*
```

to invoke only the Get Job Lambda.

No permission will use:

```text
execution-arn/*/*
```

The Get Job wildcard will cover only the dynamic `job_id` path segment.

## Stage Decision

CloudDoc will use one explicit stage named:

```text
var.environment
```

The stage will use:

```text
auto_deploy = true
```

No standalone deployment resource will be introduced.

The explicit stage provides:

```text
clear environment ownership
stable deployment URL
route-scoped permission ARNs
environment-specific access-log behavior
environment-specific throttling
```

## Access Logging Decision

CloudDoc will provision a managed API access-log group.

Retention will be:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

The stage will emit structured JSON containing:

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

The access logs will exclude:

```text
request bodies
response bodies
Authorization headers
presigned upload URLs
document contents
AWS credentials
```

API access logs and Lambda application logs remain separate operational layers.

## Throttling Decision

The Create Job route will use:

```text
rate = 2 requests per second
burst = 5
```

The Get Job route will use:

```text
rate = 10 requests per second
burst = 20
```

Create Job receives the lower limit because it creates state and an upload capability.

Get Job is read-only and receives a higher initial threshold.

These settings are best-effort operational protections.

They are not authorization, billing enforcement, or hard cost ceilings.

## Output Decision

Terraform will export:

```text
control_plane_api_id
control_plane_api_execution_arn
control_plane_api_base_url
control_plane_api_stage_name
control_plane_api_access_log_group_name
```

The base URL will include the environment stage but not a route path.

## Security Decision

The control plane will preserve:

```text
AWS IAM route authorization
explicit route surface
route-scoped Lambda permissions
no direct API Gateway data-service permissions
no credentials in Terraform
no body logging
no wildcard routing
```

The API will not configure CORS because no browser client exists in the current scope.

## Data-Plane Separation Decision

API Gateway will not proxy document bytes.

Create Job returns a presigned S3 upload URL.

The upload and processing pipeline remain:

```text
client
    → S3
    → SQS
    → Processor Lambda
```

This avoids coupling API request duration and payload limits to document transfer or processing.

## Offline Test Decision

Terraform native tests will use:

```text
mock_provider "aws"
command = plan
```

The tests will validate:

```text
HTTP API foundation
environment naming
development and production log retention
integration ownership
payload format
integration timeout boundaries
exact routes
AWS IAM authorization
stage configuration
access-log structure
route throttling
route-scoped Lambda permissions
API outputs
```

Computed identifiers will be overridden where deterministic plan-time values are required.

The absence of undeclared authorizers, CORS resources, custom domains, and deployment resources remains partly a structural Terraform review.

## Consequences

### Positive

- The control plane has one coherent routing boundary.
- Both routes require signed AWS requests.
- Unknown methods and paths do not invoke Lambda.
- Each route invokes only its corresponding function.
- API and Lambda timeout boundaries are explicit.
- Access logs provide edge-level operational evidence.
- Sensitive bodies and credentials are excluded from logs.
- Route throttling is explicit.
- Document bytes bypass the API.
- Offline tests validate the infrastructure without AWS access.
- Future JWT authorization remains possible.

### Negative

- AWS IAM authorization is not suitable for a general browser audience.
- Callers require AWS credentials or workload identity.
- The default execute-api endpoint remains publicly reachable at the network layer.
- Route throttling is best-effort.
- Auto-deploy provides less explicit deployment promotion control than a manually managed deployment resource.
- No custom domain exists.
- No alarms or synthetic checks exist.
- Real authorization behavior remains unvalidated until deployment.

## Alternatives Considered

### API Gateway REST API

Rejected for the current scope.

Usage plans, API keys, mapping templates, gateway models, and REST-specific features are not required.

HTTP API provides the needed routing and authorization capabilities with a smaller configuration surface.

### Lambda Function URLs

Rejected.

Function URLs would create separate endpoints per function and weaken the coherent control-plane routing boundary.

### Public Routes with Authorization in Lambda

Rejected.

Authentication should occur before Lambda invocation.

Public routes would increase cost and attack surface and duplicate an existing platform capability.

### JWT Authorizer

Deferred.

A browser or external client identity design has not been approved.

AWS IAM is appropriate for the current trusted AWS caller boundary.

### Amazon Cognito

Deferred.

The project does not yet require user registration, browser sessions, hosted UI, or consumer identity lifecycle.

### Custom Lambda Authorizer

Rejected.

No custom authorization logic is required.

A custom authorizer would increase code, latency, failure modes, and operational ownership.

### Default Route

Rejected.

A default route could expose unexpected paths or methods to an integration.

### API-Wide Lambda Permission

Rejected.

A source ARN such as `/*/*` would allow future routes to invoke a function without an intentional permission update.

### Manual Deployment Resource

Deferred.

The environment stage uses automatic deployment to keep the current slice small and deterministic.

A gated promotion workflow may later require explicit deployments.

### Log Request and Response Bodies

Rejected.

Payload logging would increase privacy, security, and cost risk and could expose presigned URLs or document-related data.

### Same Throttling for Both Routes

Rejected.

Create Job mutates state and creates an upload capability, while Get Job is read-only.

Separate thresholds better represent their operational risk.

### Proxy Document Upload Through API Gateway

Rejected.

Presigned S3 upload preserves a smaller, cheaper, and more scalable control-plane boundary.

## Follow-Up Decisions

Future work must define:

```text
caller IAM role and policy
controlled deployment workflow
signed smoke tests
API latency and error alarms
Lambda error alarms
synthetic monitoring
custom-domain requirements
JWT or Cognito identity requirements
CORS policy
reserved concurrency
load-test targets
edge-protection requirements
```