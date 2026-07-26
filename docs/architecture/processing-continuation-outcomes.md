# Processing Continuation Outcomes

## Purpose

CloudDoc distinguishes between successful processing-start requests that authorize the current worker to continue and successful requests whose business effect was already applied elsewhere.

This distinction is required before document retrieval, AI invocation, or result persistence can safely enter the processing workflow.

The continuation contract is responsible for communicating:

```text
this worker acquired processing ownership
the desired processing-start effect already exists
```

It is not responsible for:

```text
loading the source document
invoking the AI provider
completing the processing attempt
persisting failure
releasing retryable claims
```

## Problem

`StartDocumentProcessing` previously returned `None` for every successful path:

```text
new claim acquired
active claim already exists
job already succeeded
```

Those cases are not operationally equivalent.

Only the worker that acquired the claim may safely continue into document retrieval and future AI execution.

A duplicate delivery that observes another worker's active claim must stop successfully without performing downstream effects.

## Application Contract

The continuation contract contains:

```text
ProcessingStartOutcome
ProcessingStartResult
```

### ProcessingStartOutcome

```text
CLAIM_ACQUIRED
EFFECT_ALREADY_APPLIED
```

The enum uses stable string values:

```text
claim_acquired
effect_already_applied
```

These values are suitable for future structured logs, metrics, and deterministic tests.

### ProcessingStartResult

```text
outcome
attempt
```

The result is immutable.

Its invariants are:

```text
CLAIM_ACQUIRED
    → attempt must be present

EFFECT_ALREADY_APPLIED
    → attempt must be absent
```

An invalid combination fails immediately during construction.

## Why Attempt Ownership Is Returned

When the current worker acquires the claim, the result returns the exact `ProcessingAttempt` created for that worker.

```text
attempt_id
started_at
lease_expires_at
```

Future side effects must be associated with this attempt identity.

The result does not return the complete `DocumentJob`.

This keeps the contract focused on continuation authorization rather than exposing a general aggregate snapshot.

## State Interpretation

### Pending Upload

```text
pending_upload
    → acquire new ProcessingAttempt
    → CLAIM_ACQUIRED
    → return owned attempt
```

### Processing With Expired Lease

```text
processing
    + expired active lease
    → acquire replacement ProcessingAttempt
    → CLAIM_ACQUIRED
    → return replacement attempt
```

### Processing With Active Lease

```text
processing
    + active unexpired lease
    → EFFECT_ALREADY_APPLIED
    → return no attempt
```

The active attempt may belong to another worker.

Returning that attempt would incorrectly authorize the current worker to continue.

### Succeeded

```text
succeeded
    → EFFECT_ALREADY_APPLIED
    → return no attempt
```

The workflow is complete and must not regress.

### Failed or Dead

```text
failed
dead
    → ApplicationConflictError
```

A duplicate upload event is not a reprocessing command.

## Concurrent Claim Race

Two workers may observe the same pending job before either claim is persisted.

```text
worker A reads pending_upload
worker B reads pending_upload

worker A claims successfully
worker B receives conditional conflict
```

The losing worker reloads authoritative state.

Expected results:

```text
worker A
    → CLAIM_ACQUIRED
    → returns its owned attempt

worker B
    → EFFECT_ALREADY_APPLIED
    → returns no attempt
```

The persisted job contains:

```text
status = processing
attempts = 1
one active attempt
```

The result contract makes the concurrency outcome visible without exposing DynamoDB-specific errors or conditional-expression details.

## Claim Conflict Reconciliation

`StartDocumentProcessing` reconciles conditional conflicts against authoritative state.

### Active Claim Observed

```text
claim conflict
    ↓
reload job
    ↓
processing with active lease
    ↓
EFFECT_ALREADY_APPLIED
```

### Completed Job Observed

```text
claim conflict
    ↓
reload job
    ↓
succeeded
    ↓
EFFECT_ALREADY_APPLIED
```

### Incompatible State Observed

```text
failed
dead
processing without a valid active attempt
processing with an unresolved expired lease
```

Behavior:

```text
ApplicationConflictError
```

## Layer Boundaries

```text
DocumentJob
    → owns lifecycle invariants

DocumentJobRepository
    → owns conditional persistence

StartDocumentProcessing
    → interprets authoritative state
    → returns continuation authorization

ApplicationUploadedDocumentProcessor
    → adapts application behavior to delivery contract

Processor Lambda
    → remains unaware of claim internals
```

## Delivery Contract Preservation

`ApplicationUploadedDocumentProcessor` still implements:

```python
def process(
    self,
    *,
    event: UploadedDocumentEvent,
) -> None: ...
```

The infrastructure adapter invokes `StartDocumentProcessing` and absorbs the application result.

```text
ProcessingStartResult
    → internal application decision

None
    → existing delivery-layer success contract
```

This preserves the current Processor Lambda interface while enabling the next workflow slice to evolve the application-backed processor internally.

## Error Behavior

The continuation result applies only to successful processing-start paths.

Existing failures remain unchanged:

```text
missing job
    → ApplicationNotFoundError

repository unavailable
    → ApplicationDependencyError

failed or dead state
    → ApplicationConflictError

unresolved conditional race
    → ApplicationConflictError
```

`ApplicationUploadedDocumentProcessor` continues translating known `ApplicationError` values into `UploadedDocumentProcessingError`.

Unexpected programming exceptions continue to the outer Lambda boundary.

## Current Workflow Boundary

The result contract is now available, but document retrieval is not yet connected to the application-backed processor.

The next workflow composition can apply:

```text
result.outcome == CLAIM_ACQUIRED
    → load the source document
    → continue processing under result.attempt

result.outcome == EFFECT_ALREADY_APPLIED
    → return successfully
    → perform no downstream effect
```

This is the authorization boundary required to prevent duplicate deliveries from running S3 reads or AI inference without ownership.

## Testing Strategy

Unit tests cover:

```text
valid claim-acquired result
valid already-applied result
missing attempt rejection
unexpected attempt rejection
result immutability
stable outcome values
pending job result
expired-lease replacement result
active-lease duplicate result
succeeded duplicate result
claim-conflict reconciliation
```

Infrastructure tests prove:

```text
both valid application outcomes remain internal
the delivery processor still returns None
known application errors remain translated
unexpected exceptions remain visible
```

The Moto-backed concurrency test proves:

```text
exactly one worker receives CLAIM_ACQUIRED
exactly one worker receives EFFECT_ALREADY_APPLIED
only the winning worker receives the persisted attempt
the losing worker receives no continuation attempt
one active claim is persisted
```

## Security and Reliability Considerations

An attempt returned by `CLAIM_ACQUIRED` is a capability-like authorization token for future attempt-aware effects.

Downstream operations must not accept an attempt copied from authoritative state when the current worker did not acquire it.

Future completion and failure writes should require:

```text
job_id
attempt_id
```

and reject stale or mismatched attempts.

The result contract does not by itself provide exactly-once processing. It establishes which worker is authorized to perform the next effects.

## Intentionally Deferred

```text
document retrieval inside the processor workflow
AI-provider invocation
prompt construction
empty-document processing policy
attempt-aware result persistence
retryable claim release
terminal failure persistence
lease heartbeat or extension
structured logging
outcome metrics
DLQ reconciliation
explicit reprocessing
```