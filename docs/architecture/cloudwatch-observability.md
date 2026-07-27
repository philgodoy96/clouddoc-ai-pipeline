# CloudWatch Observability and Runtime Telemetry

## Status

Implemented as an application, runtime-composition, and Terraform infrastructure slice.

The repository now contains:

```text
CloudDoc-owned structured operational logging contract
standard-library JSON-compatible application events
safe field allowlisting
control-plane request completion telemetry
processing record and batch telemetry
dead-letter reconciliation record and batch telemetry
Amazon Bedrock invocation telemetry
explicit Lambda application and system log levels
nine CloudWatch metric alarms
one CloudWatch operations dashboard
offline application telemetry tests
offline Terraform observability tests
```

Real AWS deployment, dashboard inspection, alarm-state validation, and notification routing remain separate delivery work.

## Purpose

CloudDoc is asynchronous, retry-aware, stateful, and dependent on several managed AWS services.

A successful API response does not prove that the document was processed.

A successful Lambda invocation does not prove that the document job reached an authoritative terminal state.

A failed Bedrock call does not by itself explain whether the message will retry, reach the DLQ, or become a terminal document failure.

The observability boundary therefore provides two complementary forms of operational evidence:

```text
structured application logs
        → execution-level diagnosis
        → request, job, processing-attempt, and provider context

native AWS metrics
        → service health and aggregate behavior
        → alarms and dashboard panels
```

The design intentionally separates:

```text
high-cardinality troubleshooting context
from
low-cardinality metric dimensions
```

## Operational Architecture

```text
Client
  │
  ▼
API Gateway HTTP API
  │
  ├── native AWS/ApiGateway metrics
  │
  ▼
Create Job / Get Job Lambda
  │
  ├── control_plane.request_completed
  │
  ├── native AWS/Lambda metrics
  │
  ▼
DynamoDB / S3 upload boundary
  │
  ▼
SQS processing queue
  │
  ├── native AWS/SQS metrics
  │
  ▼
Document Processor Lambda
  │
  ├── processing.record_completed
  ├── processing.record_failed
  ├── processing.batch_completed
  │
  ├── ai_provider.invocation_completed
  │
  ▼
Amazon Bedrock
  │
  ├── native AWS/Bedrock metrics
  │
  ▼
DynamoDB authoritative completion
  │
  ▼
SQS processing DLQ
  │
  ▼
Dead-Letter Reconciler Lambda
  │
  ├── reconciliation.record_completed
  ├── reconciliation.record_failed
  ├── reconciliation.batch_completed
  │
  ▼
DynamoDB authoritative dead-state reconciliation
```

CloudWatch receives:

```text
Lambda application logs
Lambda platform logs
API Gateway access logs
AWS-native service metrics
alarm state
dashboard definitions
```

CloudWatch does not become a business-state owner.

DynamoDB remains authoritative for `DocumentJob` lifecycle state.

## Observability Ownership

### Application and domain layers

The application and domain layers remain free of logging dependencies.

They own:

```text
business outcomes
error classification
state transitions
processing-attempt ownership
terminal and retryable decisions
```

They do not emit infrastructure telemetry directly.

### Delivery handlers

Delivery handlers own transport-level operational evidence.

They emit:

```text
HTTP request completion events
SQS record failure events
SQS batch completion events
```

They do not decide document-job state.

### Infrastructure adapters

Application-facing infrastructure adapters emit authoritative workflow-completion events after application services return explicit results.

They emit:

```text
processing.record_completed
reconciliation.record_completed
```

They do not duplicate handler-owned retryable failure events.

### Amazon Bedrock adapter

`BedrockAIProvider` owns provider-specific operational metadata because it is the only component that safely sees:

```text
Bedrock provider request ID
stop reason
usage counters
provider latency
normalized provider outcome
```

It does not log model content.

### Terraform

Terraform owns:

```text
Lambda logging configuration
CloudWatch metric alarms
CloudWatch dashboard
dashboard output
alarm and dashboard offline tests
```

Terraform does not configure application event contents.

