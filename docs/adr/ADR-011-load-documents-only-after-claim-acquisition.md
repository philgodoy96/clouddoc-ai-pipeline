# ADR-011: Load Documents Only After Processing Claim Acquisition

## Status

Accepted

## Context

CloudDoc receives uploaded-document events through standard SQS.

The delivery model is at least once, and multiple workers may observe the same logical upload.

The system already provides:

```text
authoritative processing claims
bounded processing leases
explicit continuation outcomes
bounded S3 document retrieval
```

Before this decision, the application-backed processor invoked processing-start but discarded its result.

Connecting document retrieval without interpreting that result would allow a duplicate worker to read the document even when another worker owned the active processing attempt.

That would increase cost and create an unsafe foundation for future AI inference.

## Decision

CloudDoc will load a document only when `StartDocumentProcessing` returns:

```text
ProcessingStartOutcome.CLAIM_ACQUIRED
```

When the result is:

```text
ProcessingStartOutcome.EFFECT_ALREADY_APPLIED
```

the processor will return successfully without calling `DocumentTextLoader`.

## Workflow

```text
UploadedDocumentEvent
    ↓
StartDocumentProcessing
    ↓
ProcessingStartResult
    ├── CLAIM_ACQUIRED
    │       → construct DocumentObjectReference
    │       → load document
    │
    └── EFFECT_ALREADY_APPLIED
            → stop successfully
            → no storage read
```

## Document Reference

The processor maps only storage-identity fields:

```text
object_key
object_size
etag
version_id
```

into `DocumentObjectReference`.

The bucket remains trusted runtime configuration inside the S3 adapter.

The processor does not allow event data to select an arbitrary bucket.

## Error Policy

Known processing-start failures become:

```text
UploadedDocumentProcessingError:
failed to start uploaded-document processing
```

Known document-load failures become:

```text
UploadedDocumentProcessingError:
failed to load uploaded document
```

Both are returned through SQS partial batch failure behavior.

Unexpected exceptions remain visible to the outer Lambda safety boundary.

## Temporary Classification Decision

All `DocumentLoadError` variants are retryable at the delivery boundary in this slice.

This includes:

```text
not found
validation failure
dependency failure
```

This is intentionally temporary.

The system does not yet have attempt-aware use cases to:

```text
release a retryable claim
persist a terminal failure
```

Performing either mutation without validating the current `attempt_id` could allow a stale worker to overwrite authoritative state.

Operational evidence is therefore preserved through SQS retries and DLQ redrive until safe state transitions are implemented.

## Why the Processor Performs the Orchestration

`ApplicationUploadedDocumentProcessor` already implements the concrete delivery port and owns translation from application behavior into SQS success or failure.

For this slice, it coordinates:

```text
processing-start
continuation decision
document retrieval
error translation
```

A separate workflow service was considered but intentionally deferred.

The current orchestration remains small and cohesive.

When AI invocation, output validation, completion, and failure persistence are added, the workflow should be reviewed for extraction into a dedicated application service.

## Why Not Load Before Claim Acquisition

Rejected because duplicate workers could:

```text
perform duplicate S3 reads
consume Lambda memory
increase execution time
perform duplicate future inference
```

Ownership must precede downstream effects.

## Why Not Load for EFFECT_ALREADY_APPLIED

Rejected because a successful duplicate outcome means the desired processing-start effect already exists.

No attempt is returned, so the current worker has no authorization context for downstream work.

## Why Not Return LoadedTextDocument to the Handler

Rejected because the Processor Lambda handler owns transport concerns, not document-processing internals.

The delivery contract remains:

```text
process(event) -> None
```

The loaded document stays inside the application-backed workflow.

## Why Not Persist Failure Immediately

Rejected because safe failure writes must validate the active attempt.

A worker may lose its lease before a retrieval error is handled.

Without conditional attempt matching, it could overwrite a newer worker's state.

## Consequences

### Positive

- Duplicate deliveries perform no S3 read.
- Only the claim-owning worker loads the document.
- The bucket remains runtime controlled.
- The Processor Lambda contract remains stable.
- Existing partial batch failure behavior is preserved.
- S3 request cost is reduced for duplicates.
- The workflow is ready for owned-attempt AI execution.
- Runtime composition remains explicit and offline-testable.

### Negative

- Loaded document content is discarded until AI integration is added.
- Deterministic validation failures currently retry.
- A failed retrieval leaves the processing claim active until lease expiration.
- The processor adapter now performs more orchestration.
- The workflow still lacks attempt-aware completion and failure transitions.

These costs are accepted because the slice establishes safe ordering without mixing in provider execution and state persistence.

## Runtime Composition

The claim-aware processor is composed from:

```text
DynamoDBDocumentJobRepository
SystemClock
UUIDProcessingAttemptIdGenerator
configured lease duration
S3DocumentTextLoader
configured document bucket
configured maximum document size
```

Both AWS factories are injectable.

The composition root performs no AWS operation beyond creating client or resource objects.

Warm caching remains in the Lambda entrypoint.

## Reliability Implications

The decision enforces:

```text
claim ownership
    before
document retrieval
```

It does not enforce:

```text
claim still active
    when future result is persisted
```

Future writes must require attempt identity and reject stale workers.

A future retryable failure path should use an attempt-aware release operation.

A future deterministic validation path should persist terminal failure conditionally on the owned attempt.

## Security Implications

The event cannot select the S3 bucket.

A duplicate worker cannot use another worker's active attempt as authorization to retrieve and process the document.

Document content remains inside the processing workflow and must not be logged.

## Testing Decision

Unit tests must prove:

```text
CLAIM_ACQUIRED performs exactly one load
EFFECT_ALREADY_APPLIED performs no load
event metadata maps exactly to the document reference
known loading errors are translated
unexpected errors remain visible
```

Composition tests must prove:

```text
one DynamoDB factory call
one S3 factory call
configured lease propagation
configured bucket propagation
configured size propagation
fresh composition
no real AWS access
```

Handler tests remain focused on:

```text
cold start
warm cache
batch acknowledgement
composition failure
partial batch behavior
```

## Follow-up Work

- Introduce the AI provider into the owned-attempt workflow.
- Decide whether to extract a dedicated application workflow service.
- Carry `ProcessingAttempt` through inference and persistence.
- Add attempt-aware retryable claim release.
- Add attempt-aware terminal failure persistence.
- Add attempt-aware successful completion.
- Add structured logs and metrics.
- Add DLQ reconciliation.
- Add IAM and Terraform updates.