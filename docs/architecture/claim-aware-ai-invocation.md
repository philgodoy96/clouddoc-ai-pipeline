# Claim-Aware AI Invocation

## Status

Implemented as an incremental processing slice.

This document describes the workflow boundary that connects authoritative processing ownership, bounded S3 document retrieval, deterministic AI-provider invocation, and validated structured output.

It does not describe durable job completion or failure persistence. Those state transitions remain separate follow-up work.

## Purpose

CloudDoc processes uploaded documents through an at-least-once SQS delivery path.

Duplicate deliveries are expected. A worker must not read the document or invoke an AI provider merely because it received a valid queue message. It must first acquire authoritative processing ownership through the document job stored in DynamoDB.

The workflow therefore enforces:

```text
processing claim
    before
document retrieval
    before
AI invocation
```

## Processing Flow

```text
UploadedDocumentEvent
    ↓
ProcessUploadedDocument
    ↓
StartDocumentProcessing
    ├── EFFECT_ALREADY_APPLIED
    │       → skip S3 retrieval
    │       → skip AI invocation
    │       → return explicit no-effect result
    │
    └── CLAIM_ACQUIRED
            → receive owned ProcessingAttempt
            → receive authoritative correlation_id
            → build DocumentObjectReference
            → load and validate UTF-8 text
            → build AIProviderRequest
            → invoke AIProvider
            → receive validated AIExtractionResult
            → return explicit processed result
```

The workflow currently stops after returning the validated extraction result. It does not yet persist job completion.

## Application Boundary

The orchestration is owned by:

```text
ProcessUploadedDocument
```

This application service coordinates:

- processing-claim acquisition
- continuation-outcome interpretation
- document-reference construction
- bounded document retrieval
- AI-provider request construction
- provider invocation
- normalized application failure translation
- explicit workflow-result creation

The service depends on abstractions and application-owned contracts rather than concrete AWS clients.

Its direct collaborators are:

```text
StartDocumentProcessing
DocumentTextLoader
AIProvider
```

## Explicit Workflow Results

The workflow returns:

```text
DocumentProcessingResult
```

with one of two outcomes:

```text
PROCESSED
EFFECT_ALREADY_APPLIED
```

### PROCESSED

A processed result requires:

```text
owned ProcessingAttempt
validated AIExtractionResult
```

This means the current worker acquired processing ownership and completed document retrieval and provider invocation.

It does not mean the job has been durably completed in DynamoDB.

### EFFECT_ALREADY_APPLIED

An already-applied result contains:

```text
attempt = None
extraction_result = None
```

This prevents a duplicate delivery from receiving continuation authority or exposing another worker's result.

## Authoritative Correlation Context

`AIProviderRequest` requires:

```text
document_text
correlation_id
processing_attempt_id
```

The `correlation_id` is obtained from the authoritative `DocumentJob.correlation_context` already loaded by `StartDocumentProcessing`.

It is not derived from:

- SQS message IDs
- S3 event metadata
- Lambda invocation identifiers
- object keys

A queue-message ID identifies one delivery attempt. It is not a stable workflow identifier.

For a successful claim, `ProcessingStartResult` carries:

```text
attempt
correlation_id
```

For an already-applied outcome, both values remain absent.

## Document Retrieval

The workflow constructs `DocumentObjectReference` from the normalized uploaded-document event:

```text
object_key
expected_size_bytes
expected_etag
version_id
```

The configured bucket remains a runtime-owned concern inside the S3 document loader.

The document loader is responsible for:

- private S3 access
- content-type validation
- object identity validation
- bounded size enforcement
- UTF-8 decoding
- normalized document-loading errors

Only the claim owner invokes the loader.

## AI Provider Request

After successful document retrieval, the workflow creates:

```text
AIProviderRequest
```

using:

```text
document_text = LoadedTextDocument.content
correlation_id = authoritative job correlation ID
processing_attempt_id = owned attempt ID
```

The request does not expose:

- bucket names
- AWS credentials
- raw S3 responses
- queue delivery metadata
- Lambda context objects

The processing-attempt ID will later be used to protect durable completion and failure writes from stale workers.

## Provider Abstraction

The workflow depends on:

```text
AIProvider
```

and not on Amazon Bedrock directly.

The current runtime composition injects:

```text
MockAIProvider
```

This is an intentional sequencing decision.

The deterministic provider allows the project to verify orchestration, request construction, duplicate suppression, result validation, and error propagation without introducing:

- model identifiers
- Bedrock IAM permissions
- network variability
- throttling configuration
- provider-specific payload mapping
- inference cost
- real document disclosure

A Bedrock adapter can replace the mock through the composition boundary without changing the application workflow.

## Validated Output

The provider returns:

```text
AIExtractionResult
```

The result schema is application-owned and validated before it reaches `DocumentProcessingResult`.

A successful provider call alone is not sufficient to mark a document job as succeeded.

