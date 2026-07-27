# ADR-024: Use Native AWS Metrics and Structured Application Logs

## Status

Accepted

## Context

CloudDoc spans:

```text
API Gateway
four Lambda runtimes
Amazon S3
Amazon SQS
processing DLQ
reconciliation quarantine queue
Amazon DynamoDB
Amazon Bedrock
```

The system uses:

```text
asynchronous processing
partial SQS batch failures
bounded retries
processing-attempt ownership
conditional state transitions
dead-letter reconciliation
managed AI inference
```

Operational diagnosis requires both:

```text
aggregate service health
per-execution application context
```

Native AWS metrics can answer questions such as:

```text
Is API Gateway returning 5xx responses?
Is the Processor Lambda failing?
Is the processing queue aging?
Are messages visible in the DLQ?
Is Bedrock throttling?
```

Native metrics cannot answer questions such as:

```text
Which job failed?
Which processing attempt owned the work?
Which normalized application outcome occurred?
Which SQS message was returned as failed?
Which Bedrock request ID belongs to the invocation?
```

Logs can provide high-cardinality context, but logging business document content would violate the project's data-minimization boundary.

The project also needs an offline-testable implementation that does not require real AWS resources, credentials, or model invocations.

## Decision

CloudDoc will use:

```text
AWS-native service metrics
+
CloudDoc-owned structured application logs
+
Terraform-managed CloudWatch alarms
+
one Terraform-managed operations dashboard per environment
```

The implementation will not introduce custom application metrics in this slice.

## Structured Logging Decision

CloudDoc will use:

```text
Python standard logging
AWS Lambda JSON logging configuration
StandardOperationalLogger
NullOperationalLogger
```

The operational logger contract will expose:

```text
info
warning
error
```

with:

```text
stable event name
flat approved fields
JSON-safe scalar values
component identity
service identity
```

The logger will not call CloudWatch APIs directly.

## Field Allowlist Decision

Only approved operational fields may be emitted.

The current field set includes:

```text
trace identifiers
job and processing-attempt identifiers
SQS message identity
operation
outcome
normalized error code
exception type
duration
batch counts
provider identity
provider request identity
Bedrock usage metadata
Bedrock latency metadata
retryable flag
```

Unknown fields and unsafe values will be dropped.

Nested objects, lists, event payloads, exception objects, and non-finite numbers will not be serialized.

This protects against accidental logging of:

```text
document content
request bodies
response bodies
raw AWS events
prompts
raw model output
credentials
authorization values
```

## Event Model Decision

Events will use stable dotted names.

The implemented catalog is:

```text
control_plane.request_completed
processing.record_completed
processing.record_failed
processing.batch_completed
reconciliation.record_completed
reconciliation.record_failed
reconciliation.batch_completed
ai_provider.invocation_completed
```

The design favors terminal events over separate start and completion events.

## One Terminal Event Decision

CloudDoc will attempt:

```text
one completion event per control-plane request
one completion event per completed processing workflow
one failed-record event per reportable failed processing message
one batch event per normal processing batch
one completion event per completed reconciliation workflow
one failed-record event per reportable failed reconciliation message
one batch event per normal reconciliation batch
one terminal event per Bedrock invocation
```

Completed processing and reconciliation record events belong to infrastructure adapters.

Failed-record and batch events belong to SQS handlers.

This avoids duplicate success events.

## Application and Domain Boundary Decision

Application and domain services will not depend on logging interfaces.

They continue to own:

```text
business results
state transitions
failure classification
retry decisions
idempotency decisions
```

Delivery and infrastructure adapters translate those results into operational events.

## Logging Failure Decision

Telemetry must never change business behavior.

```text
logger failure
    → event may be lost
    → HTTP response remains unchanged
    → SQS partial batch response remains unchanged
    → provider result or exception remains unchanged
```

The implementation will catch logger failures.

CloudDoc does not claim exactly-once or lossless log delivery.

## Timing Decision

Application duration will use:

```text
time.perf_counter
```

and emit:

```text
duration_ms
```

Negative computed durations will be bounded to zero.

Bedrock provider-reported latency remains a separate optional field:

```text
provider_latency_ms
```

## Control-Plane Decision

Every Create Job and Get Job request will emit:

```text
control_plane.request_completed
```

with:

```text
operation
outcome
status code
request ID
correlation ID
duration
normalized job ID when available
normalized error code when applicable
exception type when applicable
```

The handler will not log request or response bodies.

## SQS Processing Decision

The processing adapter will emit authoritative completed outcomes.

The Processor handler will emit:

```text
record failures
batch completion
```

The telemetry implementation will preserve:

```text
partial batch failure identifiers
message ordering
later sibling processing
fail-fast behavior within one SQS message
malformed outer-event propagation
missing message-ID propagation
```

## Reconciliation Decision

