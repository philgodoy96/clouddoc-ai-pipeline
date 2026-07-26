# Attempt-Aware Processing Finalization

## Status

Implemented as an incremental reliability slice.

This document describes how CloudDoc finalizes successful processing, records deterministic terminal failures, releases retryable claims, and distinguishes active ownership from a durably applied terminal effect.

Amazon Bedrock integration, stale-job reconciliation, observability, and dead-letter reconciliation remain separate follow-up work.

## Purpose

CloudDoc processes uploaded documents through an at-least-once SQS delivery path.

A processing claim authorizes one worker to perform document retrieval and AI inference. That claim alone is not sufficient to acknowledge the queue message.

The worker must durably record the outcome through the same owned processing attempt before the delivery layer can treat the workflow as complete.

The finalization rule is:

```text
owned processing attempt
    before
document retrieval and AI inference
    before
attempt-aware finalization
    before
queue acknowledgement
```

## Reliability Problem

Before this slice, a worker could:

```text
acquire claim
    ↓
fail during S3 retrieval or AI invocation
    ↓
return the current message as failed
    ↓
receive a redelivery while the claim remained active
    ↓
treat the active claim as an already-applied effect
    ↓
acknowledge the redelivery
```

That behavior could leave the document job indefinitely in `processing`.

The system now distinguishes:

```text
another attempt is actively processing
```

from:

```text
a terminal business effect has already been persisted
```

## Processing-Start Outcomes

`StartDocumentProcessing` returns one of three outcomes.

### CLAIM_ACQUIRED

```text
attempt present
correlation_id present
```

The current worker owns the attempt and may continue.

### PROCESSING_ALREADY_ACTIVE

```text
attempt absent
correlation_id absent
```

Another unexpired attempt owns the job.

The workflow performs:

```text
no S3 retrieval
no AI-provider invocation
no completion write
no failure write
no claim release
```

It raises an application conflict so the current SQS delivery remains retryable.

### EFFECT_ALREADY_APPLIED

```text
attempt absent
correlation_id absent
```

The authoritative job is already terminal:

```text
succeeded
failed
dead
```

The workflow performs no additional effects and returns an explicit no-effect result that the delivery adapter acknowledges.

## End-to-End Workflow

```text
UploadedDocumentEvent
    ↓
StartDocumentProcessing
    ├── EFFECT_ALREADY_APPLIED
    │       → return no-effect result
    │       → acknowledge
    │
    ├── PROCESSING_ALREADY_ACTIVE
    │       → raise ApplicationConflictError
    │       → retry delivery
    │
    └── CLAIM_ACQUIRED
            → receive owned ProcessingAttempt
            → receive authoritative correlation_id
            → load and validate document
            → build AIProviderRequest
            → invoke AIProvider
            ↓
        ┌──────────────────────┬────────────────────────┬────────────────────────┐
        │ validated success    │ deterministic failure  │ retryable dependency   │
        ▼                      ▼                        ▼
    complete_job           fail_job              release_retryable_claim
        │                      │                        │
        ▼                      ▼                        ▼
    PROCESSED       TERMINAL_FAILURE_RECORDED   ApplicationDependencyError
        │                      │                        │
        ▼                      ▼                        ▼
    acknowledge            acknowledge                 retry
```

## Application Workflow Ownership

The orchestration is owned by:

```text
ProcessUploadedDocument
```

Its dependencies are:

```text
StartDocumentProcessing
DocumentTextLoader
AIProvider
DocumentJobRepository
Clock
```

The workflow coordinates:

- processing ownership
- active-claim behavior
- terminal duplicate behavior
- bounded document retrieval
- provider-request construction
- AI-provider invocation
- failure classification
- attempt-aware completion
- attempt-aware terminal failure persistence
- attempt-aware retryable claim release
- repository-error normalization
- explicit workflow-result creation

The workflow does not instantiate infrastructure adapters or AWS clients.

## Shared Repository and Clock

The runtime composition root creates one repository and one clock for each processing object graph.

The same instances are injected into:

```text
StartDocumentProcessing
ProcessUploadedDocument
```

This makes the graph explicit:

```text
repository ───────────────┐
    ↓                     │
StartDocumentProcessing   │
                          ├── ProcessUploadedDocument
clock ────────────────────┤
document_loader ──────────┤
ai_provider ──────────────┘
```

