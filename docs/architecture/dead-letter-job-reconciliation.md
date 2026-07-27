# Dead-Letter Job Reconciliation

## Status

Implemented as an incremental reliability slice.

This document describes how CloudDoc reconciles exhausted processing-queue deliveries with the authoritative `DocumentJob` lifecycle stored in DynamoDB.

The reconciler records unfinished attempted jobs as `dead`, preserves terminal business outcomes, protects active workers, and isolates failures through the Lambda partial batch response.

Automatic redrive, operator replay, stale-job scanning, real AWS deployment validation, and operator recovery tooling remain separate follow-up work.

Structured operational logging, CloudWatch alarms, dashboard declarations, reconciler IAM, and Terraform consumer topology are implemented in the repository.

## Purpose

SQS and DynamoDB own different forms of state:

```text
SQS
    → delivery attempts
    → redrive policy
    → dead-letter retention

DynamoDB
    → authoritative DocumentJob lifecycle
    → processing attempts
    → successful result
    → terminal failure
    → dead state
```

Moving a processing message to the DLQ proves that queue delivery retries were exhausted.

It does not prove that the related document job is still unfinished.

A duplicate message may reach the DLQ after another delivery has already persisted:

```text
succeeded
failed
dead
```

The reconciler must therefore consult authoritative job state before applying any lifecycle transition.

## Topology

```text
S3 ObjectCreated
    ↓
Processing Queue
    ↓ retries exhausted
Processing DLQ
    ↓
DLQ Reconciler Lambda
    ↓
ReconcileDeadLetteredDocument
    ↓
DocumentJobRepository
    ↓
DynamoDB
```

The reconciler is a control-plane recovery workflow.

It does not:

- retrieve document bodies from S3
- invoke the AI provider
- repeat inference
- create upload URLs
- redrive messages automatically
- scan the complete jobs table

## Responsibility Boundaries

### Processing DLQ

The DLQ:

- retains exhausted processing messages
- triggers the reconciliation Lambda
- preserves the original processing message body
- provides a new SQS delivery boundary for reconciliation

The DLQ does not determine the final business state.

### DLQ Reconciler Lambda

The Lambda:

- loads runtime settings
- composes and caches the reconciliation processor
- validates the outer SQS batch
- parses each SQS record independently
- reuses the existing SQS-wrapped S3 parser
- reports partial batch failures

The Lambda does not make lifecycle decisions directly.

### Delivery Processor

`ApplicationDeadLetteredDocumentProcessor`:

- receives one normalized `UploadedDocumentEvent`
- delegates only `event.job_id` to the application workflow
- absorbs successful reconciliation results
- translates known `ApplicationError` values
- preserves unexpected exceptions

The object key, bucket, and DLQ message ID remain operational context. They do not authorize a job transition.

### Application Workflow

`ReconcileDeadLetteredDocument`:

- loads authoritative job state
- identifies terminal idempotency
- verifies dead-letter reconciliation eligibility
- protects active processing leases
- conditionally requests `mark_dead(...)`
- reconciles conditional-write races
- normalizes repository failures
- returns an explicit reconciliation result

### Repository

`DocumentJobRepository` remains the application-facing persistence boundary.

The reconciler uses:

```text
get_job(...)
mark_dead(...)
```

No DLQ-specific repository implementation is introduced.

## Normalized Dead-Letter Reason

The application persists:

```text
processing_retries_exhausted
```

through:

```text
DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED
```

The persisted reason is stable and application-owned.

The workflow does not persist:

- raw Lambda exception messages
- provider SDK messages
- stack traces
- document content
- SQS message bodies
- AWS response payloads

## Reconciliation Result

The workflow returns:

```text
DeadLetterReconciliationResult
```

with one of two outcomes.

### DEAD_RECORDED

```text
mark_dead(...) succeeded
```

The job was eligible and the dead state was durably persisted.

The delivery may be acknowledged.

### EFFECT_ALREADY_APPLIED

The authoritative job was already terminal:

```text
succeeded
failed
dead
```

No mutation was performed.

The delivery may be acknowledged idempotently.

Repository, conflict, and missing-resource failures remain exceptions rather than successful results.

## Eligibility Rules

### Succeeded Job

```text
status = succeeded
    → preserve successful result
    → EFFECT_ALREADY_APPLIED
```

The reconciler never overwrites a successful document job.

### Failed Job

```text
status = failed
    → preserve terminal business failure
    → EFFECT_ALREADY_APPLIED
```

The reconciler does not replace a deterministic business failure with queue exhaustion.

### Dead Job

```text
status = dead
    → no additional mutation
    → EFFECT_ALREADY_APPLIED
```

Repeated DLQ delivery is idempotent.

### Pending Job Without Attempts

```text
status = pending_upload
attempts = 0
    → ApplicationConflictError
```

A job that never acquired a processing attempt does not prove processing retry exhaustion.