The reconciliation adapter and handler will use the same ownership split as processing.

`dead_recorded` will use warning severity because it represents an acknowledged exhausted-delivery outcome requiring operational attention.

It is not logged as a failed reconciliation.

## Amazon Bedrock Decision

Every Bedrock invocation will attempt one terminal event.

Safe metadata may include:

```text
model ID
provider request ID
stop reason
input token count
output token count
total token count
provider latency
wall-clock duration
normalized provider outcome
```

Telemetry metadata will be optional.

Malformed metadata will not invalidate an otherwise valid model result.

The provider will not log:

```text
document
prompt
raw response
validated result
service error message
exception message
```

## Native Metric Decision

CloudDoc will use these native namespaces:

```text
AWS/ApiGateway
AWS/Lambda
AWS/SQS
AWS/Bedrock
```

The project will not create a custom metric namespace in this slice.

## Metric Dimension Decision

Allowed aggregate dimensions are:

```text
API Gateway
    → ApiId + Stage

Lambda
    → FunctionName

SQS
    → QueueName

Bedrock
    → ModelId
```

High-cardinality identifiers remain logs-only context:

```text
job_id
request_id
correlation_id
processing_attempt_id
sqs_message_id
provider_request_id
```

## Alarm Decision

Terraform will declare nine alarms:

```text
control-plane 5xx
Processor Lambda errors
Reconciler Lambda errors
processing queue age
processing DLQ visible messages
reconciliation quarantine visible messages
Bedrock client errors
Bedrock server errors
Bedrock throttles
```

All alarms will:

```text
use AWS-native metrics
use explicit dimensions
use explicit thresholds
use treat_missing_data = notBreaching
```

## Notification Routing Decision

The initial alarms will not have:

```text
alarm_actions
ok_actions
insufficient_data_actions
```

Notification routing requires an approved operator and incident channel.

Alarm state and notification delivery are separate responsibilities.

## Dashboard Decision

Terraform will declare one environment-scoped dashboard:

```text
${project_name}-${environment}-operations
```

The dashboard will contain:

```text
alarm status
API Gateway traffic and errors
API Gateway latency
Lambda errors and throttles
Lambda duration and concurrency
processing queue health
DLQ and quarantine health
Bedrock invocation health
Bedrock latency
Bedrock token usage
```

The Terraform root will export the dashboard name.

## Lambda Logging Configuration Decision

All four Lambdas will use:

```text
log format = JSON
application log level = INFO
system log level = WARN
```

This preserves operational application events while reducing routine platform noise.

## IAM Decision

Lambda roles will not receive:

```text
cloudwatch:PutMetricData
cloudwatch:*
```

Application code will not own dashboard or alarm management.

Terraform will own CloudWatch alarm and dashboard resources.

## Bedrock Model Invocation Logging Decision

CloudDoc will not enable Amazon Bedrock model invocation logging in this slice.

That feature can capture model input and output.

The project instead records bounded provider metadata through the application-owned logging contract.

## AWS Lambda Powertools Decision

CloudDoc will not introduce AWS Lambda Powertools in this slice.

The current requirements are satisfied by:

```text
standard logging
one small application-owned protocol
explicit field allowlist
explicit dependency injection
existing Lambda JSON logging
```

Powertools may be reconsidered if future requirements justify:

```text
tracing
sampling
idempotency utilities
metrics utility
batch-processing utility
shared multi-service conventions
```

## Custom Metrics Decision

CloudDoc will not use:

```text
PutMetricData
Embedded Metric Format
CloudWatch log metric filters
```

in this slice.

Native metrics already provide the initial aggregate health signals.

Custom business metrics require separate semantics, dimensions, cost controls, and SLO ownership.

## Detailed Metrics Decision

CloudDoc will not enable:

```text
API Gateway route-level detailed metrics
Lambda event-source mapping detailed metrics
```

in this slice.

The initial dashboard and alarms use the service metrics already available for the approved boundaries.

## Distributed Tracing Decision

CloudDoc will not introduce:

```text
AWS X-Ray
OpenTelemetry
trace propagation
trace sampling
```

in this slice.

Request, correlation, job, attempt, message, and provider identifiers provide logs-based operational correlation.

The project does not claim distributed tracing.

## Offline Test Decision

Application telemetry tests will use:

```text
recording logger doubles
raising logger doubles
deterministic sequence timers
fake Bedrock clients
existing service and processor doubles
```

Terraform tests will use:

```text
mock_provider "aws"
command = plan
resource overrides
```

Automated tests will not:

```text
require AWS credentials
create AWS resources
call CloudWatch APIs
invoke Lambda
invoke Bedrock
```

## Consequences

### Positive