The result must later be persisted through an attempt-aware conditional state transition.

## Infrastructure Adapter

The infrastructure adapter is:

```text
ApplicationUploadedDocumentProcessor
```

Its responsibility is intentionally narrow:

```text
UploadedDocumentEvent
    → ProcessUploadedDocument.execute(...)
    → absorb DocumentProcessingResult
    → return None
```

It does not:

- acquire claims directly
- load S3 objects directly
- build provider requests
- invoke the provider
- inspect workflow outcomes
- persist job state

Known `ApplicationError` values are translated to the delivery-level `UploadedDocumentProcessingError`.

Unexpected exceptions continue to propagate to the Lambda safety boundary.

## Lambda Boundary

The Processor Lambda continues to depend on:

```text
UploadedDocumentProcessor.process(...) -> None
```

The handler is intentionally unaware of:

- `DocumentProcessingResult`
- AI-provider implementations
- extraction schemas
- processing attempts
- DynamoDB repository details
- S3 loader details

The handler remains responsible for:

- SQS batch parsing
- per-message isolation
- partial batch failure reporting
- cold-start composition
- warm processor reuse

Because the delivery contract did not change, no AI-specific handler behavior was added.

## Runtime Composition

The runtime composition root builds one object graph per builder call:

```text
DynamoDBDocumentJobRepository
    ↓
StartDocumentProcessing

S3DocumentTextLoader
    ↓
ProcessUploadedDocument
    ← MockAIProvider

ProcessUploadedDocument
    ↓
ApplicationUploadedDocumentProcessor
```

The Lambda handler caches the composed processor at module scope for warm invocations.

The composition builder itself does not introduce global caching.

A custom AI-provider factory can be injected for tests and future provider implementations.

## Failure Translation

### Processing-start failures

Known processing-start application failures remain application errors and are translated at the processor adapter boundary.

### Document-retrieval failures

Current translations are:

```text
DocumentNotFoundError
    → ApplicationNotFoundError

DocumentValidationError
    → ApplicationConflictError

DocumentDependencyError
    → ApplicationDependencyError
```

### Provider failures

Normalized `AIProviderError` values currently become:

```text
ApplicationDependencyError
```

with operational context that excludes document content.

Unexpected loader or provider exceptions are not broadly caught by the workflow.

## Transitional Retry Semantics

This slice does not yet implement attempt-aware claim release or terminal failure persistence.

The current behavior is therefore transitional:

```text
worker acquires claim
    ↓
document retrieval or AI invocation fails
    ↓
current SQS message is reported as failed
    ↓
redelivery may occur while the claim lease is still active
    ↓
StartDocumentProcessing may return EFFECT_ALREADY_APPLIED
    ↓
redelivery may be acknowledged without repeating retrieval or inference
```

Consequently, this slice does not guarantee that a transient retrieval or provider failure reaches the DLQ.

A job may remain in `processing` until:

- the lease expires and another processing trigger occurs
- a future reconciler detects the stale job
- attempt-aware failure handling is implemented

This behavior must be addressed before the processing path is considered operationally complete.

## Security Considerations

The workflow avoids including document content in normalized error context.

Operational context may include:

```text
job_id
attempt_id
object_key
provider_name
```

Full document text and full provider payloads must not be logged.

The mock provider is used for local and automated testing so tests do not disclose documents to an external inference service.

## Testing Strategy

Coverage includes:

- explicit workflow-result invariants
- authoritative correlation-context propagation
- claim-owner document retrieval
- claim-owner provider invocation
- duplicate suppression before S3
- duplicate suppression before AI
- document-reference mapping
- provider-request mapping
- known document-error translation
- known provider-error translation
- unexpected-error propagation
- narrow infrastructure-adapter behavior
- runtime provider-factory injection
- fresh composition graphs
- offline composition
- Lambda partial-batch behavior
- Lambda warm processor caching

Automated tests do not require AWS or real AI-provider calls.

## Intentionally Deferred

The following capabilities are intentionally deferred from this slice:

- Amazon Bedrock adapter
- model selection and model-ID configuration
- prompt templates and prompt versioning
- token-usage accounting
- provider-specific retry policy
- attempt-aware successful completion
- retryable claim release
- terminal failure persistence
- lease heartbeat or extension
- stale-processing reconciliation
- structured processing logs
- CloudWatch metrics and alarms
- IAM and Terraform changes
- end-to-end deployed validation

## Required Follow-Up

Before adding more processing effects, the next reliability slice should introduce attempt-aware failure handling.

The workflow must distinguish:

```text
retryable dependency failure
    → conditionally release the owned claim
    → return the message as failed
    → allow redelivery to acquire a new attempt

deterministic terminal failure
    → conditionally persist job failure
    → acknowledge the queue message

stale worker
    → conditional write rejected
    → must not overwrite the current owner
```

After failure handling is safe, the pipeline can add attempt-aware result persistence and then replace the deterministic provider with Amazon Bedrock.