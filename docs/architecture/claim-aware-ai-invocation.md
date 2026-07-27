# Claim-Aware AI Invocation

## Status

Implemented as an incremental processing slice.

This document describes the workflow boundary that connects authoritative processing ownership, bounded S3 document retrieval, deterministic AI-provider invocation, and validated structured output.

## Current Evolution

The original slice introduced the provider boundary with `MockAIProvider` and claim-aware orchestration before durable completion and failure persistence existed.

Later slices implemented attempt-aware finalization and Amazon Bedrock. The current implementation is documented in:

- [Attempt-Aware Processing Finalization](attempt-aware-processing-finalization.md)
- [Bedrock AI Provider Integration](bedrock-ai-provider-integration.md)

This document remains the historical architecture of the claim-aware invocation slice, updated only where earlier statements would otherwise present superseded behavior as current.

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
            → persist attempt-aware completion or terminal failure
            → return explicit workflow result
```

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
- attempt-aware completion and failure persistence
- explicit workflow-result creation

The service depends on abstractions and application-owned contracts rather than concrete AWS clients.

Its direct collaborators are:

```text
StartDocumentProcessing
DocumentTextLoader
AIProvider
DocumentJobRepository
Clock
```

## Explicit Workflow Results

The workflow returns:

```text
DocumentProcessingResult
```

with one of:

```text
PROCESSED
TERMINAL_FAILURE_RECORDED
EFFECT_ALREADY_APPLIED
```

### PROCESSED

A processed result requires:

```text
owned ProcessingAttempt
validated AIExtractionResult
```

This means the current worker acquired processing ownership, completed document retrieval and provider invocation, and persisted successful completion.

### TERMINAL_FAILURE_RECORDED

A terminal-failure result requires:

```text
owned ProcessingAttempt
normalized failure reason
```

This means the worker recorded a durable terminal failure and should acknowledge the queue message.

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

The processing-attempt ID protects durable completion and failure writes from stale workers.

## Provider Abstraction

The workflow depends on:

```text
AIProvider
```

and not on Amazon Bedrock directly.

`MockAIProvider` remains the local and automated-test default. The deployed Processor selects Bedrock through runtime configuration. The application workflow still depends only on `AIProvider`.

The mock was introduced first so the project could verify orchestration, request construction, duplicate suppression, result validation, and error propagation without introducing model identifiers, Bedrock IAM permissions, network variability, throttling configuration, provider-specific payload mapping, inference cost, or real document disclosure.

A Bedrock adapter replaces the mock through the composition boundary without changing the application workflow.

## Validated Output

The provider returns:

```text
AIExtractionResult
```

The result schema is application-owned and validated before it reaches `DocumentProcessingResult`.

A successful provider call alone is not sufficient to mark a document job as succeeded.

The result must be persisted through an attempt-aware conditional state transition.

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
       or
      BedrockAIProvider

ProcessUploadedDocument
    ↓
ApplicationUploadedDocumentProcessor
```

An explicit AI provider factory takes precedence when supplied. Otherwise composition selects the configured provider from runtime settings.

The Lambda handler caches the composed processor at module scope for warm invocations.

The composition builder itself does not introduce global caching.

## Failure Translation

### Processing-start failures

Known processing-start application failures remain application errors and are translated at the processor adapter boundary.

### Document-retrieval failures

Current translations are:

```text
DocumentNotFoundError
    → terminal failure persistence

DocumentValidationError
    → terminal failure persistence

DocumentDependencyError
    → claim release + ApplicationDependencyError
```

### Provider failures

Current provider failure behavior:

```text
AIProviderInvalidResponseError
    → terminal failure persistence

retryable provider errors
    → claim release + ApplicationDependencyError + SQS retry

configuration errors
    → operational dependency path, not terminal document failure
```

`AIProviderConfigurationError`, timeout, throttling, and temporary unavailability follow the retryable operational dependency path: the owned claim is released and the failure surfaces as `ApplicationDependencyError` for SQS retry.

Unexpected loader or provider exceptions are not broadly caught by the workflow.

## Historical Transitional Retry Semantics

The original claim-aware slice deferred attempt-aware claim release and terminal failure persistence. That transitional behavior has been replaced.

Current retry and finalization semantics are documented in [Attempt-Aware Processing Finalization](attempt-aware-processing-finalization.md).

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

The mock provider remains the local and automated-test default so tests do not disclose documents to an external inference service. The deployed Processor uses Bedrock while automated tests inject fake clients and never call AWS.

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

The following capabilities remain intentionally deferred:

- prompt templates and prompt versioning
- token and cost accounting
- lease heartbeat or extension
- stale-processing reconciliation
- structured provider telemetry
- CloudWatch metrics and alarms
- quality evaluation
- real deployed validation

## Required Follow-Up

Implemented follow-up work is documented in:

- [Attempt-Aware Processing Finalization](attempt-aware-processing-finalization.md)
- [Bedrock AI Provider Integration](bedrock-ai-provider-integration.md)
- [ADR-023: Use Amazon Nova Micro through Bedrock Converse](../adr/ADR-023-use-amazon-nova-micro-through-bedrock-converse.md)

The next operational work is observability: structured provider telemetry, CloudWatch alarms, and deployed validation evidence.
