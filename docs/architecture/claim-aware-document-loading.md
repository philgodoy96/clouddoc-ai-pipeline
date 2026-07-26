# Claim-Aware Document Loading

## Purpose

CloudDoc loads an uploaded source document only after the current worker has acquired processing ownership.

This workflow boundary connects:

```text
processing continuation authorization
bounded S3 document retrieval
delivery-layer success and retry behavior
```

The processor now distinguishes between:

```text
CLAIM_ACQUIRED
    → this worker may load the document

EFFECT_ALREADY_APPLIED
    → this delivery must stop successfully
    → no S3 request is performed
```

This slice intentionally stops after validated document retrieval.

It does not yet:

```text
invoke the AI provider
construct prompts
validate AI output
complete the processing attempt
persist terminal failure
release retryable claims
```

## Runtime Flow

```text
SQS uploaded-document event
    ↓
Processor Lambda
    ↓
ApplicationUploadedDocumentProcessor
    ↓
StartDocumentProcessing
    ↓
ProcessingStartResult
    ├── EFFECT_ALREADY_APPLIED
    │       → return successfully
    │       → no document load
    │
    └── CLAIM_ACQUIRED
            → build DocumentObjectReference
            → DocumentTextLoader.load(...)
            → validated LoadedTextDocument
            → return successfully
```

The ordering is intentional:

```text
authoritative ownership
    before
document retrieval
```

## Application-Backed Processor

`ApplicationUploadedDocumentProcessor` now orchestrates two application-facing dependencies:

```text
StartDocumentProcessing
DocumentTextLoader
```

Its delivery contract remains:

```python
def process(
    self,
    *,
    event: UploadedDocumentEvent,
) -> None: ...
```

The Processor Lambda remains unaware of:

```text
ProcessingStartResult
ProcessingAttempt
DocumentObjectReference
LoadedTextDocument
DynamoDB claim behavior
S3 response behavior
```

## Continuation Authorization

### Claim Acquired

When `StartDocumentProcessing` returns:

```text
ProcessingStartOutcome.CLAIM_ACQUIRED
```

the result includes the exact attempt acquired by the current worker.

The processor is authorized to continue and performs one document-load request.

```text
claim acquired
    → one DocumentTextLoader.load(...)
```

### Effect Already Applied

When the service returns:

```text
ProcessingStartOutcome.EFFECT_ALREADY_APPLIED
```

the processor returns successfully without loading the object.

```text
active claim already exists
or
job already succeeded
    ↓
no S3 request
    ↓
delivery acknowledged
```

This prevents duplicate SQS deliveries from performing unnecessary storage reads or future AI calls.

## Document Reference Construction

The processor derives `DocumentObjectReference` from the normalized uploaded-document event.

Mapping:

```text
event.object_key
    → reference.object_key

event.object_size
    → reference.expected_size_bytes

event.etag
    → reference.expected_etag

event.version_id
    → reference.version_id
```

The reference does not contain:

```text
bucket name
message ID
event name
job ID
sequencer
```

The bucket remains owned by trusted runtime configuration inside `S3DocumentTextLoader`.

The other event fields remain delivery metadata and are not part of storage-object identity at this boundary.

## Loaded Document Lifecycle

For a claim-owning worker:

```text
DocumentTextLoader.load(...)
    → LoadedTextDocument
```

The loaded document has already passed:

```text
trusted bucket selection
configured size limits
S3 metadata validation
ETag validation
VersionId validation when present
canonical text/plain validation
strict UTF-8 decoding
bounded body read
```

The document is intentionally not forwarded to an AI provider in this slice.

```text
validated document
    → workflow boundary proven
    → result not yet consumed
```

This sequencing isolates ownership and retrieval before adding provider behavior and state persistence.

## Error Translation

The processor preserves distinct messages for the two workflow stages.

### Processing-Start Failure

Known application errors from `StartDocumentProcessing` become:

```text
UploadedDocumentProcessingError
message:
failed to start uploaded-document processing
```

Examples:

```text
authoritative job missing
terminal-state conflict
repository dependency failure
unresolved claim race
```

### Document-Load Failure

Known `DocumentLoadError` values become:

```text
UploadedDocumentProcessingError
message:
failed to load uploaded document
```

This includes:

```text
DocumentNotFoundError
DocumentValidationError
DocumentDependencyError
```

The original error is preserved as the exception cause.

### Unexpected Failures

The processor does not catch broad exceptions.

Unexpected failures such as programming defects continue to the outer Lambda safety boundary.

```text
unexpected RuntimeError
    → Processor Lambda message failure
```

## Temporary Retrieval Failure Policy

All normalized document-load failures currently become SQS-retryable processor failures.

This means:

```text
missing object
invalid metadata
oversized document
invalid UTF-8
S3 dependency failure
```

