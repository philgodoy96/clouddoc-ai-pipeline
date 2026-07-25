# System Design

## Design Objective

CloudDoc AI Pipeline separates synchronous API responsibilities from asynchronous document processing.

The system has two primary execution paths:

### Control plane

Responsible for:

* creating document jobs
* validating upload metadata
* generating pre-signed S3 upload URLs
* returning job status and results

### Processing plane

Responsible for:

* reacting to completed document uploads
* processing documents asynchronously
* invoking the AI provider
* validating model output
* coordinating retries and duplicate delivery
* updating durable job state

This separation prevents document-processing latency and model availability from affecting the synchronous API request path.

## Architecture Overview

```text
┌──────────────────────┐
│  Client Application  │
└──────────┬───────────┘
           │
           │ POST /document-jobs
           ▼
┌──────────────────────┐
│     API Gateway      │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│      API Lambda      │
│                      │
│ - validates request  │
│ - creates job        │
│ - generates IDs      │
│ - creates upload URL │
└───────┬────────┬─────┘
        │        │
        │        │ pre-signed PUT URL
        │        ▼
        │   ┌──────────────────────┐
        │   │ Client uploads to S3 │
        │   └──────────┬───────────┘
        │              ▼
        │   ┌──────────────────────┐
        │   │ Documents S3 Bucket │
        │   └──────────┬───────────┘
        │              │ ObjectCreated event
        │              ▼
        │   ┌──────────────────────┐
        │   │ Processing SQS Queue│
        │   └──────────┬───────────┘
        │              ▼
        │   ┌──────────────────────┐
        │   │  Processor Lambda    │
        │   │                      │
        │   │ - claims job         │
        │   │ - validates object   │
        │   │ - reads document     │
        │   │ - invokes provider   │
        │   │ - validates result   │
        │   │ - persists outcome   │
        │   └─────┬─────────┬──────┘
        │         │         │
        │         │         ▼
        │         │   ┌──────────────────────┐
        │         │   │  Amazon Bedrock      │
        │         │   └──────────────────────┘
        │         │
        ▼         ▼
┌──────────────────────┐
│ DynamoDB Jobs Table  │
└──────────────────────┘

Processing Queue
      │ retries exhausted
      ▼
┌──────────────────────┐
│       SQS DLQ        │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ DLQ Reconciler       │
│ Lambda               │
└──────────┬───────────┘
           ▼
┌──────────────────────┐
│ DynamoDB status=dead │
└──────────────────────┘
```

All Lambda runtimes emit structured logs and operational metrics to Amazon CloudWatch.

## Core Architectural Decisions

## SQS as the processing work queue

The primary processing path is:

```text
S3 → SQS → Processor Lambda
```

SQS is selected because uploaded documents represent durable work that must either be processed successfully or preserved for investigation.

The queue provides:

* durable buffering
* bounded retries
* dead-letter queue integration
* backpressure
* queue-depth visibility
* independent scaling between ingestion and processing

EventBridge is intentionally excluded from the primary v1 path because the initial requirement is durable work processing rather than event fan-out.

## Standard queue instead of FIFO

V1 uses an SQS standard queue.

Document jobs are independently processable and do not require global ordering.

The system accepts at-least-once delivery and handles duplicate effects through application-level idempotency.

FIFO delivery would not remove the need to handle:

* repeated S3 notifications
* processing retries
* concurrent Lambda execution
* external side effects
* partial failures

## Lambda for bounded processing

Lambda is selected because the initial workload is:

* event-driven
* intermittent
* horizontally parallel
* bounded in duration
* cost-sensitive while idle

The v1 document-size and format restrictions must keep processing within Lambda execution, memory, storage, and packaging constraints.

ECS or Fargate remains a future option for workloads that require:

* long-running execution
* large documents
* specialized native dependencies
* predictable sustained compute
* greater runtime control

## Direct S3 upload

The client uploads documents directly to S3 through a time-limited pre-signed URL.

This keeps document bytes out of:

* API Gateway request handling
* Lambda memory
* Lambda execution duration
* application request-body processing

The API remains responsible for controlling the expected bucket, key, content type, and size.

The processor validates the resulting object before inference.

## DynamoDB key design

V1 uses one job item with the partition key:

```text
PK = JOB#{job_id}
```

The primary access pattern is:

```text
Get one job by job_id.
```

No tenant or workspace key is included because authentication and multi-tenancy are outside the v1 product contract.

A future tenant-aware model may introduce workspace ownership or secondary indexes after additional access patterns are defined.

