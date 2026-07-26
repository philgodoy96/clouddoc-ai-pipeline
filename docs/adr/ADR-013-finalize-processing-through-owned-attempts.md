# ADR-013: Finalize Document Processing Through Owned Attempts

## Status

Accepted

## Context

CloudDoc uses standard SQS delivery and therefore assumes duplicate messages and partial failures.

The processing workflow already acquired a DynamoDB-backed processing claim before reading a document or invoking the AI provider. However, the workflow initially stopped after receiving a validated AI result and did not persist successful completion.

Failures after claim acquisition also created a reliability gap:

```text
worker acquires claim
    ↓
retrieval or inference fails
    ↓
message is retried
    ↓
retry observes the active claim
    ↓
active claim is mistaken for an already-applied effect
    ↓
message may be acknowledged
```

This could leave the job in `processing`.

The repository contract already provides attempt-aware operations:

```text
complete_job
fail_job
release_retryable_claim
```

Each operation requires the processing-attempt ID expected to own the job.

The application needed a clear policy for:

- successful finalization
- deterministic terminal failures
- retryable dependency failures
- stale-worker conflicts
- active duplicate deliveries
- terminal duplicate deliveries
- acknowledgement timing

## Decision

CloudDoc will finalize every resolved post-claim outcome through the owned processing attempt.

The application workflow:

```text
ProcessUploadedDocument
```

will receive:

```text
DocumentJobRepository
Clock
```

in addition to its existing processing-start, document-loader, and AI-provider dependencies.

The workflow will apply these rules:

```text
validated success
    → complete_job
    → return PROCESSED

deterministic terminal failure
    → fail_job
    → return TERMINAL_FAILURE_RECORDED

retryable dependency failure
    → release_retryable_claim
    → raise ApplicationDependencyError
```

A result is returned only after the corresponding authoritative repository transition succeeds.

## Active Ownership Versus Applied Effect

`ProcessingStartOutcome` distinguishes:

```text
CLAIM_ACQUIRED
PROCESSING_ALREADY_ACTIVE
EFFECT_ALREADY_APPLIED
```

### CLAIM_ACQUIRED

The current worker receives:

```text
owned ProcessingAttempt
authoritative correlation_id
```

and may continue.

### PROCESSING_ALREADY_ACTIVE

Another unexpired attempt owns processing.

The current delivery performs no S3, AI, or finalization effect and raises an application conflict so SQS can retry later.

### EFFECT_ALREADY_APPLIED

The authoritative job is terminal:

```text
succeeded
failed
dead
```

The current delivery performs no effect and may be acknowledged.

An active attempt is not treated as an applied business effect.

## Successful Completion

After provider output passes the existing application-owned validation, the workflow calls:

```text
complete_job(
    job_id,
    owned_attempt_id,
    extraction_result,
    completed_at
)
```

Only after this succeeds may the workflow return `PROCESSED`.

A successful provider response without durable completion is not considered a successful workflow.

## Terminal Failure Persistence

The application uses stable normalized terminal reasons:

```text
document_not_found
document_validation_failed
invalid_document_reference
invalid_provider_request
ai_provider_invalid_response
```

These values are provider-neutral and safe for durable state.

The workflow calls:

```text
fail_job(
    job_id,
    owned_attempt_id,
    normalized_reason,
    failed_at
)
```

Only after this succeeds may it return `TERMINAL_FAILURE_RECORDED`.

The delivery adapter absorbs that result, allowing the message to be acknowledged.

## Retryable Claim Release

Retryable dependency failures include storage dependency failures and normalized provider availability failures.

Before returning the message as failed, the workflow calls:

```text
release_retryable_claim(
    job_id,
    owned_attempt_id,
    released_at
)
```

Only after release succeeds does the workflow raise `ApplicationDependencyError`.

This permits a redelivery to acquire a new processing attempt rather than being blocked by the previous active claim.

## Repository Error Policy

Repository failures during completion, terminal failure persistence, or claim release are normalized consistently.

```text
JobNotFoundError
    → ApplicationNotFoundError

JobAttemptMismatchError
JobStateConflictError
    → ApplicationConflictError

remaining RepositoryError
    → ApplicationDependencyError
```

A rejected conditional write never produces a false successful result.

A repository failure while releasing a retryable claim takes precedence over the original storage or provider failure because retryable state was not safely restored.