A fresh graph is created for each direct builder call.

The Lambda entrypoint caches the completed processor graph for warm invocations.

## Successful Finalization

A validated provider response does not by itself produce a successful workflow result.

The workflow first calls:

```text
complete_job(
    job_id,
    owned_attempt_id,
    validated_extraction_result,
    completed_at
)
```

Only after that repository transition succeeds does the workflow return:

```text
DocumentProcessingOutcome.PROCESSED
```

The result contains:

```text
owned ProcessingAttempt
validated AIExtractionResult
failure_reason = None
```

The repository-returned job is not exposed through the workflow result.

## Terminal Failure Finalization

A deterministic processing failure is acknowledged only after the workflow calls:

```text
fail_job(
    job_id,
    owned_attempt_id,
    normalized_reason,
    failed_at
)
```

Only after that transition succeeds does the workflow return:

```text
DocumentProcessingOutcome.TERMINAL_FAILURE_RECORDED
```

The result contains:

```text
owned ProcessingAttempt
normalized ProcessingFailureReason
extraction_result = None
```

The delivery adapter absorbs the result and returns `None`, allowing the SQS message to be acknowledged.

## Normalized Terminal Failure Reasons

The application persists stable provider-neutral reasons:

```text
document_not_found
document_validation_failed
invalid_document_reference
invalid_provider_request
ai_provider_invalid_response
```

The mapping is:

```text
missing event ETag
    → invalid_document_reference

DocumentNotFoundError
    → document_not_found

DocumentValidationError
    → document_validation_failed

invalid AIProviderRequest
    → invalid_provider_request

AIProviderInvalidResponseError
    → ai_provider_invalid_response
```

The application does not persist:

- raw exception messages
- SDK response bodies
- document content
- prompt content
- stack traces
- provider credentials

## Retryable Failure Handling

Retryable dependency failures include:

```text
DocumentDependencyError
AIProviderTimeoutError
AIProviderThrottledError
AIProviderUnavailableError
remaining normalized AIProviderError values
```

The workflow first calls:

```text
release_retryable_claim(
    job_id,
    owned_attempt_id,
    released_at
)
```

Only after release succeeds does it raise an `ApplicationDependencyError`.

The resulting path is:

```text
claim released to retryable state
    ↓
application dependency failure
    ↓
delivery adapter translation
    ↓
SQS partial batch failure
    ↓
redelivery can acquire a new attempt
```

The workflow does not release a claim for:

- deterministic terminal failures
- successful processing
- active claims owned by another worker
- already-applied terminal jobs
- unexpected programming defects

## Repository Failure Normalization

Attempt-aware finalization operations may fail independently from retrieval or inference.

### Missing job

```text
JobNotFoundError
    → ApplicationNotFoundError
```

Message:

```text
document job was not found during processing finalization
```

### Stale attempt or invalid state

```text
JobAttemptMismatchError
JobStateConflictError
    → ApplicationConflictError
```

Message:

```text
document processing finalization was rejected
```

This prevents an old worker from completing, failing, or releasing the claim owned by a newer attempt.

### Repository dependency failure

```text
RepositoryError
    → ApplicationDependencyError
```

Safe context includes:

```text
job_id
attempt_id
operation
```

Stable operation values are:

```text
complete
fail
release
```

A repository failure during claim release takes precedence over the original storage or provider dependency failure because the application could not safely restore retryable state.

## Stale-Worker Protection

Every finalization transition includes the owned `attempt_id`.

The authoritative repository conditionally verifies that the expected attempt still owns processing.

A stale worker cannot:

- persist successful output
- persist a terminal failure
- release another worker's claim
- overwrite a newer attempt's state

When a conditional transition is rejected, the workflow raises an application conflict rather than claiming success.

A later delivery asks the authoritative state again:

```text
newer attempt still active
    → PROCESSING_ALREADY_ACTIVE

terminal state recorded
    → EFFECT_ALREADY_APPLIED

lease expired
    → new attempt may be acquired
```

## Clock Semantics

The workflow asks the injected clock for a fresh timestamp for each attempted repository transition.

It does not reuse the claim timestamp for finalization.

The clock is not called for:

- `EFFECT_ALREADY_APPLIED`
- `PROCESSING_ALREADY_ACTIVE`
- unexpected exceptions before a finalization attempt

This keeps timestamps aligned with the transition being attempted.

