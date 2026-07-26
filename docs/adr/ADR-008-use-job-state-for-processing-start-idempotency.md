# ADR-008: Use Authoritative Job State for Processing-Start Idempotency

## Status

Accepted

## Context

CloudDoc receives uploaded-document notifications through standard SQS.

The delivery model is at least once, so the same logical upload may be delivered multiple times.

Concurrent Lambda invocations may also observe the same job before either worker persists processing ownership.

The system must prevent duplicate deliveries from:

```text
creating multiple active processing owners
incrementing attempts unnecessarily
regressing completed jobs
restarting terminal failures implicitly
stealing a valid active claim
```

Transport identifiers do not fully represent the business effect.

SQS message IDs can change if an event is republished, and S3 metadata does not by itself describe the authoritative workflow lifecycle.

## Decision

CloudDoc will use the authoritative `DocumentJob` state and a bounded `ProcessingAttempt` lease to make processing-start behavior idempotent.

A worker starts processing by acquiring a conditional claim through:

```text
DocumentJobRepository.claim_job
```

A processing attempt contains:

```text
attempt_id
started_at
lease_expires_at
```

The job aggregate stores the active attempt and the number of acquired attempts.

## State Interpretation

The application service interprets authoritative state as follows.

```text
pending_upload
    → acquire a new processing claim

processing with active lease
    → idempotent success

processing with expired lease
    → acquire a replacement claim

succeeded
    → idempotent success

failed or dead
    → conflict
```

The strict aggregate transition remains separate from the application-level duplicate interpretation.

## Conditional Claim

The DynamoDB repository protects claim acquisition with conditional persistence.

When two workers race:

```text
worker A reads pending_upload
worker B reads pending_upload
worker A claims
worker B receives a conditional conflict
```

The losing worker reloads the authoritative job.

If the reloaded state shows an active processing claim or a succeeded job, the desired effect is considered already applied.

Otherwise, the conflict remains an application failure.

## Bounded Lease

Processing ownership is time bounded.

The runtime setting is:

```text
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
```

The default is:

```text
300 seconds
```

An active unexpired lease cannot be stolen by a duplicate delivery.

An expired lease may be replaced by a new attempt.

This allows recovery from workers that stop without completing or releasing the claim.

## Object Ownership

Before acquiring a claim, the application service validates:

```text
event.object_key
    ==
documents/{authoritative_job_id}/source.txt
```

The canonical object-key rule is shared with upload generation and event parsing.

A syntactically valid event for another job cannot start processing for the loaded authoritative job.

## Consequences

### Positive

- Duplicate deliveries do not create multiple active claims.
- Concurrent workers converge on one authoritative owner.
- Completed jobs do not regress.
- Active claims cannot be stolen before lease expiration.
- Expired claims can be recovered.
- Attempt identity supports future stale-worker protection.
- Attempt counts represent acquired processing ownership periods.
- Idempotency is tied to business state rather than transport packaging.
- The Processor Lambda contract remains unchanged.

### Negative

- Processing-start requires an authoritative read before claim evaluation.
- A conditional conflict may require an additional read.
- Lease duration becomes an operational parameter.
- A lease that is too short can permit overlapping work.
- A lease that is too long delays recovery.
- Start idempotency does not make AI inference exactly once.
- Earlier work performed by a losing or expired worker may still need stale-attempt protection.
- Terminal failure messages currently retry until DLQ rather than being acknowledged silently.

These costs are accepted because authoritative conditional claims provide stronger business semantics than transport-level deduplication.

## Alternatives Considered

### Use SQS message ID as the idempotency key

Rejected because message IDs identify queue deliveries, not durable business effects.

The same S3 event may be republished in a new SQS message.

### Use S3 ETag, sequencer, or version ID as the sole idempotency key

Rejected because these values describe object or event metadata rather than the current processing lifecycle.

Their availability and semantics also vary with upload and bucket configuration.

They may still support future observability or event-order policies.

### Make `DocumentJob.start_processing()` idempotent

Rejected because the aggregate should enforce strict lifecycle transitions.

Interpreting duplicate delivery requires authoritative repository context and belongs in the application service.

### Use an unconditional status update

Rejected because concurrent workers could overwrite one another and both believe they acquired ownership.

### Use a separate distributed-lock table

Rejected because the document job already owns the processing lifecycle.

A separate lock would create additional state, expiry rules, synchronization invariants, and cleanup behavior.

### Keep processing status without a lease

Rejected because a worker failure could leave the job permanently owned with no bounded recovery path.

### Restart failed or dead jobs automatically on duplicate upload events

Rejected because an upload notification is not an explicit reprocessing command.

Reprocessing should have a dedicated authorization and lifecycle use case.

## Idempotency Scope

This decision guarantees idempotent acquisition of processing ownership.

It does not guarantee exactly-once execution of:

```text
S3 reads
content decoding
AI inference
result persistence
external side effects
```

Later processing steps must verify active attempt identity before accepting effects from a worker.

## Error Policy

Known application failures are translated through:

```text
ApplicationUploadedDocumentProcessor
    → UploadedDocumentProcessingError
    → SQS partial batch failure
```

Missing jobs, incompatible states, dependency failures, and unresolved races therefore remain retryable and can reach the DLQ.

This preserves operational evidence while the project does not yet have a separate quarantine or semantic-discard mechanism.

## Operational Considerations

The lease duration must be aligned with:

```text
Lambda timeout
SQS visibility timeout
expected processing latency
provider retry strategy
maximum processing duration
```

Future processing may require lease extension or heartbeat behavior if one attempt can legitimately exceed the configured duration.

Monitoring should eventually include:

```text
claim acquisition count
claim conflicts
idempotent active-claim duplicates
expired-lease takeovers
attempt count
jobs stuck in processing
processing lease age
terminal-state event conflicts
```

## Security Considerations

Attempt identities and lease durations are generated by trusted runtime components.

Clients and S3 events cannot select:

```text
attempt_id
lease duration
authoritative job state
object ownership
```

Repository permissions must restrict claim updates to the Processor Lambda role.

## Follow-up Work

- Read the source document from S3.
- Validate document size and UTF-8 content.
- Invoke the AI provider under the active attempt.
- Require attempt identity when persisting results.
- Release retryable attempts safely.
- Persist terminal attempt failures.
- Evaluate lease heartbeat or extension.
- Add structured claim logs and metrics.
- Define DLQ reconciliation and explicit reprocessing.