## AI provider abstraction

Application services depend on an internal AI provider contract.

```text
Document Processing Service
            │
            ▼
       AIProvider
        ┌───┴──────────┐
        ▼              ▼
 BedrockProvider   MockAIProvider
```

The provider interface protects application code from:

* Bedrock request formats
* Bedrock response formats
* model-specific SDK behavior
* provider-specific exception types

The provider does not own:

* job state transitions
* DynamoDB updates
* SQS retry behavior
* dead-letter handling
* Lambda response formatting

## Structured output validation

The system uses two validation layers when supported by the selected model:

1. provider-level structured-output constraints
2. application-owned schema validation

Application validation remains mandatory.

The application owns rules for:

* required fields
* allowed document types
* confidence range
* summary constraints
* key-field structure
* human-review behavior
* result-size limits

A successful provider request is not equivalent to a successful document job.

## Supported document format

The first complete workflow supports:

```text
Content type: text/plain
Encoding: UTF-8
Recommended extension: .txt
```

Plain-text input keeps document decoding deterministic while the project proves:

* asynchronous orchestration
* idempotency
* retries
* state transitions
* provider isolation
* AI validation
* observability
* IAM
* Terraform

PDF extraction and OCR are intentionally deferred until the processing workflow is stable.

## Component Boundaries

### API Gateway

Responsibilities:

* expose HTTP routes
* route requests to the API Lambda
* preserve a future authentication boundary

Non-responsibilities:

* store document content
* invoke the AI provider
* coordinate processing retries
* own job state

### API Lambda

Responsibilities:

* validate API requests
* create jobs
* generate workflow identifiers
* persist initial state
* generate upload URLs
* retrieve status and results

Non-responsibilities:

* read uploaded document bodies
* invoke Bedrock
* process queue events
* decide SQS retry behavior

### Amazon S3

Responsibilities:

* store document bytes
* encrypt uploaded objects
* emit upload-completion events
* retain relevant object metadata

Non-responsibilities:

* own job state
* validate business rules
* coordinate processing
* store structured results

### Amazon SQS

Responsibilities:

* buffer document-processing work
* isolate ingestion from worker capacity
* provide retry delivery
* route exhausted messages to a DLQ

Non-responsibilities:

* guarantee unique delivery
* define current business state
* guarantee exactly-once execution

### Processor Lambda

Responsibilities:

* normalize queue and S3 events
* resolve the associated job
* acquire processing ownership
* validate object metadata
* read supported document content
* invoke the AI provider
* validate the candidate result
* persist success or failure
* classify errors
* emit structured logs and metrics

Non-responsibilities:

* expose public API responses
* embed Bedrock SDK logic directly in the handler
* treat all exceptions as equivalent
* own infrastructure configuration

### DynamoDB

Responsibilities:

* own workflow state
* enforce conditional state transitions
* store processing metadata
* store bounded validated results
* support idempotency decisions

Non-responsibilities:

* store raw document bytes
* store unrestricted model payloads
* replace operational logging

## Job State Model

V1 uses the following persisted states:

```text
pending_upload
processing
succeeded
failed
dead
```

### `pending_upload`

The job exists and the client has not yet completed an accepted upload-processing flow.

### `processing`

A processor invocation has successfully acquired the job.

### `succeeded`

A validated result was durably persisted.

### `failed`

The job reached a terminal business failure that should not be retried.

Examples:

* unsupported content type
* oversized object
* invalid UTF-8 content
* invalid controlled object key

### `dead`

Retryable or unknown processing failures exhausted the configured queue retries.

### Allowed transitions

```text
pending_upload → processing
processing     → succeeded
processing     → failed
processing     → pending_upload
processing     → dead
```

Returning to `pending_upload` represents releasing a failed processing claim so the queue can retry the job.

A more explicit retry state may be introduced later if it provides additional operational value.

### Terminal states

```text
succeeded
failed
dead
```

Ordinary duplicate delivery cannot move a terminal job back into active processing.

## Processing Ownership

The processor must acquire a DynamoDB conditional claim before reading the complete document or invoking Bedrock.

Conceptual update:

```text
status = processing
processing_attempt_id = generated identifier
processing_started_at = current timestamp
processing_lease_expires_at = bounded expiration
attempts = attempts + 1
```

Conceptual condition:

```text
current status is pending_upload
or
the previous processing lease has expired
```

Only one concurrent invocation can acquire the valid claim.