## Package Structure

```text
src/clouddoc/
├── observability/
│   ├── __init__.py
│   └── operational_logging.py
├── handlers/
│   ├── create_job.py
│   ├── get_job.py
│   ├── process_uploaded_document.py
│   └── reconcile_dead_lettered_document.py
├── infrastructure/
│   ├── application_processing.py
│   └── application_dead_letter_processing.py
├── providers/
│   └── bedrock_ai_provider.py
└── runtime/
    └── composition.py

infra/terraform/
├── observability.tf
├── lambda.tf
├── outputs.tf
└── tests/
    └── observability.tftest.hcl
```

## Operational Logger Contract

The public contract is:

```python
class OperationalLogger(Protocol):
    def info(self, event_name: str, **fields: OperationalFieldValue) -> None: ...
    def warning(self, event_name: str, **fields: OperationalFieldValue) -> None: ...
    def error(self, event_name: str, **fields: OperationalFieldValue) -> None: ...
```

Implementations:

```text
StandardOperationalLogger
NullOperationalLogger
```

### StandardOperationalLogger

`StandardOperationalLogger` uses the Python standard `logging` library.

It emits:

```text
message = event_name
event_name
service
component
approved operational fields
```

The default service name is:

```text
clouddoc
```

The default logger name is derived from:

```text
{service}.{component}
```

The implementation does not call:

```text
CloudWatch Logs API
CloudWatch PutMetricData
AWS SDK
network service
```

Lambda captures standard output and standard logging records through its configured runtime logging boundary.

### NullOperationalLogger

`NullOperationalLogger` discards every event.

It preserves:

```text
silent unit tests
offline composition
components that do not need telemetry
explicit dependency injection
```

## Field Safety Contract

Operational fields must be:

```text
flat
explicitly allowlisted
JSON-safe scalar values
```

Accepted value types:

```text
string
integer
finite float
boolean
null
```

Rejected value types include:

```text
dictionary
list
tuple
exception object
event object
request object
response object
NaN
positive infinity
negative infinity
```

Unknown or unsafe fields are not serialized.

The emitted event may include:

```text
dropped_field_count
```

to indicate that fields were rejected without revealing their names or values.

## Approved Operational Fields

The current allowlist includes:

```text
batch_size
correlation_id
duration_ms
error_code
exception_type
failed_record_count
failure_reason
input_tokens
job_id
model_id
operation
outcome
output_tokens
processed_record_count
processing_attempt_id
provider_error_code
provider_latency_ms
provider_name
provider_request_id
request_id
retryable
sqs_message_id
status_code
stop_reason
total_tokens
```

The allowlist intentionally excludes:

```text
document_text
document_body
request_body
response_body
raw_event
raw_exception
exception_message
object_key
bucket_name
presigned_upload_url
raw_model_response
summary
key_fields
authorization
credentials
```

## Logging Failure Isolation

Operational telemetry is best-effort evidence.

It must never alter a business result.

```text
logging succeeds
    → event is emitted
    → business behavior continues

logging fails
    → event may be lost
    → business behavior continues unchanged
```

`StandardOperationalLogger` catches internal logging exceptions.

Handlers, adapters, and the Bedrock provider also isolate arbitrary injected logger implementations that raise.

The system does not claim:

```text
exactly-once log delivery
lossless logging
transactional coupling between logs and business state
```

## Timing Contract

Measured application durations use:

```python
time.perf_counter
```

The calculation is:

```python
round(max(0.0, timer() - started_at) * 1_000, 3)
```

This produces milliseconds while preventing negative emitted duration values.

Timers are injectable in tests.

Bedrock telemetry distinguishes:

```text
duration_ms
    → wall-clock application duration

provider_latency_ms
    → safe latency metadata reported by Bedrock
```

The provider does not replace wall-clock duration with provider-reported latency.

## Event Naming

Event names use:

```text
lowercase dotted namespaces
```

Examples:

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

The event name is stable operational vocabulary.

Human-readable exception messages are not used as event names or dimensions.