all currently lead to:

```text
UploadedDocumentProcessingError
    → batchItemFailures
    → SQS retry
    → eventual DLQ
```

This is not the final failure classification.

The project intentionally defers state mutation until it can perform attempt-aware updates.

A worker must not:

```text
mark a job failed
release a claim
complete a job
```

without proving that its `attempt_id` is still authoritative.

## Why Validation Errors Are Temporarily Retryable

Some retrieval failures are deterministic and should eventually become terminal:

```text
unsupported content type
oversized document
invalid UTF-8
identity mismatch
```

However, persisting a terminal failure safely requires:

```text
job_id
owned attempt_id
conditional failure write
```

Similarly, dependency failures should eventually release or preserve the claim according to a retry policy.

Until those use cases exist, the safest behavior is to preserve the failure operationally through SQS retries and the DLQ rather than perform an unprotected state mutation.

## Runtime Composition

The processor builder now composes both storage systems.

```text
RuntimeSettings
    ├── jobs_table_name
    ├── processing_lease_duration_seconds
    ├── documents_bucket_name
    └── max_document_size_bytes
```

Composition:

```text
injected DynamoDB resource factory
    ↓
DynamoDBDocumentJobRepository
    ↓
StartDocumentProcessing

injected S3 client factory
    ↓
build_document_text_loader
    ↓
S3DocumentTextLoader

both
    ↓
ApplicationUploadedDocumentProcessor
```

The composition root reuses:

```text
build_document_job_repository
build_document_text_loader
```

It does not duplicate adapter construction.

## Composition Characteristics

Each call to `build_uploaded_document_processor(...)` creates:

```text
one DynamoDB resource
one repository
one processing-start service
one S3 client
one document loader
one application-backed processor
```

The builder:

```text
does not read environment variables
does not cache objects
does not call DynamoDB
does not call S3 GetObject
```

The Lambda entrypoint remains responsible for warm-invocation caching.

## Lambda Behavior

Cold invocation:

```text
load RuntimeSettings
    ↓
compose claim-aware processor
    ↓
cache processor
    ↓
process SQS batch
```

Warm invocation:

```text
load current settings according to existing entrypoint behavior
    ↓
reuse cached processor
    ↓
process SQS batch
```

The handler remains focused on:

```text
event parsing
message isolation
partial batch failures
warm processor caching
```

It does not inspect whether the internal workflow loaded a document or skipped an already-applied effect.

## Duplicate Delivery Cost Behavior

Before this slice, a future retrieval integration could have allowed both workers to read S3.

After this slice:

```text
winning worker
    → one document retrieval

duplicate worker with active claim
    → zero document retrievals

late duplicate after success
    → zero document retrievals
```

This reduces:

```text
S3 request cost
Lambda execution time
memory usage
future model-input cost
duplicate external effects
```

## Security Considerations

Claim-aware loading protects the storage boundary from unauthorized continuation.

A worker cannot continue merely because processing-start returned successfully.

It must receive:

```text
CLAIM_ACQUIRED
```

The S3 bucket still comes from trusted runtime configuration.

The event supplies only the expected object identity.

Document content remains internal and must not be logged.

## Reliability Considerations

Claim-aware loading prevents duplicate delivery from entering document retrieval, but it does not guarantee exactly-once downstream processing.

A worker can:

```text
acquire a claim
load the document
lose its lease
continue running
```

Future result and failure writes must validate the active `attempt_id`.

The current processor also does not release a claim when S3 fails.

That behavior will be addressed through explicit attempt-aware failure use cases.

## Testing Strategy

Infrastructure unit tests prove:

```text
claim-acquired outcome loads exactly once
event metadata maps to DocumentObjectReference
VersionId is propagated
already-applied outcome performs no load
loaded content does not escape the adapter
start errors remain distinct
known document-load errors are translated
unexpected start errors propagate
unexpected loader errors propagate
delivery None contract remains stable
```

Runtime composition tests prove:

```text
DynamoDB and S3 factories are injected
existing repository composition is preserved
document-loader builder is reused
configured bucket reaches the loader
configured size limit reaches the loader
configured lease reaches the service
fresh composition returns distinct object graphs
no AWS access is required
```

Handler tests prove:

```text
cold-start composition occurs once
warm invocation reuses the processor
valid processor success is acknowledged
composition failure remains invocation-level
partial batch behavior is unchanged
```

## Intentionally Deferred

```text
AI-provider invocation
prompt construction
document semantic validation
empty-document rejection
attempt-aware completion
attempt-aware terminal failure
retryable claim release
lease heartbeat or extension
provider retries
structured logs
CloudWatch metrics
DLQ reconciliation
explicit reprocessing
Terraform and IAM updates
```