## Shared Runtime Dependencies

The composition root creates one repository and one clock per processing object graph.

The same instances are injected into:

```text
StartDocumentProcessing
ProcessUploadedDocument
```

This provides one explicit repository boundary and one time source for claim acquisition and finalization.

Direct builder calls still create fresh independent graphs.

The Lambda entrypoint may reuse the completed graph across warm invocations.

## Unexpected Exceptions

Unexpected exceptions are not automatically normalized or followed by unconditional claim release.

This decision avoids:

- hiding programming defects
- masking the original exception
- unsafe cleanup when state is uncertain
- rapid retry loops
- release of a claim after an unknown partial effect

The active claim remains authoritative until:

- the original attempt finalizes
- the lease expires
- a future reconciliation process intervenes

## Consequences

### Positive

- Success is acknowledged only after durable completion.
- Terminal failures are acknowledged only after durable failure persistence.
- Retryable failures release ownership before retry.
- Active claims are no longer mistaken for completed effects.
- Terminal duplicates remain idempotent.
- Stale workers cannot finalize a newer attempt.
- Finalization timestamps use an injected clock.
- Failure reasons remain stable and provider-neutral.
- Raw dependency messages are not persisted.
- The Lambda handler remains thin.
- The infrastructure adapter remains outcome-agnostic.
- Runtime composition remains testable without AWS.
- The design provides a clear boundary for future Bedrock integration.

### Negative

- `ProcessUploadedDocument` coordinates more lifecycle behavior.
- The workflow now depends directly on repository and clock ports.
- Provider invocation can still be repeated if inference succeeds but completion persistence fails.
- Unexpected failures may leave the claim active until lease expiration.
- A repository outage during claim release can delay retry progress.
- Active-message retries may continue until the current lease expires.
- Additional operational reconciliation is still required.

## Exactly-Once Position

This decision does not provide exactly-once inference.

A worker may:

```text
invoke provider successfully
    ↓
fail to persist complete_job
    ↓
lose or expire its claim
    ↓
allow another attempt to invoke the provider again
```

The system guarantees that only the currently owned attempt may persist authoritative final state.

It does not guarantee that the external provider is called only once.

This trade-off is accepted because DynamoDB conditional writes can protect business state, while exactly-once coordination with an external inference service would require provider-side idempotency support or a substantially different execution model.

## Alternatives Considered

### Continue acknowledging active duplicate deliveries

Rejected.

An active attempt proves current ownership, not completion. Acknowledging the duplicate could remove the only remaining queue delivery while the job remains unfinished.

### Retry without releasing the owned claim

Rejected for known retryable dependency failures.

A prompt redelivery would observe the still-active claim and remain unable to continue. Explicit release restores a state that permits a new attempt.

### Release the claim for every exception

Rejected.

Unexpected exceptions may occur after an unknown partial effect. Automatic release could create repeated effects, hide defects, and generate rapid retry storms.

### Persist raw exception messages

Rejected.

SDK and provider messages may be unstable, verbose, sensitive, or include implementation details. Stable application-owned reasons are safer for persistence, metrics, and API exposure.

### Treat invalid AI output as retryable

Rejected for the current provider contract.

A normalized invalid-response error means the provider returned a response that failed the expected structured contract. Repeating the same deterministic request is not assumed to repair that result automatically.

A future provider-specific policy may refine this decision when prompt versions, model versions, and bounded retry counts are available.

### Add separate application services for completion, failure, and release

Deferred.

The repository already exposes application-facing attempt-aware operations. Introducing one wrapper service per method would add structure without clarifying the current workflow.

Extraction may be reconsidered if finalization policy grows substantially or is reused by other workflows.

### Integrate Amazon Bedrock in the same slice

Deferred.

The priority is to establish reliable state and acknowledgement semantics before introducing external inference configuration, IAM, throttling, cost, and provider-specific behavior.

## Follow-Up Decisions

Future work must define:

- lease heartbeat or extension
- stale-processing reconciliation
- maximum processing-attempt policy
- SQS receive-count-aware behavior
- DLQ reconciler ownership rules
- behavior after Lambda timeout
- metrics for claim acquisition and rejection
- metrics for completion, terminal failure, and claim release
- alarms for expired or long-running processing attempts
- Amazon Bedrock adapter and provider-specific resilience policy
- Terraform and IAM changes