## Control-Plane Telemetry

Every Create Job and Get Job request attempts exactly one terminal event:

```text
control_plane.request_completed
```

There is no separate request-start event.

### Common fields

```text
operation
outcome
status_code
request_id
correlation_id
duration_ms
```

Optional safe fields:

```text
job_id
error_code
exception_type
```

### Operations

```text
create_document_job
get_document_job
```

### Create Job outcomes

```text
201 → succeeded
400 → invalid_request
409 → conflict
503 → dependency_failure
500 → internal_error
```

### Get Job outcomes

```text
200 → succeeded
400 → invalid_request
404 → not_found
503 → dependency_failure
500 → internal_error
```

### Severity mapping

```text
200 through 399 → INFO
400 through 499 → WARNING
500 and above   → ERROR
```

### Security behavior

The handler does not log:

```text
request body
response body
presigned URL
object key
headers
authorization
application error context
exception message
```

Unexpected failures may expose only:

```text
exception_type
normalized error_code
safe trace identifiers
```

## Processing Telemetry

Processing telemetry is split by ownership.

### Infrastructure adapter completion event

`ApplicationUploadedDocumentProcessor` emits:

```text
processing.record_completed
```

after the application workflow returns an authoritative result.

Common fields:

```text
operation = process_document
outcome
job_id
sqs_message_id
duration_ms
```

Optional fields:

```text
processing_attempt_id
failure_reason
```

Outcomes:

```text
processed
effect_already_applied
terminal_failure_recorded
```

Severity:

```text
processed                 → INFO
effect_already_applied    → INFO
terminal_failure_recorded → WARNING
```

The adapter does not log:

```text
AIExtractionResult
summary
key_fields
document content
```

### Handler failed-record event

The Processor SQS handler emits:

```text
processing.record_failed
```

for a reportable failed SQS message.

#### Event parsing failure

```text
outcome = event_rejected
error_code = event_parsing_error
retryable = true
severity = WARNING
```

#### Translated processor failure

```text
outcome = retryable_failure
error_code = uploaded_document_processing_error
retryable = true
severity = ERROR
```

#### Unexpected processor failure

```text
outcome = retryable_failure
error_code = unexpected_processing_error
retryable = true
severity = ERROR
```

A trusted `sqs_message_id` is required for a record event.

`job_id` is included only when parsing produced a trusted normalized event.

### Processing batch event

Every normal Processor batch emits:

```text
processing.batch_completed
```

Fields:

```text
operation = process_document_batch
outcome
batch_size
processed_record_count
failed_record_count
duration_ms
```

Outcomes:

```text
succeeded
completed_with_failures
event_rejected
```

Normal severity:

```text
zero failed messages      → INFO
one or more failed records → WARNING
```

A malformed outer queue event or unreportable message identity emits an error batch event and preserves the existing invocation-failure behavior.

## Dead-Letter Reconciliation Telemetry

### Infrastructure adapter completion event

`ApplicationDeadLetteredDocumentProcessor` emits:

```text
reconciliation.record_completed
```

Common fields:

```text
operation = reconcile_dead_lettered_document
outcome
job_id
sqs_message_id
duration_ms
```

Outcomes:

```text
dead_recorded
effect_already_applied
```

Severity:

```text
dead_recorded          → WARNING
effect_already_applied → INFO
```

For `dead_recorded`, the event includes:

```text
failure_reason = processing_retries_exhausted
```

The warning does not mean the reconciliation failed.

It means an exhausted processing delivery was authoritatively recorded as dead and requires operational attention.

### Handler failed-record event

The Reconciler SQS handler emits:

```text
reconciliation.record_failed
```

Normalized errors include:

```text
dead_letter_event_parsing_error
dead_lettered_document_processing_error
unexpected_reconciliation_error
```

### Reconciliation batch event

Every normal reconciliation batch emits:

```text
reconciliation.batch_completed
```

Fields:

```text
operation = reconcile_dead_letter_batch
outcome
batch_size
processed_record_count
failed_record_count
duration_ms
```