### Pending Job With Attempts

```text
status = pending_upload
attempts >= 1
    → eligible for mark_dead(...)
```

This state represents a job whose prior retryable claim was released.

### Processing Job With Active Lease

```text
status = processing
lease not expired
    → ApplicationConflictError
```

A healthy active worker must not be terminated by an old duplicate message in the DLQ.

No `mark_dead(...)` call is attempted.

### Processing Job With Expired Lease

```text
status = processing
lease expired
    → eligible for mark_dead(...)
```

The expired attempt is no longer protected as live work.

## Snapshot-Aware Dead Transition

Eligibility is evaluated from one authoritative `DocumentJob` snapshot.

The repository operation requires:

```python
mark_dead(
    job_id,
    reason,
    expected_updated_at=observed_job.updated_at,
    marked_at=clock.now(),
)
```

`expected_updated_at` is the optimistic concurrency token from the exact snapshot evaluated by the application service.

This protects against the following race:

```text
reconciler reads retry-ready job
    ↓
another worker acquires a new attempt
    ↓
reconciler calls mark_dead with old updated_at
    ↓
repository rejects stale snapshot
    ↓
new attempt survives
```

The DynamoDB adapter:

1. loads the current item
2. verifies `current_job.updated_at == expected_updated_at`
3. validates lifecycle eligibility
4. performs a conditional write
5. keeps conditions on status, attempts, and updated-at state

The in-memory repository follows the same contract.

Lease policy remains in the application service. The repository protects persistence concurrency rather than deciding whether a lease is operationally active.

## Conditional Conflict Reconciliation

A conditional dead transition can fail because the job changed after the initial read.

The workflow reloads authoritative state once.

### Concurrent Success

```text
initial state eligible
    ↓
processor completes job
    ↓
mark_dead rejected
    ↓
reload shows succeeded
    → EFFECT_ALREADY_APPLIED
```

The successful result wins.

### Concurrent Terminal Failure

```text
initial state eligible
    ↓
processor records failed
    ↓
mark_dead rejected
    ↓
reload shows failed
    → EFFECT_ALREADY_APPLIED
```

The recorded business failure wins.

### Concurrent Dead Reconciliation

```text
initial state eligible
    ↓
another reconciler records dead
    ↓
mark_dead rejected
    ↓
reload shows dead
    → EFFECT_ALREADY_APPLIED
```

The operation remains idempotent.

### Concurrent New Claim

```text
initial state retry-ready
    ↓
another worker acquires a new attempt
    ↓
mark_dead rejected
    ↓
reload shows processing
    → ApplicationConflictError
```

The reconciler does not terminate the new owner.

### Remaining Non-Terminal State

When the reloaded state remains non-terminal, the workflow raises:

```text
document job changed before dead-letter reconciliation completed
```

The DLQ record remains retryable.

## Repository Failure Normalization

### Missing Job

A missing job produces:

```text
ApplicationNotFoundError
```

The exhausted message is not silently acknowledged.

### Lookup Dependency Failure

A repository failure during `get_job(...)` produces:

```text
ApplicationDependencyError
```

Safe context includes:

```text
job_id
```

### Dead-State Persistence Failure

A repository dependency failure during `mark_dead(...)` produces:

```text
ApplicationDependencyError
```

Safe context includes:

```text
job_id
operation = mark_dead
```

### Conditional State Conflict

`JobStateConflictError` triggers one authoritative reload.

It becomes a successful no-effect result only when the reloaded job is terminal.

Unexpected exceptions are not broadly normalized by the application workflow.

## Event Normalization

The DLQ retains processing messages whose body contains the original S3 event notification.

The reconciler reuses:

```text
parse_sqs_record_with_s3_notification(...)
```

Each outer DLQ SQS record is normalized into one or more:

```text
UploadedDocumentEvent
```

The parser continues validating:

- outer SQS record shape
- JSON body shape
- S3 event shape
- configured source bucket
- canonical object key
- job identity
- object metadata

A separate DLQ payload schema is not introduced because the dead-lettered message body preserves the original processing payload.

## Partial Batch Failure

The testable handler processes each outer SQS record independently.

```text
valid record
    → all contained normalized events reconcile
    → record acknowledged

parsing failure
    → record enters batchItemFailures

known reconciliation failure
    → record enters batchItemFailures

unexpected per-record failure
    → record enters batchItemFailures
```

When one outer SQS record contains multiple S3 events, processing stops after the first failure in that record.

Valid sibling SQS records continue.

A record without a usable `messageId` fails the invocation because the handler cannot identify it in the partial batch response.

## Runtime Composition

The composition root builds:

```text
DynamoDBDocumentJobRepository
    ↓
ReconcileDeadLetteredDocument
    ↓
ApplicationDeadLetteredDocumentProcessor
```

Each direct builder call creates a fresh object graph containing:

- one DynamoDB repository
- one `SystemClock`
- one reconciliation workflow
- one delivery adapter
- an injected operational logger

The builder does not create:

- an S3 client
- an AI provider
- an SQS client
- a Bedrock client

The Lambda module caches only the fully composed delivery processor for warm invocations.

Runtime settings are loaded for every invocation.

A composition failure leaves the cache empty and fails the invocation.

## Reconciliation Telemetry Ownership

Telemetry ownership is split:

```text
adapter emits reconciliation.record_completed
handler emits reconciliation.record_failed
handler emits reconciliation.batch_completed
```

`DEAD_RECORDED` emits `reconciliation.record_completed` at warning severity with:

```text
failure_reason=processing_retries_exhausted
```

`EFFECT_ALREADY_APPLIED` emits the same event name at info severity.

The handler owns failed-record and batch-summary telemetry. Logging failure cannot change acknowledgement or partial-batch behavior.

Detailed field contracts, Terraform consumer wiring, quarantine alarms, and the operations dashboard are documented in [CloudWatch Observability](cloudwatch-observability.md) and the dead-letter reconciliation infrastructure document.

## Acknowledgement Semantics

```text
DEAD_RECORDED
    → processor returns None
    → acknowledge DLQ record

EFFECT_ALREADY_APPLIED
    → processor returns None
    → acknowledge DLQ record

ApplicationNotFoundError
ApplicationConflictError
ApplicationDependencyError
    → delivery processor error
    → batchItemFailures
    → retry DLQ record

unexpected per-record exception
    → batchItemFailures
    → retry DLQ record
```

The reconciler does not automatically redrive acknowledged messages to the processing queue.

## Idempotency and Concurrency Guarantees

The system guarantees:

- a terminal job is never rewritten by reconciliation
- a job with an active unexpired lease is not marked dead
- an untouched pending job is not marked dead
- a stale observed snapshot cannot kill a newly acquired attempt
- a concurrent terminal transition wins over dead reconciliation
- repeated reconciliation of a dead job is idempotent
- unrelated batch records remain isolated

The system does not claim exactly-once Lambda execution or exactly-once reconciliation delivery.

Correctness comes from authoritative reads, stable terminal results, optimistic concurrency, and conditional writes.

## Security Boundary

The DLQ reconciler requires permission to:

- consume messages from the processing DLQ
- read the document-jobs table
- conditionally update eligible document-job items
- emit approved operational telemetry

It does not require permission to:

- read source document objects
- invoke Bedrock
- create upload URLs
- write arbitrary S3 objects
- send messages back to the processing queue
- mutate unrelated DynamoDB tables

Document content and full queue payloads must not be logged.

## Scaling and Operational Posture

The reconciler is a low-throughput control-plane workflow.

Initial operating assumptions:

```text
small SQS batch size
partial batch response enabled
bounded Lambda concurrency
no automatic redrive
DLQ retention long enough for investigation
```

High concurrency is not required for the initial portfolio scope.

The authoritative conditional transition allows safe horizontal execution when multiple reconciler invocations overlap.

## Testing Strategy

Coverage includes:

- dead-letter reason stability
- reconciliation-result invariants
- terminal-state idempotency
- expired processing eligibility
- active processing protection
- attempted pending-state eligibility
- untouched pending-state rejection
- missing-job behavior
- repository dependency normalization
- conditional race reconciliation
- stale snapshot rejection in the repository contract
- Moto-backed stale snapshot rejection
- preservation of newly acquired attempts
- preservation of concurrent successful completion
- delivery processor translation
- SQS/S3 parser reuse
- partial batch isolation
- multi-event message behavior
- malformed queue events
- runtime composition
- fresh direct object graphs
- offline composition
- Lambda cold-start composition
- Lambda warm processor caching
- builder failure propagation
- reconciliation.record_completed ownership on the adapter
- reconciliation.record_failed ownership on the handler
- reconciliation.batch_completed summaries
- dead_recorded warning severity and failure_reason
- logging-failure isolation

Tests do not require real AWS services.

## Intentionally Deferred

The following are intentionally deferred:

- automatic DLQ redrive
- operator replay API
- scheduled stale-job scanning
- lease heartbeat
- maximum processing-attempt policy
- receive-count-aware business policy
- EventBridge recovery schedules
- custom metrics
- distributed tracing
- deployed AWS validation
- operator recovery tooling

## Follow-Up Work

Remaining operational follow-up includes:

- real AWS deployment and validation
- alarm notification routing
- operator-controlled replay and investigation workflow
- SLO definitions

## Related Documentation

- [CloudWatch Observability](cloudwatch-observability.md)
- [Dead-letter reconciliation infrastructure](dead-letter-reconciliation-infrastructure.md)
- [Runtime Composition](runtime-composition.md)
- [ADR-024: Use Native AWS Metrics and Structured Application Logs](../adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)
