# ADR-014: Reconcile Exhausted Processing Deliveries Against Authoritative Job State

## Status

Accepted

## Context

CloudDoc processes uploaded documents through a standard SQS queue.

After the queue redrive policy exhausts delivery attempts, the message moves to a processing DLQ.

SQS and DynamoDB represent different truths:

```text
SQS
    → delivery exhaustion

DynamoDB
    → authoritative DocumentJob lifecycle
```

A message in the DLQ does not necessarily mean the related job is unfinished.

Another duplicate delivery may already have persisted:

```text
succeeded
failed
dead
```

The system needs a controlled workflow that reconciles queue exhaustion with authoritative business state without repeating document retrieval or AI inference.

The repository already supports a dead lifecycle transition, but reconciliation must also protect active workers and concurrent state changes.

## Decision

CloudDoc will introduce a DLQ Reconciler Lambda backed by the application service:

```text
ReconcileDeadLetteredDocument
```

The Lambda will consume processing-DLQ messages, reuse the existing SQS-wrapped S3 parser, and delegate normalized job identity to the application workflow.

The application workflow will:

1. load the authoritative document job
2. preserve terminal states
3. reject untouched pending jobs
4. reject processing jobs with active leases
5. allow expired processing jobs
6. allow retry-ready pending jobs with prior attempts
7. request a snapshot-aware dead transition
8. reload authoritative state after a conditional conflict
9. return an explicit reconciliation result
10. normalize known repository failures

The reconciler will not automatically redrive messages.

## Authoritative Outcomes

The workflow returns:

```text
DEAD_RECORDED
EFFECT_ALREADY_APPLIED
```

### DEAD_RECORDED

The unfinished attempted job was conditionally persisted as `dead`.

The DLQ record may be acknowledged.

### EFFECT_ALREADY_APPLIED

The job was already terminal:

```text
succeeded
failed
dead
```

No mutation was required.

The DLQ record may be acknowledged.

Missing jobs, active ownership, unresolved conflicts, and repository failures remain retryable exceptions.

## Stable Dead-Letter Reason

The application persists:

```text
processing_retries_exhausted
```

through:

```text
DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED
```

Raw queue bodies, exception messages, stack traces, and document content are not persisted as lifecycle reasons.

## Active-Lease Policy

A processing job may be marked dead only when its active lease has expired.

```text
active lease
    → preserve worker
    → reconciliation conflict

expired lease
    → eligible for dead transition
```

This policy belongs to the application service because it is an operational lifecycle decision.

The repository does not interpret lease freshness.

## Snapshot-Aware Persistence

`mark_dead(...)` requires:

```text
expected_updated_at
marked_at
```

`expected_updated_at` is copied from the exact job snapshot whose eligibility the application service evaluated.

This prevents a stale reconciliation decision from terminating a state created after the read.

Example:

```text
reconciler reads released pending job
    ↓
processor acquires a new attempt
    ↓
reconciler calls mark_dead with old updated_at
    ↓
repository rejects the stale snapshot
```

The repository also preserves its conditional write on status, attempts, and updated-at state.

The in-memory repository and DynamoDB repository implement the same concurrency contract.

## Conflict Reconciliation

After `JobStateConflictError`, the application service reloads the job once.

```text
reloaded succeeded / failed / dead
    → EFFECT_ALREADY_APPLIED

reloaded non-terminal
    → ApplicationConflictError
```

This gives precedence to concurrently persisted terminal business outcomes while protecting new processing ownership.

## Delivery Boundary

The application-backed delivery processor receives:

```text
UploadedDocumentEvent
```

but passes only:

```text
job_id
```

to the lifecycle workflow.

Bucket, object key, event metadata, and DLQ message ID do not authorize a job transition.

The processor absorbs successful results and translates known `ApplicationError` values into a retryable delivery error.

## Parser Reuse

The processing DLQ retains the original processing message body, which contains the S3 event notification.

The reconciler reuses:

```text
parse_sqs_record_with_s3_notification(...)
```