Normal outcomes:

```text
succeeded
completed_with_failures
```

Malformed outer events and missing message identifiers preserve the current invocation-failure behavior and emit one safe error batch event.

## Amazon Bedrock Telemetry

Every `BedrockAIProvider.extract()` call attempts exactly one terminal event:

```text
ai_provider.invocation_completed
```

There is no request-start event.

### Common fields

```text
operation = extract_document
outcome
provider_name = bedrock
model_id
correlation_id
processing_attempt_id
duration_ms
```

### Safe response metadata

When valid and present:

```text
provider_request_id
stop_reason
input_tokens
output_tokens
total_tokens
provider_latency_ms
```

Metadata is optional and independently validated.

The provider does not coerce:

```text
string token counts
floating-point token counts
boolean token counts
negative values
non-finite latency
```

The provider does not derive missing total tokens.

### Success outcome

```text
outcome = succeeded
retryable = false
severity = INFO
```

The event is emitted only after:

```text
response-envelope validation
strict JSON parsing
AIExtractionResult validation
```

### Invalid response outcome

```text
outcome = invalid_response
provider_error_code = ai_provider_invalid_response
exception_type = AIProviderInvalidResponseError
retryable = false
severity = WARNING
```

### Timeout

```text
outcome = timed_out
retryable = true
severity = ERROR
```

### Throttling

```text
outcome = throttled
retryable = true
severity = WARNING
```

### Temporary unavailability

```text
outcome = unavailable
retryable = true
severity = ERROR
```

### Configuration or authorization failure

```text
outcome = configuration_error
retryable = true
severity = ERROR
```

Configuration failure remains an operational dependency failure.

It does not become a terminal document failure.

### Unexpected provider implementation failure

```text
outcome = internal_error
provider_error_code = unexpected_provider_error
exception_type
severity = ERROR
```

The exact unexpected exception is re-raised unchanged.

### Prohibited provider content

The provider never logs:

```text
document text
system prompt
user prompt
raw Converse response
raw model output
summary
key fields
confidence
human-review decision
service error message
exception message
```

## Runtime Composition

Runtime composition accepts one operational logger boundary for the asynchronous processor graph.

```text
StandardOperationalLogger(component="document-processor")
        │
        ├── ApplicationUploadedDocumentProcessor
        └── BedrockAIProvider
```

The Reconciler uses:

```text
StandardOperationalLogger(component="dead-letter-reconciler")
```

The control-plane handlers use:

```text
StandardOperationalLogger(component="create-job")
StandardOperationalLogger(component="get-job")
```

Explicit dependency injection remains authoritative.

When an explicit `ai_provider_factory` is supplied:

```text
the explicit provider wins
the configured Bedrock provider is not constructed
the logger does not wrap or replace the explicit provider
```

## Lambda Logging Configuration

All four Lambdas declare:

```hcl
logging_config {
  log_format            = "JSON"
  application_log_level = "INFO"
  system_log_level      = "WARN"
}
```

Consequences:

```text
application INFO, WARNING, and ERROR events remain available
routine platform logs below WARN are suppressed
records are emitted through Lambda JSON logging controls
```

The four functions retain independent CloudWatch log groups.

Retention remains:

```text
dev = 14 days
staging = 14 days
prod = 30 days
```

## Metric Strategy

The current observability slice uses:

```text
AWS-native service metrics
```

It does not use:

```text
CloudWatch PutMetricData
Embedded Metric Format
CloudWatch Logs metric filters
custom metric namespace
application-defined metric dimensions
```

This keeps:

```text
runtime IAM unchanged
application code free of metric clients
aggregate service signals aligned with AWS ownership
offline infrastructure tests simple and deterministic
```

## Metric Sources

### API Gateway

Namespace:

```text
AWS/ApiGateway
```

Dimensions:

```text
ApiId
Stage
```

Dashboard metrics:

```text
Count
4xx
5xx
Latency p95
IntegrationLatency p95
```

Route-level detailed metrics remain disabled.

### Lambda

Namespace:

```text
AWS/Lambda
```

Dimension:

```text
FunctionName
```

Dashboard metrics:

```text
Errors
Throttles
Duration p95
ConcurrentExecutions
```

Functions:

```text
Create Job
Get Job
Document Processor
Dead-Letter Reconciler
```

### SQS

Namespace:

```text
AWS/SQS
```

Dimension:

```text
QueueName
```

Dashboard metrics:

```text
ApproximateNumberOfMessagesVisible
ApproximateNumberOfMessagesNotVisible
ApproximateAgeOfOldestMessage
```

Queues:

```text
processing queue
processing DLQ
reconciliation quarantine queue
```

### Amazon Bedrock

Namespace:

```text
AWS/Bedrock
```

Dimension:

```text
ModelId = amazon.nova-micro-v1:0
```

Dashboard metrics:

```text
Invocations
InvocationClientErrors
InvocationServerErrors
InvocationThrottles
InvocationLatency
InputTokenCount
OutputTokenCount
```

## CloudWatch Alarms

The infrastructure declares nine alarms.

| Alarm | Metric | Threshold |
| --- | --- | --- |
| Control-plane 5xx | `AWS/ApiGateway 5xx` | Sum ≥ 1 in 5 minutes |
| Processor Lambda errors | `AWS/Lambda Errors` | Sum ≥ 1 in 5 minutes |
| Reconciler Lambda errors | `AWS/Lambda Errors` | Sum ≥ 1 in 5 minutes |
| Processing queue age | `ApproximateAgeOfOldestMessage` | Maximum ≥ 300 seconds in 2 of 3 one-minute periods |
| Processing DLQ visible | `ApproximateNumberOfMessagesVisible` | Maximum ≥ 1 |
| Reconciliation quarantine visible | `ApproximateNumberOfMessagesVisible` | Maximum ≥ 1 |
| Bedrock client errors | `InvocationClientErrors` | Sum ≥ 1 in 5 minutes |
| Bedrock server errors | `InvocationServerErrors` | Sum ≥ 1 in 5 minutes |
| Bedrock throttles | `InvocationThrottles` | Sum ≥ 1 in 5 minutes |

Every alarm uses:

```text
comparison operator = GreaterThanOrEqualToThreshold
treat missing data = notBreaching
```

## Alarm Notification Boundary

The alarms intentionally have no:

```text
alarm_actions
ok_actions
insufficient_data_actions
```

There is not yet an approved:

```text
operator identity
incident channel
email subscription
Slack integration
PagerDuty integration
environment-specific escalation policy
```

Alarm state is implemented.

Notification routing is deferred until the deployment and operational-response boundary is approved.

## Operations Dashboard

Terraform declares:

```text
aws_cloudwatch_dashboard.operations
```

Dashboard name:

```text
${project_name}-${environment}-operations
```

Default local name:

```text
clouddoc-dev-operations
```

The Terraform root exports:

```text
operations_dashboard_name
```

The default view is:

```text
last six hours
```

The dashboard contains ten widgets.

### 1. Operational alarm status

Displays all nine alarm states.

### 2. Control plane traffic and errors

Displays:

```text
requests
4xx
5xx
```

### 3. Control plane latency

Displays:

```text
Latency p95
IntegrationLatency p95
```

### 4. Lambda errors and throttles

Displays errors and throttles for all four functions.

### 5. Lambda duration and concurrency

Displays:

```text
Duration p95
ConcurrentExecutions
```

for all four functions.

### 6. Processing queue health

Displays:

```text
visible messages
in-flight messages
oldest-message age
```

### 7. Dead-letter and quarantine health

Displays visible-message and oldest-message-age signals for:

```text
processing DLQ
reconciliation quarantine queue
```

### 8. Amazon Bedrock invocations and errors

Displays:

```text
successful invocations
client errors
server errors
throttles
```

### 9. Amazon Bedrock invocation latency

Displays:

```text
InvocationLatency p95
```

### 10. Amazon Bedrock token usage

Displays:

```text
InputTokenCount Sum
OutputTokenCount Sum
```

## Cardinality Boundary

High-cardinality identifiers are valid in logs:

```text
job_id
request_id
correlation_id
processing_attempt_id
sqs_message_id
provider_request_id
```

They are not valid metric dimensions in the current slice.

The dashboard and alarms contain no:

```text
job_id
request_id
correlation_id
processing_attempt_id
provider_request_id
document field
raw model field
custom CloudDoc metric namespace
```

## CloudWatch Logs Insights Examples

These queries are operational examples.

They are not application contracts.

### Find one correlation flow

```text
fields @timestamp, event_name, component, operation, outcome,
       request_id, correlation_id, job_id, processing_attempt_id
| filter correlation_id = "correlation-001"
| sort @timestamp asc
```

### Find processing failures

```text
fields @timestamp, event_name, outcome, error_code, exception_type,
       job_id, processing_attempt_id, sqs_message_id, retryable
| filter event_name = "processing.record_failed"
| sort @timestamp desc
| limit 100
```

### Find terminal processing outcomes

```text
fields @timestamp, outcome, job_id, processing_attempt_id,
       failure_reason, duration_ms
| filter event_name = "processing.record_completed"
| filter outcome = "terminal_failure_recorded"
| sort @timestamp desc
```

### Find Bedrock failures

```text
fields @timestamp, outcome, provider_error_code, exception_type,
       model_id, correlation_id, processing_attempt_id,
       provider_request_id, duration_ms
| filter event_name = "ai_provider.invocation_completed"
| filter outcome != "succeeded"
| sort @timestamp desc
```

### Find exhausted processing reconciliations

```text
fields @timestamp, outcome, job_id, sqs_message_id,
       failure_reason, duration_ms
| filter event_name = "reconciliation.record_completed"
| filter outcome = "dead_recorded"
| sort @timestamp desc
```

Queries must not add document content to logs merely to improve searchability.

## Incident Triage Flow

### Control-plane failure

```text
control-plane 5xx alarm
    → inspect API Gateway 5xx and latency
    → inspect Create Job and Get Job Lambda errors
    → query control_plane.request_completed
    → follow request_id and correlation_id
```

### Processing backlog

```text
processing queue age alarm
    → inspect queue visible and in-flight counts
    → inspect Processor concurrency and duration
    → inspect Processor Lambda errors
    → query processing.batch_completed
    → query processing.record_failed
```

### DLQ message present

```text
processing DLQ visible alarm
    → inspect reconciliation Lambda errors
    → query reconciliation.record_completed
    → query reconciliation.record_failed
    → inspect authoritative DynamoDB job state
```

### Reconciliation quarantine present

```text
reconciliation quarantine alarm
    → preserve message
    → inspect reconciler failure logs
    → inspect authoritative job state
    → use approved operator recovery procedure
```

Automatic replay is not performed by this slice.

### Bedrock failure

```text
Bedrock client/server/throttle alarm
    → inspect native Bedrock metrics
    → query ai_provider.invocation_completed
    → inspect normalized outcome
    → correlate through processing_attempt_id and correlation_id
    → distinguish configuration, throttling, timeout, and service failure
```

## Security and Privacy

The observability design applies data minimization.

It records identifiers and normalized outcomes required for diagnosis.

It does not record business document content.

Prohibited content includes:

```text
source document bytes
document text
prompts
raw AI output
validated AI result
summary
key fields
upload URLs
authorization headers
AWS credentials
raw request bodies
raw response bodies
raw SQS message bodies
complete AWS event objects
complete exception contexts
```

The system does not enable account-level Bedrock model invocation logging because that feature can capture model input and output.

## IAM Boundary

Application logging continues to require only function-scoped CloudWatch Logs permissions:

```text
logs:CreateLogStream
logs:PutLogEvents
```

Lambda execution roles do not receive:

```text
cloudwatch:PutMetricData
cloudwatch:*
```

The dashboard and alarms are Terraform-managed infrastructure resources.

Application code does not create or update them.