## Workflow Results

`DocumentProcessingResult` represents only successfully resolved workflow decisions.

### PROCESSED

Requires:

```text
attempt present
extraction_result present
failure_reason absent
```

### TERMINAL_FAILURE_RECORDED

Requires:

```text
attempt present
extraction_result absent
failure_reason present
```

### EFFECT_ALREADY_APPLIED

Requires:

```text
attempt absent
extraction_result absent
failure_reason absent
```

`PROCESSING_ALREADY_ACTIVE` does not become a successful document-processing result. It raises an application conflict so delivery remains retryable.

## Infrastructure Adapter

`ApplicationUploadedDocumentProcessor` remains a narrow boundary:

```text
UploadedDocumentEvent
    → ProcessUploadedDocument.execute(...)
    → absorb successful workflow result
    → return None
```

It absorbs:

```text
PROCESSED
TERMINAL_FAILURE_RECORDED
EFFECT_ALREADY_APPLIED
```

It translates known `ApplicationError` values into:

```text
UploadedDocumentProcessingError
```

Unexpected exceptions continue to propagate.

The adapter does not inspect result outcomes or failure reasons.

## Lambda Delivery Semantics

The Processor Lambda remains responsible for:

- parsing the SQS batch
- isolating each message
- reporting partial batch failures
- composing the processor on cold start
- reusing the processor on warm invocations

The handler does not know about:

- repository finalization methods
- processing attempts
- failure-reason enums
- AI extraction results
- provider implementations
- document-processing outcomes

Delivery behavior is:

```text
PROCESSED
    → processor returns None
    → acknowledge

TERMINAL_FAILURE_RECORDED
    → processor returns None
    → acknowledge

EFFECT_ALREADY_APPLIED
    → processor returns None
    → acknowledge

PROCESSING_ALREADY_ACTIVE
    → application conflict
    → processor error
    → partial batch failure
    → retry

retryable dependency failure after successful release
    → processor error
    → partial batch failure
    → retry
```

## Exactly-Once Boundaries

The project does not claim:

- exactly-once Lambda execution
- exactly-once SQS delivery
- exactly-once S3 retrieval
- exactly-once AI inference

The system enforces idempotent authoritative state transitions through owned attempt IDs and conditional repository writes.

A worker may still invoke the AI provider and then fail before persisting completion. A later attempt may invoke the provider again.

The current guarantee is:

```text
only the current owned attempt may persist final state
```

not:

```text
the provider is invoked exactly once
```

## Security Considerations

The workflow uses safe normalized failure reasons for durable state.

Error context excludes:

- full document text
- extracted business data
- provider payloads
- credentials
- raw SDK responses

Operational context may include:

```text
job_id
attempt_id
object_key
provider_name
operation
```

Logging policy must continue avoiding full documents and model payloads.

## Testing Strategy

Coverage includes:

- all processing-start outcome invariants
- active direct-state behavior
- active claim-race behavior
- terminal-state duplicate behavior
- successful attempt-aware completion
- terminal failure classification
- terminal failure persistence
- retryable claim release
- repository failure normalization
- stale-attempt rejection
- clock-call behavior
- zero effects for active ownership
- zero effects for already-applied terminal jobs
- unexpected-exception propagation
- shared repository composition
- shared clock composition
- fresh object graphs
- offline composition
- terminal-result acknowledgement at the adapter boundary
- existing Lambda partial batch behavior

Tests do not require real AWS services or real AI-provider calls.

## Intentionally Deferred

The following remain intentionally deferred:

- Amazon Bedrock adapter
- model and prompt configuration
- lease heartbeat or extension
- maximum processing-attempt policy
- SQS receive-count-aware failure policy
- stale-processing reconciliation
- DLQ reconciler implementation
- automated DLQ redrive
- structured workflow logs
- CloudWatch metrics and alarms
- Terraform and IAM updates
- deployed end-to-end validation

## Next Reliability Work

The next reliability stage should introduce operational recovery for processing attempts that remain active after:

- unexpected worker termination
- Lambda timeout
- process crash
- repository outage during finalization
- network interruption after provider invocation

That work should define:

```text
stale-processing detection
lease-expiration reconciliation
maximum-attempt policy
DLQ ownership reconciliation
observability for active and expired attempts
```

Amazon Bedrock integration should follow once these operational recovery boundaries are approved.