A duplicate or losing invocation exits successfully after determining that another worker owns or completed the job.

A duplicate message that requires no work is not considered a processing failure.

## Processing Lease

A status value alone is not a distributed lock.

The job therefore includes:

```text
processing_attempt_id
processing_lease_expires_at
```

The bounded lease prevents a timed-out or terminated Lambda invocation from leaving a job permanently locked in `processing`.

A later invocation may reclaim the job after lease expiration.

## Idempotency Boundary

The system provides idempotent business effects where practical.

It does not claim exactly-once Lambda execution or exactly-once Bedrock inference.

DynamoDB can coordinate processing state, but it cannot create one atomic transaction across:

* Bedrock inference
* DynamoDB result persistence

A narrow failure window exists when inference succeeds but result persistence fails.

In that case, a later retry may invoke Bedrock again.

V1 accepts this bounded duplicate-inference risk rather than adding a more complex durable inference-result staging subsystem.

## Error Classification

### Terminal input errors

Retrying the same input will not produce success.

Examples:

* unsupported content type
* oversized document
* malformed object key
* invalid UTF-8 document
* missing job

Behavior:

* persist `failed`
* acknowledge the queue message
* do not retry

### Retryable dependency errors

The operation may succeed later.

Examples:

* Bedrock throttling
* Bedrock timeout
* temporary S3 error
* temporary DynamoDB error
* transient AWS SDK network error

Behavior:

* release or preserve retry-safe state
* return a record-level failure
* allow SQS to retry

### Unknown or internal errors

The system cannot classify the failure safely.

Examples:

* unexpected exception
* programming defect
* unrecognized provider behavior
* unexpected integration response

Behavior:

* log safe diagnostic metadata
* request bounded retry
* eventually route the message to the DLQ

## SQS Processing Strategy

Initial configuration direction:

```text
Queue type: Standard
Batch size: 1
Partial batch response: Enabled
Maximum receive count: 3
```

Batch size one simplifies:

* processing-attempt accounting
* failure isolation
* troubleshooting
* model cost attribution
* test fixtures

The value may be increased after the processing path is operationally stable.

The queue visibility timeout must remain longer than the Processor Lambda timeout with an appropriate safety margin.

## Dead-Letter Reconciliation

Moving a message to the DLQ does not automatically update DynamoDB.

A dedicated DLQ Reconciler Lambda closes this consistency gap.

Responsibilities:

* consume exhausted queue messages
* recover the associated `job_id`
* conditionally update the job to `dead`
* preserve safe failure context
* emit a structured dead-letter event log

The reconciler does not automatically redrive messages.

Replay remains an explicit operational decision.

## Identifier Model

### `job_id`

Identifies the document-processing business resource.

Stable for the job lifetime.

### `request_id`

Identifies one inbound API request.

Each API request receives a new value.

### `correlation_id`

Identifies the complete workflow.

Created during job creation and persisted for the job lifetime.

### `aws_request_id`

Identifies one Lambda invocation.

Generated by AWS Lambda.

### `processing_attempt_id`

Identifies one acquired processing attempt.

Generated when the Processor Lambda successfully claims the job.

During asynchronous processing, DynamoDB is the trusted source for the workflow correlation identifier.

Client-controlled S3 metadata is not trusted for workflow identity.

## Observability

Application logs use structured JSON.

Common fields include:

```text
timestamp
level
service
environment
event_type
status
job_id
request_id
correlation_id
aws_request_id
processing_attempt_id
error_code
retryable
```

Stable event types include:

```text
job_creation_started
job_created
upload_url_generated
job_status_requested
processing_event_received
processing_claim_acquired
duplicate_processing_skipped
document_validation_failed
document_loaded
ai_inference_started
ai_inference_succeeded
ai_output_invalid
job_succeeded
job_failed
processing_retry_requested
job_dead_lettered
```

Logs must not contain:

* complete document content
* full model prompts
* full raw model responses
* pre-signed URLs
* credentials
* authorization headers

Minimum operational alarms include:

* visible messages in the DLQ
* elevated Processor Lambda error rate
* excessive age of the oldest processing message

## Security

Each Lambda runtime receives a separate least-privilege IAM role.

### API Lambda permissions

May:

* create and read job items
* authorize controlled uploads
* write logs

May not:

* invoke Bedrock
* consume processing messages
* read arbitrary document objects

### Processor Lambda permissions

May:

* consume the processing queue
* read expected document objects
* read and conditionally update jobs
* invoke the approved Bedrock model
* emit logs and approved metrics