A separate DLQ event schema is not introduced.

The outer DLQ SQS `messageId` remains the identifier used in `batchItemFailures`.

## Lambda Partial Batch Behavior

Each outer SQS record is isolated.

A parsing, workflow, or unexpected per-record failure adds only that message ID to:

```text
batchItemFailures
```

Valid sibling records continue.

When one outer message contains multiple S3 events, processing stops after the first failure because the complete outer message is the retry unit.

## Runtime Composition

The runtime graph is:

```text
DynamoDBDocumentJobRepository
    ↓
ReconcileDeadLetteredDocument
    ↓
ApplicationDeadLetteredDocumentProcessor
```

The builder creates fresh graphs and requires only DynamoDB.

The Lambda entrypoint caches the fully composed processor for warm invocations.

The reconciler does not compose S3, AI-provider, SQS, or Bedrock clients.

## Consequences

### Positive

- Queue exhaustion is reflected in authoritative business state.
- Terminal business outcomes are preserved.
- Active workers are protected.
- Newly acquired attempts survive stale reconciliation.
- Conditional races are resolved against fresh authoritative state.
- Dead reconciliation is idempotent.
- Missing resources are not silently discarded.
- Per-message failures are isolated.
- The existing event parser is reused.
- The reconciler has a narrow IAM boundary.
- No document retrieval or inference occurs.
- The application service remains testable without AWS.
- The DynamoDB concurrency guarantee is covered with Moto.

### Negative

- DLQ messages may remain retrying when jobs are missing or actively processing.
- An active worker may outlive several DLQ reconciliation deliveries.
- The workflow performs an additional read after a conditional conflict.
- `updated_at` acts as the optimistic concurrency token and therefore requires timestamp precision to remain stable across serialization.
- Automatic replay is not provided.
- Operational observability remains incomplete.
- Infrastructure resources are not yet implemented.

## Exactly-Once Position

The design does not claim exactly-once DLQ delivery or exactly-once Lambda execution.

Repeated messages are safe because:

- terminal states return an idempotent result
- dead-state persistence is conditional
- stale snapshots are rejected
- active leases are protected
- partial batch failures preserve retryable records

## Alternatives Considered

### Mark every DLQ-related job dead without reading it

Rejected.

A duplicate exhausted message could overwrite a job that already succeeded or failed.

### Mark every processing job dead

Rejected.

The job may have an active healthy worker. Reconciliation requires lease-expiration evaluation.

### Let the repository decide lease freshness

Rejected.

Lease freshness is application policy. The repository should protect persistence concurrency, not operational meaning.

### Use only the repository's internal read

Rejected.

The internal read may observe a newer claim than the snapshot evaluated by the application service, allowing stale policy decisions to affect new work.

### Add the processing attempt ID to `mark_dead(...)`

Deferred.

Dead-letter reconciliation may begin from a released pending state with no active attempt. The observed `updated_at` token protects both pending and processing snapshots without introducing a second method.

### Create a dedicated DLQ payload model

Rejected for the current queue topology.

The DLQ message body preserves the original processing payload, so the existing parser remains the correct normalization boundary.

### Automatically redrive after reconciliation

Rejected.

Dead reconciliation records retry exhaustion. Replay requires an explicit operator or policy decision, investigation context, and protections against repeated poison messages.

### Read S3 or invoke the AI provider from the reconciler

Rejected.

The reconciler owns lifecycle recovery only. Reprocessing belongs to the processing queue and workflow.

### Scan DynamoDB for stale jobs in the same slice

Deferred.

Scheduled stale-job recovery has different triggering, scaling, and operational semantics from DLQ-driven reconciliation.

## Follow-Up Decisions

Future work must define:

- processing queue and DLQ infrastructure
- SQS redrive settings
- DLQ Lambda event-source mapping
- reconciler IAM permissions
- reconciliation logs and metrics
- alarms for DLQ depth and repeated failures
- operator investigation and replay workflow
- stale-job scheduled reconciliation
- maximum-attempt policy
- retention and cleanup policy for dead jobs