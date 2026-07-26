# ADR-010: Use Explicit Processing Continuation Outcomes

## Status

Accepted

## Context

CloudDoc processes uploaded-document events delivered through standard SQS.

The delivery model is at least once, and concurrent Lambda workers may race for the same document job.

`StartDocumentProcessing` previously returned `None` for all successful paths:

```text
a new processing claim was acquired
another worker already held an active claim
the job had already succeeded
```

That contract was sufficient while processing-start was the final application effect.

It became unsafe once document retrieval and AI execution were introduced as upcoming workflow stages.

Without an explicit continuation decision, a duplicate worker could interpret success as authorization to continue even though another worker owned the active attempt.

## Decision

CloudDoc will return an explicit `ProcessingStartResult` from `StartDocumentProcessing`.

The result contains:

```text
outcome
attempt
```

The supported outcomes are:

```text
CLAIM_ACQUIRED
EFFECT_ALREADY_APPLIED
```

## Invariants

```text
CLAIM_ACQUIRED
    → requires the attempt acquired by the current worker

EFFECT_ALREADY_APPLIED
    → must not include an attempt
```

The result is immutable and rejects invalid combinations during construction.

## State Mapping

```text
pending_upload
    → CLAIM_ACQUIRED

processing with expired lease
    → CLAIM_ACQUIRED

processing with active lease
    → EFFECT_ALREADY_APPLIED

succeeded
    → EFFECT_ALREADY_APPLIED

failed or dead
    → ApplicationConflictError
```

## Concurrent Claims

When two workers race:

```text
one conditional claim succeeds
one conditional claim fails
```

The winner receives:

```text
CLAIM_ACQUIRED
owned ProcessingAttempt
```

The losing worker reloads authoritative state and receives:

```text
EFFECT_ALREADY_APPLIED
no attempt
```

The competing worker's active attempt is never returned to the loser.

## Why Return the Attempt

Future retrieval, inference, completion, and failure effects must remain associated with the worker's acquired processing attempt.

Returning the exact owned attempt provides:

```text
attempt identity
lease start
lease expiration
```

The result does not return the full job aggregate because downstream continuation needs authorization, not a general state snapshot.

## Why Not Return a Boolean

A boolean such as:

```text
should_continue
```

was rejected because it hides business meaning and scales poorly as additional outcomes emerge.

Named outcomes provide clearer:

```text
application semantics
test assertions
future structured logs
future metrics
interview-level architectural explanation
```

## Why Not Return the Active Attempt for Already-Applied Work

The active attempt may belong to another worker.

Returning it would blur observation and ownership.

A worker may observe that work is already in progress without receiving permission to perform downstream effects.

Therefore:

```text
EFFECT_ALREADY_APPLIED
    → attempt = None
```

## Why Preserve the Delivery-Layer None Contract

The Processor Lambda currently depends on:

```text
UploadedDocumentProcessor.process(...) -> None
```

The delivery layer only needs to know whether processing succeeded or failed for the SQS message.

Claim details remain application concerns.

`ApplicationUploadedDocumentProcessor` therefore absorbs the application result while preserving the current delivery interface.

The next slice may use the result internally when composing document retrieval.

## Consequences

### Positive

- Only the claim-owning worker is authorized to continue.
- Duplicate deliveries can stop successfully without downstream effects.
- Concurrent claim outcomes become explicit and testable.
- The losing worker never receives another worker's attempt.
- Future side effects can carry the owned `attempt_id`.
- The domain aggregate remains strict.
- DynamoDB-specific conflict details remain hidden.
- The Processor Lambda delivery contract remains stable.
- Application semantics are clearer than an ambiguous `None`.

### Negative

- Callers of `StartDocumentProcessing` must handle a result.
- The infrastructure adapter currently discards useful continuation information.
- Additional workflow composition is required before document retrieval can use the result.
- The result introduces another application type that must remain stable.
- The two outcomes do not yet represent terminal rejection or retryable release decisions.

These costs are accepted because continuation authorization must be explicit before adding external effects.

## Alternatives Considered

### Continue Returning None

Rejected because success does not indicate whether the current worker owns the processing attempt.

### Return True or False

Rejected because boolean meaning is implicit and difficult to evolve.

### Return the Complete DocumentJob

Rejected because it exposes more state than downstream continuation requires and encourages coupling to aggregate internals.

### Return the Current Active Attempt for Every Successful Path

Rejected because observing another worker's attempt is not equivalent to owning it.

### Throw an Exception for Duplicate Active Claims

Rejected because an active claim already satisfies the desired processing-start effect.

Treating expected duplicate delivery as failure would create unnecessary retries and DLQ traffic.

### Move Idempotency Into the Processor Lambda

Rejected because authoritative lifecycle interpretation belongs in the application service, not the transport handler.

## Reliability Implications

The explicit result establishes a clean rule:

```text
CLAIM_ACQUIRED
    → downstream effects may begin

EFFECT_ALREADY_APPLIED
    → acknowledge success without downstream effects
```

This does not guarantee exactly-once retrieval or inference.

Later effects must still validate attempt identity when persisting state.

A worker whose lease expires may continue running, so completion and failure operations must reject stale attempts.

## Security Implications

The returned attempt acts as an authorization context for future writes.

Downstream code must not synthesize attempt IDs from event data or retrieve another worker's attempt and treat it as owned.

Attempt IDs remain generated by trusted runtime components.

## Testing Decision

The concurrency integration test must prove:

```text
one CLAIM_ACQUIRED result
one EFFECT_ALREADY_APPLIED result
one persisted active attempt
one persisted attempt count
```

The test must not depend on worker ordering.

Infrastructure adapter tests must prove both successful outcomes remain hidden behind the delivery-layer `None` contract.

## Follow-up Work

- Inject `DocumentTextLoader` into the application-backed processor.
- Continue only for `CLAIM_ACQUIRED`.
- Carry the owned attempt through retrieval and AI execution.
- Define retrieval failure classification.
- Release retryable claims safely.
- Persist terminal failures with attempt identity.
- Complete jobs with attempt-aware conditional writes.
- Add outcome logs and metrics.