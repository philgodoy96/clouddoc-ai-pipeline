# Project Context

## Overview

CloudDoc AI Pipeline is a production-minded AWS serverless document intelligence platform.

The system accepts business documents through secure Amazon S3 uploads, processes them asynchronously with Amazon SQS and AWS Lambda, invokes Amazon Bedrock for document classification and structured extraction, validates the model output, and stores job state and results in Amazon DynamoDB.

The platform is designed as a realistic event-driven backend system rather than an isolated AI demonstration.

## Business Problem

Organizations frequently receive documents through workflows such as:

* customer onboarding
* contract management
* billing operations
* internal reporting
* customer support
* supplier management
* compliance review

These documents often require employees to classify their type, identify important fields, create summaries, and determine whether manual review is necessary.

Manual processing introduces several operational problems:

* processing time increases with document volume
* classification can become inconsistent
* relevant fields may be missed
* employees repeat low-value extraction work
* downstream systems receive unstructured information
* failures are difficult to trace
* AI responses may be malformed or unreliable

CloudDoc AI Pipeline provides a reusable processing capability that transforms an uploaded document into a validated result.

Example result:

```json
{
  "document_type": "contract",
  "summary": "A service agreement defining responsibilities and payment terms.",
  "key_fields": {
    "effective_date": "2026-08-01",
    "renewal_term": "12 months"
  },
  "confidence": 0.91,
  "requires_human_review": false
}
```

The platform does not assume that model output is trustworthy. AI responses are treated as untrusted external data and must pass application-owned validation before becoming successful processing results.

## Business Value

The system demonstrates how an organization can:

* reduce repetitive document-processing work
* standardize document metadata
* integrate AI into an asynchronous business workflow
* isolate document ingestion from model inference
* absorb processing spikes safely
* retry transient failures
* identify documents requiring human review
* investigate failed jobs without losing events
* control cloud and model inference costs

## Actors

### Client Application

The client application represents a trusted internal application or integration consuming the platform.

Responsibilities:

* create document-processing jobs
* provide document metadata
* upload documents using pre-signed S3 URLs
* query job status
* retrieve successful results
* display failed or review-required outcomes

The client does not upload the document body through the application API.

### API Lambda

The API Lambda is the synchronous control-plane entry point.

Responsibilities:

* validate job creation requests
* generate workflow identifiers
* create the initial DynamoDB job record
* generate time-limited S3 upload URLs
* retrieve job status and results
* return stable API responses

The API Lambda does not perform document processing or AI inference.

### Amazon S3

Amazon S3 is the authoritative storage location for uploaded document objects.

Responsibilities:

* receive direct client uploads
* store documents under controlled object keys
* encrypt stored objects
* emit object-created events
* preserve document metadata required by processing

S3 stores document bytes. DynamoDB stores workflow state and validated results.

### Amazon SQS

Amazon SQS is the asynchronous processing buffer.

Responsibilities:

* decouple document upload from processing
* absorb temporary processing spikes
* provide at-least-once delivery
* support bounded retries
* route repeatedly failing messages to a dead-letter queue

Duplicate message delivery is an expected system behavior.

### Processor Lambda

The Processor Lambda is the asynchronous document-processing worker.

Responsibilities:

* consume SQS messages
* resolve the associated document job
* reject stale or duplicate work safely
* validate S3 object metadata
* retrieve supported document content
* invoke the configured AI provider
* validate the structured result
* update job state
* classify failures as retryable or terminal
* produce structured operational logs

### Amazon Bedrock

Amazon Bedrock provides managed model inference.

The focused v1 responsibilities are:

* document classification
* concise summarization
* key-field extraction
* confidence estimation
* human-review recommendation

Bedrock is accessed through an internal provider abstraction.

### Amazon DynamoDB

DynamoDB is the authoritative workflow-state store.

Responsibilities:

* store document job lifecycle state
* store document metadata
* record processing attempts
* store validated processing results
* store normalized failure information
* enforce conditional state transitions
* support idempotency decisions

### Amazon CloudWatch

CloudWatch provides operational visibility.

Responsibilities:

* retain structured application logs
* expose native Lambda and SQS metrics
* support troubleshooting through workflow identifiers
* reveal retries, errors, throttling, and dead-letter behavior
* support alarms for critical operational conditions

### Platform Engineer

The platform engineer deploys and operates the system.

Responsibilities:

* provision infrastructure using Terraform
* configure environments
* review IAM permissions
* enable Bedrock model access
* inspect failed jobs and dead-letter messages
* monitor cloud costs
* troubleshoot events
* destroy development infrastructure safely

## Core Business Flow

1. A client requests a document-processing job.
2. The API creates the job and returns a `job_id` and pre-signed upload URL.
3. The client uploads the document directly to Amazon S3.
4. The S3 object-created event is delivered to Amazon SQS.
5. The Processor Lambda consumes the queue message.
6. The processor validates the job and uploaded object.
7. The processor invokes the configured AI provider.
8. The model response is validated as structured application data.
9. The processor stores the result and final job state in DynamoDB.
10. The client queries the API for job status and result.
11. Retryable failures are retried through SQS.
12. Exhausted messages are preserved in a dead-letter queue.
13. Structured logs include the workflow identifiers required for troubleshooting.

