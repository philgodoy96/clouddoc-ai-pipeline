# Authoritative Processing Start

## Purpose

CloudDoc starts document processing only after validating the uploaded-document event against the authoritative document job stored in DynamoDB.

The processing-start boundary is responsible for:

```text
loading the authoritative job
validating object ownership
acquiring bounded processing ownership
handling duplicate upload events idempotently
reconciling conditional-write races
preserving terminal job states
```

It does not yet:

```text
download the S3 object
decode document content
invoke an AI provider
persist a processing result
classify retryable execution failures
complete or fail the active attempt
```

## Processing Flow

```text
SQS uploaded-document event
    ↓
Processor Lambda
    ↓
ApplicationUploadedDocumentProcessor
    ↓
StartDocumentProcessing
    ↓
load authoritative DocumentJob
    ↓
validate canonical object ownership
    ↓
evaluate authoritative lifecycle state
    ↓
create bounded ProcessingAttempt when required
    ↓
DocumentJobRepository.claim_job
    ↓
conditional DynamoDB update
```

DynamoDB remains the authoritative source of workflow state.

An S3 object notification alone does not prove that a valid job exists or that processing may begin.

## Processing Ownership

A processing attempt represents a bounded worker claim:

```text
attempt_id
started_at
lease_expires_at
```

The lease duration is configured through:

```text
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
```

Default:

```text
300 seconds
```

Each acquired attempt receives an opaque identifier:

```text
attempt_<uuid4 hex>
```

The job aggregate records the active attempt and increments the number of acquired processing attempts when a claim succeeds.

## State Behavior

### Pending Upload

```text
pending_upload
    → acquire ProcessingAttempt
    → processing
```

This is the normal first-delivery path.

### Processing With an Active Lease

```text
processing
    + active unexpired lease
    → idempotent success
    → no additional write
    → no new attempt ID
```

The desired business effect already exists.

A duplicate SQS delivery must not steal a valid claim or increment the attempt count.

### Processing With an Expired Lease

```text
processing
    + expired lease
    → acquire replacement ProcessingAttempt
    → remain processing
```

The replacement claim receives a new attempt identity and a new bounded lease.

The attempt counter advances because a new processing ownership period has been acquired.

### Succeeded

```text
succeeded
    → idempotent success
    → no state regression
```

A late duplicate upload event does not return a completed job to processing.

### Failed or Dead

```text
failed
dead
    → application conflict
    → message remains retryable through the processor boundary
```

Upload-event duplication is not an explicit reprocessing command.

Automatic restart from a terminal failure state is intentionally prohibited.

A future reprocessing workflow must be modeled as a separate use case.

## Domain Strictness and Application Idempotency

The `DocumentJob` aggregate remains strict.

Its processing transition requires a concrete `ProcessingAttempt` and applies lifecycle invariants.

The domain model does not convert repeated calls into success automatically.

Idempotency belongs to `StartDocumentProcessing`, which examines authoritative state before deciding whether a new claim is necessary.

```text
domain
    → strict lifecycle transitions

application service
    → duplicate-delivery interpretation
```

This keeps business state rules separate from transport retry semantics.

## Object Ownership Validation

The delivery parser already validates the canonical object-key format:

```text
documents/{job_id}/source.txt
```

The application service validates ownership again against the authoritative job:

```text
event.object_key
    ==
build_document_object_key(authoritative_job.job_id)
```

This is defense in depth.

A structurally valid uploaded-document event for another job must not acquire processing ownership.

The bucket is validated earlier in the delivery layer using runtime configuration.

## Claim Ordering

The application service performs:

```text
read current time
load authoritative job
validate ownership and state
generate attempt ID only when a new claim is required
construct ProcessingAttempt
claim job conditionally
```

Duplicate events observing an active claim or a succeeded job do not generate unused attempt identifiers.

## Conditional Persistence

`DocumentJobRepository.claim_job(...)` is the ownership boundary.

The DynamoDB adapter uses conditional persistence so multiple workers cannot both acquire the same active claim.

Conceptually:

```text
worker A reads pending_upload
worker B reads pending_upload

worker A claims successfully
worker B conditional claim fails
```

The losing worker must not assume failure immediately.

It reloads authoritative state and evaluates the effect already persisted by the competing worker.

## Conflict Reconciliation

After a claim conflict, the application service reloads the job.

### Competing Worker Acquired an Active Claim

```text
conditional conflict
    ↓
reload job
    ↓
processing with active lease
    ↓
idempotent success
```

The desired processing-start effect already exists.

### Competing Worker Completed the Job