- The control plane and asynchronous processing path have stable operational events.
- High-cardinality identifiers remain available for diagnosis.
- Metrics remain low-cardinality and service-owned.
- No custom metric IAM permission is required.
- Logging failures cannot change business behavior.
- Application and domain services remain free of observability dependencies.
- Bedrock metadata is available without logging model content.
- SQS partial batch behavior remains unchanged.
- Operators receive one dashboard covering the primary v1 path.
- Nine focused alarms detect immediate operational failures and queue degradation.
- Alarm declarations are independently testable.
- Dashboard structure is independently testable.
- Automated tests remain offline and deterministic.
- Non-production log retention remains bounded.
- The architecture can later adopt stronger telemetry tools without changing domain behavior.

### Negative

- Alarm state does not notify an external channel yet.
- Native metrics do not provide business-level success ratios.
- Logs are best effort and not transactional.
- Logs-based correlation is not distributed tracing.
- No SLO or error-budget model exists.
- No custom metric captures terminal document-job outcomes.
- Dashboard definitions may be syntactically valid but still require deployed inspection.
- Metric dimensions may produce no data until resources are deployed and receive traffic.
- Logs Insights queries incur operational query cost.
- One terminal event does not show intermediate stage timings.
- The field allowlist requires deliberate maintenance as telemetry evolves.
- Swallowed logger failures can hide observability degradation.
- Bedrock metadata availability depends on the service response.
- Exact production thresholds remain initial values until real traffic is observed.

## Alternatives Considered

### AWS Lambda Powertools Logger

Deferred.

Powertools provides useful conventions, but the current slice requires only a small explicit logging boundary.

Adding it now would expand:

```text
runtime dependency surface
packaging surface
configuration conventions
testing surface
```

without an immediate architectural requirement.

### CloudWatch PutMetricData

Rejected for the current slice.

It would require:

```text
application metric ownership
runtime IAM permission
network calls
retry and timeout behavior
cost controls
dimension governance
```

Native metrics already support the initial operational alarms.

### Embedded Metric Format

Deferred.

EMF could derive custom metrics from structured logs, but it would create a custom metric contract and additional cost/cardinality considerations.

### CloudWatch Logs Metric Filters

Deferred.

Metric filters couple alerting to log text and require a separate parsing and deployment contract.

The current alarm set can use native metrics.

### Only Native Metrics

Rejected as incomplete.

Native metrics cannot identify the affected:

```text
request
job
processing attempt
SQS message
provider request
normalized application outcome
```

Structured application events are still required.

### Only Structured Logs

Rejected as incomplete.

Logs alone would require queries or metric filters for aggregate service health.

Native service metrics already provide better aggregate signals.

### Log Full Events for Easier Debugging

Rejected.

Raw API, SQS, S3, and Bedrock payloads may contain sensitive data and create uncontrolled logging cost.

### Log Exception Messages

Rejected as a default operational contract.

Exception messages may contain:

```text
table names
service details
document fragments
provider messages
internal context
```

Normalized error codes and exception types are sufficient for the initial slice.

### Enable Bedrock Model Invocation Logging

Rejected for the current privacy boundary.

The project does not require full model input and output capture for operations.

### Use High-Cardinality Metric Dimensions

Rejected.

Per-request and per-job dimensions would create unbounded time series and unnecessary cost.

### Enable Route-Level API Gateway Metrics

Deferred.

API- and stage-level signals satisfy the current control-plane alarms.

### Enable Event-Source Mapping Metrics

Deferred.

Queue age, queue depth, Lambda errors, duration, and concurrency provide the initial asynchronous health model.

### Add SNS and Email Notifications Immediately

Deferred.

Notification destinations require ownership, environment policy, subscription confirmation, and escalation procedures.

### Add X-Ray

Deferred.

The project first establishes deterministic logs and native metrics.

Tracing requires a separate propagation, sampling, IAM, cost, and privacy decision.

### Persist Operational Events in DynamoDB

Rejected.

DynamoDB is authoritative for business state, not a telemetry warehouse.

Persisting logs as business records would couple diagnosis to the state model and increase write cost.

### Emit Start and Completion Events

Rejected for the initial implementation.

One terminal event reduces log volume while preserving operation, outcome, duration, and identifiers.

## Follow-Up Decisions

Future work must define:

```text
real AWS dashboard validation
real alarm-state validation
notification destinations
operator ownership
incident severity
escalation policy
runbook links
SLOs
error budgets
custom business metrics
token-to-currency attribution
budget alarms
cost anomaly detection
tracing requirements
centralized logging requirements
PII detection
log redaction
automatic recovery boundaries
```

Deployment validation must confirm:

```text
Lambda JSON event shape
custom extra-field preservation
CloudWatch log-group ownership
native metric dimensions
dashboard rendering
alarm transition behavior
missing-data behavior
Bedrock metric availability
queue-age alarm behavior
DLQ and quarantine alarms
production log volume
production Logs Insights usability
```