## Core Resources

### Document Job

Represents one document-processing workflow.

Expected data includes:

* `job_id`
* current status
* document storage location
* original filename
* content type
* file size
* processing attempt count
* maximum attempts
* validated result
* normalized failure information
* provider and model metadata
* lifecycle timestamps
* request and correlation identifiers

### Document Object

Represents the uploaded source document stored in S3.

The object is associated with a job through a controlled key generated by the platform.

### Processing Result

Represents the validated output accepted by the application.

Expected fields:

* document type
* summary
* extracted key fields
* confidence
* human-review requirement

### Processing Attempt

Represents one processor invocation that successfully acquired the right to process a job.

### Correlation Context

Represents the identifiers used to trace the workflow across API, S3, SQS, Lambda, Bedrock, DynamoDB, and CloudWatch.

## Critical Invariants

### Stable job identity

Every workflow has one immutable `job_id`.

The same identifier connects:

* the API response
* the DynamoDB item
* the S3 object key
* the processing event
* application logs
* the final result

### Job creation precedes upload authorization

A valid job record must exist before the client receives an upload URL.

### Controlled object keys

The platform generates the expected S3 object key.

Clients do not choose arbitrary storage paths.

### DynamoDB owns workflow state

DynamoDB is the authoritative source for job lifecycle state.

Logs and queue messages provide operational evidence but do not define the current business state.

### State transitions are explicit

Jobs may only move through approved lifecycle transitions.

Terminal states cannot return to active processing through ordinary duplicate delivery.

### Successful inference is not sufficient

A successful Bedrock request does not make a document job successful.

The result must pass application validation and be persisted durably.

### Duplicate delivery must be safe

Repeated S3 or SQS delivery must not:

* create duplicate jobs
* overwrite successful results
* produce invalid state transitions
* trigger unnecessary inference after completion is already known

### Processing claims are bounded

A processor must acquire ownership before invoking Bedrock.

The ownership mechanism must expire so that timed-out or terminated workers do not leave jobs permanently locked.

### Correlation identifiers remain stable

A workflow-level `correlation_id` remains unchanged for the lifetime of a job.

Lambda invocation identifiers do not replace the workflow correlation identifier.

### Sensitive content is not logged

Application logs must not include:

* full document content
* full model prompts
* complete raw model responses
* pre-signed URLs
* credentials
* authorization values

### Provider details remain isolated

Application orchestration depends on an internal AI provider contract rather than directly on Bedrock SDK structures.

## Main Failure Modes

The system must account for:

* invalid job creation requests
* uploads that are never completed
* unexpected S3 objects
* missing S3 objects
* unsupported content types
* oversized documents
* invalid UTF-8 content
* Bedrock throttling
* Bedrock timeouts
* malformed model responses
* structurally invalid AI output
* duplicate SQS messages
* concurrent processing attempts
* DynamoDB conditional-write conflicts
* persistence failure before inference
* persistence failure after inference
* Lambda timeout
* poison messages
* exhausted retries
* incorrect IAM permissions

Failures must be classified as terminal, retryable, or unknown.

## Minimal V1 Scope

V1 includes:

* document job creation
* direct S3 upload through a pre-signed URL
* asynchronous SQS-based processing
* Lambda-based API and processor runtimes
* UTF-8 plain-text document support
* Amazon Bedrock integration
* structured AI output validation
* deterministic mock AI provider
* DynamoDB job-state persistence
* conditional processing ownership
* bounded retries
* dead-letter queue behavior
* dead-letter state reconciliation
* structured CloudWatch logs
* request and correlation identifiers
* Terraform-managed infrastructure
* automated tests without real Bedrock calls
* manual deployed-environment validation

## Intentionally Deferred Scope

The following capabilities are intentionally deferred from v1:

* user authentication
* multi-tenant SaaS behavior
* production frontend
* ECS or Fargate processing
* EC2 and Kubernetes
* complex workflow orchestration
* advanced PDF parsing
* scanned-document OCR
* Amazon Textract integration
* full RAG workflows
* embeddings and vector databases
* agentic orchestration
* multiple production AI providers
* real-time streaming
* automated dead-letter redrive
* advanced analytics dashboards
* formal regulatory compliance claims

These decisions keep v1 focused on one complete, observable, recoverable serverless document-processing workflow.

## Portfolio Positioning

CloudDoc AI Pipeline is intended to demonstrate:

* cloud-native architecture
* serverless workload design
* event-driven processing
* asynchronous reliability
* at-least-once delivery handling
* idempotent business effects
* AI output validation
* infrastructure as code
* least-privilege IAM
* observability
* failure analysis
* cost-aware engineering

The project prioritizes a complete vertical workflow over broad but shallow feature coverage.