## Reliability Invariants

```text
Observability never changes a business outcome.

Logging failure never changes an HTTP response.

Logging failure never changes SQS partial batch failure behavior.

Logging failure never changes provider result validation.

Application and domain services remain free of logging dependencies.

Every production control-plane request attempts one completion event.

Every normal SQS batch attempts one batch completion event.

Every reportable failed SQS record attempts one failure event.

Every completed processing workflow attempts one record completion event.

Every completed reconciliation workflow attempts one record completion event.

Every Bedrock invocation attempts one terminal provider event.

Completed record events are not duplicated between adapters and handlers.

Request and job identifiers remain logs-only context.

Native AWS metrics remain authoritative for aggregate alarms.

DynamoDB remains authoritative for document-job lifecycle state.

The system does not claim distributed tracing.

The system does not claim exactly-once log delivery.

The system does not claim real AWS observability validation yet.
```

## Cost Position

Implemented cost controls include:

```text
native AWS metrics instead of custom metrics
no PutMetricData calls
no Embedded Metric Format
no log metric filters
no route-level detailed API metrics
no event-source mapping detailed metrics
no X-Ray tracing
one dashboard per environment
nine focused alarms
one terminal control-plane event per request
one terminal Bedrock event per invocation
one batch event per SQS batch
no duplicate handler success event
14-day non-production log retention
30-day production log retention
```

Potential costs include:

```text
CloudWatch Logs ingestion
CloudWatch Logs retention
CloudWatch alarms
CloudWatch dashboard
Logs Insights queries
```

The final production cost profile requires deployed traffic evidence.

## Automated Testing

### Operational logger tests

Tests verify:

```text
runtime protocol compliance
INFO, WARNING, and ERROR severity
service and component normalization
approved field emission
unknown field rejection
nested and opaque value rejection
non-finite value rejection
invalid event-name rejection
logger-level behavior
constructor validation
logger failure isolation
null logger behavior
```

### Control-plane handler tests

Tests verify:

```text
one completion event per request
success and normalized error outcomes
deterministic duration
normalized job identifiers
request and correlation identifiers
safe exception types
no exception messages
no response payload leakage
production logger wiring
raising-logger isolation
unchanged HTTP behavior
```

### Processing and reconciliation tests

Tests verify:

```text
authoritative adapter completion outcomes
handler-owned failed-record outcomes
one normal batch event
partial batch response preservation
malformed outer event propagation
missing message identity propagation
later record processing after sibling failure
processor warm caching
safe identifiers
no event-body leakage
raising-logger isolation
```

### Bedrock provider tests

Tests verify:

```text
one terminal event per invocation
success metadata
optional malformed metadata tolerance
invalid-response telemetry
normalized provider-failure telemetry
unexpected failure telemetry
logger isolation
no prompt or model-result leakage
unchanged provider behavior
```

### Terraform tests

`infra/terraform/tests/observability.tftest.hcl` contains:

```text
cloudwatch_alarm_contracts
operations_dashboard_contract
lambda_structured_logging_contract
observability_isolation_boundaries
```

The tests verify:

```text
exact nine-alarm contract
exact native metric namespaces
exact metric dimensions
thresholds and evaluation windows
notBreaching missing-data behavior
ten-widget dashboard
dashboard output
Lambda JSON / INFO / WARN logging
absence of notification actions
absence of high-cardinality dashboard values
absence of custom metric namespace
absence of PutMetricData permissions
```

The observability tests use:

```text
mock_provider "aws"
command = plan
```

They do not:

```text
create AWS resources
require AWS credentials
call CloudWatch
invoke Lambda
invoke Bedrock
```

The observability file adds four Terraform test runs.

The expected complete Terraform result is:

```text
29 passed, 0 failed
```

## Failure Modes

### Structured logger raises

The event may be lost.

Business processing continues unchanged.

### Timer returns decreasing values

The emitted duration is bounded at zero.

### Unknown field supplied

The field is dropped.

The event may include `dropped_field_count`.

### Unsafe nested field supplied