```text
conditional conflict
    ↓
reload job
    ↓
succeeded
    ↓
idempotent success
```

The job must not regress.

### Authoritative State Remains Incompatible

Examples:

```text
failed
dead
processing without a valid active attempt
processing with an expired lease after unresolved conflict
```

Behavior:

```text
ApplicationConflictError
```

The processor adapter translates the known application failure into the uploaded-document processing retry contract.

## Error Translation

`StartDocumentProcessing` translates repository failures into application errors.

```text
authoritative job missing
    → ApplicationNotFoundError

repository read or write unavailable
    → ApplicationDependencyError

incompatible state or unresolved ownership race
    → ApplicationConflictError
```

`ApplicationUploadedDocumentProcessor` translates known `ApplicationError` values into:

```text
UploadedDocumentProcessingError
```

The Processor Lambda then returns the SQS `messageId` through `batchItemFailures`.

Unexpected programming exceptions are not hidden by the adapter. They continue to the Lambda safety boundary, where the current message is also marked as failed.

## Runtime Composition

The runtime composition is explicit:

```text
RuntimeSettings
    ↓
DynamoDBDocumentJobRepository
SystemClock
UUIDProcessingAttemptIdGenerator
configured timedelta lease
    ↓
StartDocumentProcessing
    ↓
ApplicationUploadedDocumentProcessor
```

The composition root:

```text
does not read environment variables
does not cache the processor
accepts an injectable DynamoDB resource factory
```

The Lambda entrypoint loads settings and caches the composed processor for warm invocations.

```text
cold invocation
    → load settings
    → compose authoritative processor
    → cache processor

warm invocation
    → reuse processor
```

## Processor Lambda Contract

The testable Processor Lambda `handle()` contract remains unchanged.

```python
def handle(
    event,
    context,
    *,
    processor,
    expected_bucket_name,
): ...
```

The delivery layer continues to depend only on:

```text
UploadedDocumentProcessor
```

Replacing the no-op implementation with authoritative application processing does not require changing SQS batch behavior.

## Idempotency Boundary

Processing-start idempotency is based on authoritative job state and the current active lease.

It is not based solely on:

```text
SQS messageId
S3 ETag
S3 sequencer
S3 versionId
```

Transport identities may assist observability or future deduplication, but they do not represent the authoritative business effect.

The current guarantee is:

```text
duplicate delivery does not create a second active claim
```

The project does not yet claim:

```text
exactly-once document retrieval
exactly-once AI inference
exactly-once result persistence
```

Those effects require additional attempt-aware protections in later slices.

## Concurrency Test

A Moto-backed integration test coordinates two workers so both observe:

```text
status = pending_upload
```

before either claims the job.

Expected outcome:

```text
one conditional claim succeeds
one claim conflicts
the losing worker reloads authoritative state
both application calls finish successfully
one active attempt is persisted
attempt count remains one
```

This test validates the interaction between:

```text
StartDocumentProcessing
DynamoDBDocumentJobRepository
conditional writes
claim-conflict reconciliation
persisted authoritative state
```

## Reliability Considerations

Bounded leases prevent an active processing status from becoming permanent ownership if a worker stops before completing the workflow.

Lease expiration alone does not run recovery.

A later delivery or reconciliation workflow must attempt a replacement claim after expiration.

The configured lease duration must eventually be coordinated with:

```text
Lambda timeout
SQS visibility timeout
expected S3 download duration
AI-provider latency
retry strategy
```

The current default is an explicit starting policy, not a universal operational value.

## Security Considerations

The application service never trusts S3 event ownership by itself.

It validates the event against the authoritative job and canonical server-owned object key.

The service does not:

```text
accept caller-controlled attempt IDs
accept caller-controlled lease duration
accept caller-controlled object keys
load arbitrary buckets
```

Attempt IDs and leases are generated from trusted runtime components.

## Testing Strategy

Tests cover:

```text
pending job claim
active-lease duplicate
expired-lease replacement
succeeded duplicate
failed and dead state rejection
object ownership mismatch
missing authoritative job
repository read failure
repository claim failure
competing active claim reconciliation
unresolved conflict
positive lease configuration
attempt-ID generation
runtime composition
Lambda settings propagation
warm processor caching
concurrent DynamoDB claims
```

## Intentionally Deferred

```text
S3 GetObject
document size enforcement
UTF-8 decoding
AI-provider invocation
attempt-aware result persistence
retry release to pending_upload
terminal failure persistence
lease heartbeat or extension
manual reprocessing
structured logging
CloudWatch metrics
DLQ reconciliation
Terraform
real AWS concurrency validation
```