May not:

* create upload URLs
* access unrelated S3 buckets
* administer the DynamoDB table
* invoke arbitrary models

### DLQ Reconciler permissions

May:

* consume dead-letter messages
* read and conditionally update jobs
* emit logs and metrics

May not:

* read document bodies
* invoke Bedrock
* create uploads

The S3 bucket uses:

* public-access blocking
* server-side encryption
* controlled prefixes
* HTTPS-only access
* deliberate lifecycle configuration

Customer-managed KMS keys are deferred until a requirement exists for explicit key administration, cross-account access, or compliance-driven controls.

Secrets Manager is not introduced without a real secret to manage.

AWS service access relies on IAM roles rather than static credentials.

## Cost Controls

V1 cost controls include:

* direct S3 uploads
* Lambda compute without idle servers
* DynamoDB on-demand capacity
* bounded SQS retries
* dead-letter preservation
* deterministic mock inference
* document size limits
* restricted content types
* configurable log retention
* no document-content logging
* S3 lifecycle rules
* Terraform destroy documentation
* no NAT Gateway requirement
* no provisioned concurrency
* bounded processor concurrency

Primary cost-risk paths include:

* duplicate Bedrock invocation
* excessive retries
* oversized documents
* verbose logging
* long log retention
* unexpected Lambda concurrency
* abandoned S3 objects

## API Boundaries

### Create document job

```text
POST /document-jobs
```

Request:

```json
{
  "original_filename": "service-agreement.txt",
  "content_type": "text/plain",
  "file_size_bytes": 48219
}
```

Response:

```json
{
  "job_id": "job_...",
  "status": "pending_upload",
  "upload": {
    "method": "PUT",
    "url": "<temporary pre-signed URL>",
    "expires_at": "..."
  },
  "request_id": "req_...",
  "correlation_id": "corr_..."
}
```

The job is persisted before the upload URL is returned.

### Get document job

```text
GET /document-jobs/{job_id}
```

An existing job returns `200 OK` regardless of whether processing succeeded or failed.

Processing failure is a resource state rather than an HTTP transport failure.

## Event Boundary

The Processor Lambda receives an SQS envelope containing an S3 event.

The handler normalizes the external payload into an internal event model before calling application services.

Conceptual event fields:

```text
bucket
key
object_size
object_etag
s3_event_name
s3_event_time
s3_event_sequencer
sqs_message_id
sqs_receive_count
```

Application services do not depend on nested AWS event dictionaries.

## Result Storage

The validated v1 result is stored directly in the DynamoDB job item.

The result remains bounded:

* one document classification
* one concise summary
* a limited key-field map
* confidence
* human-review flag

The application enforces a serialized result-size guardrail.

Large future extraction results may move to S3 while DynamoDB stores the result location and summary metadata.

## Terraform Resource Boundaries

Terraform will manage:

* API Gateway HTTP API
* API Lambda
* Processor Lambda
* DLQ Reconciler Lambda
* Lambda IAM roles and policies
* documents S3 bucket
* processing SQS queue
* processing DLQ
* S3 notification configuration
* Lambda event source mappings
* DynamoDB jobs table
* CloudWatch log groups
* CloudWatch alarms
* environment-specific configuration

Terraform will not manage:

* Bedrock foundation models
* AWS organization configuration
* user authentication
* production DNS
* frontend resources

Bedrock model access and regional availability remain deployment prerequisites.

## Final V1 Decisions

1. Use `S3 → standard SQS → Processor Lambda`.
2. Exclude EventBridge from the primary v1 processing path.
3. Use Lambda for API and bounded document processing.
4. Upload documents directly to S3 through pre-signed URLs.
5. Begin with UTF-8 plain-text documents.
6. Use one DynamoDB table keyed by `PK = JOB#{job_id}`.
7. Store the bounded validated result in the job item.
8. Use DynamoDB conditional writes and processing leases.
9. Accept at-least-once delivery.
10. Design for idempotent business effects.
11. Do not claim exactly-once Bedrock inference.
12. Use one real Bedrock provider and one deterministic mock provider.
13. Validate every AI result with application-owned schemas.
14. Use bounded queue retries and a DLQ.
15. Begin with queue batch size one.
16. Reconcile exhausted messages into `dead` job state.
17. Propagate request, correlation, Lambda, and attempt identifiers.
18. Use structured logs without sensitive document content.
19. Use separate least-privilege IAM roles.
20. Manage infrastructure through Terraform.