The field is dropped without serialization.

### Control-plane response lacks integer status code

Telemetry is skipped safely.

The response remains unchanged.

### SQS outer event malformed

One safe batch failure event is attempted.

The existing invocation-level exception is re-raised.

### SQS record lacks message ID

One safe batch failure event is attempted.

No record-level event is emitted because a reportable identity does not exist.

The existing invocation-level exception is re-raised.

### Bedrock telemetry metadata malformed

Unsafe metadata is omitted.

Model-result acceptance remains governed by the response and application contracts.

### Bedrock response invalid

A warning provider event is attempted.

The existing `AIProviderInvalidResponseError` remains authoritative.

### CloudWatch alarm has no action

The alarm changes state but does not notify an external channel.

Operators must inspect CloudWatch until notification routing is implemented.

### Dashboard panel has no data

The service may have no recent traffic, the resource may not be deployed, the dimension may be incorrect, or telemetry may not yet exist.

Offline tests validate declarations, not deployed metric availability.

### Application logs unavailable

Diagnosis falls back to native service metrics and authoritative state.

The system does not assume logs are a transactional record.

## Intentionally Deferred

```text
real AWS deployment
real dashboard inspection
real alarm-state validation
SNS alarm notifications
email subscriptions
Slack integration
PagerDuty integration
environment-specific escalation policies
operator on-call ownership
SLOs
error budgets
custom application metrics
Embedded Metric Format
CloudWatch log metric filters
route-level API Gateway detailed metrics
Lambda event-source mapping detailed metrics
AWS X-Ray
OpenTelemetry
distributed tracing
trace sampling
AWS Lambda Powertools
centralized multi-account logging
cross-account dashboard aggregation
log subscription filters
SIEM integration
PII detection
automatic log redaction
Bedrock model invocation logging
token-to-currency attribution
AWS Budgets
cost anomaly detection
automatic DLQ replay
operator recovery tooling
```

These capabilities require explicit ownership, cost, privacy, and incident-response decisions.

## Validation Commands

```bash
python -m pytest tests/unit/observability/test_operational_logging.py -q
python -m pytest tests/unit/handlers/test_create_job.py tests/unit/handlers/test_get_job.py -q
python -m pytest tests/unit/handlers/test_process_uploaded_document.py -q
python -m pytest tests/unit/handlers/test_reconcile_dead_lettered_document.py -q
python -m pytest tests/unit/providers/test_bedrock_ai_provider.py -q
python -m pytest tests/unit/runtime/test_composition.py -q
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test -filter=tests/observability.tftest.hcl
terraform -chdir=infra/terraform test
make check
make lambda-package-check
git diff --check
```

No AWS credentials are required for the automated validation path.

## Related Documentation

- [System Design](system-design.md)
- [API Gateway Delivery Boundary](api-gateway-handlers.md)
- [Processor Lambda Batch Handler](processor-lambda-batch-handler.md)
- [Dead-Letter Job Reconciliation](dead-letter-job-reconciliation.md)
- [Runtime Composition](runtime-composition.md)
- [Lambda Runtime Infrastructure](lambda-runtime-infrastructure.md)
- [Amazon Bedrock AI Provider Integration](bedrock-ai-provider-integration.md)
- [ADR-024: Use Native AWS Metrics and Structured Application Logs](../adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)

## AWS References

- [Using Python logging with AWS Lambda](https://docs.aws.amazon.com/lambda/latest/dg/python-logging.html)
- [AWS Lambda metrics](https://docs.aws.amazon.com/lambda/latest/dg/monitoring-metrics-types.html)
- [Amazon API Gateway HTTP API metrics](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-metrics.html)
- [Amazon SQS CloudWatch metrics](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-available-cloudwatch-metrics.html)
- [Amazon Bedrock runtime metrics](https://docs.aws.amazon.com/bedrock/latest/userguide/monitoring-runtime-metrics.html)
- [CloudWatch dashboard body structure](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Dashboard-Body-Structure.html)
- [Amazon Bedrock model invocation logging](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)