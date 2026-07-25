# ADR-001: Use DynamoDB Conditional Writes for Job Lifecycle Mutations

## Status

Accepted

## Context

CloudDoc processes documents asynchronously.

The processing workflow may experience:

```text
duplicate queue delivery
worker retries
concurrent workers
expired processing leases
delayed dead-letter messages
stale workers completing after ownership changed
```

DynamoDB provides atomic conditional writes that can reject a mutation when the stored item no longer matches the state observed by the caller.

The repository must protect these invariants:

```text
A job is created only once.
Only one non-expired processing attempt owns a job.
A stale attempt cannot complete, fail, or release another attempt's claim.
Terminal states are not overwritten by delayed work.
Concurrent writes do not silently replace newer state.
```

## Decision

Use DynamoDB conditional writes for all lifecycle-sensitive mutations.

The repository performs a consistent read, applies the domain transition in memory, and persists the resulting item with a `ConditionExpression` that verifies the expected prior state.

The repository translates DynamoDB conditional failures into domain-facing repository errors.

## Conditional Write Rules

### Create

```text
Condition:
  attribute_not_exists(pk)
```

Failure maps to:

```text
JobAlreadyExistsError
```

### Claim a pending job

```text
Condition:
  status = pending_upload
  AND updated_at = expected_updated_at
```

### Reclaim an expired processing job

```text
Condition:
  status = processing
  AND active_attempt_lease_expires_at <= claimed_at
  AND updated_at = expected_updated_at
```

### Complete, fail, or release a processing claim

```text
Condition:
  status = processing
  AND active_attempt_id = expected_attempt_id
  AND updated_at = expected_updated_at
```

### Mark dead

```text
Condition:
  status = expected_status
  AND attempts = expected_attempts
  AND updated_at = expected_updated_at
```

## Optimistic Concurrency Token

`updated_at` is used as the current optimistic concurrency token.

The repository compares the timestamp observed during the read with the value still stored during the write.

This prevents two callers that read the same state from silently overwriting one another.

A dedicated integer version attribute may be introduced later if the timestamp becomes overloaded or if higher write frequency requires a simpler concurrency token.

## Error Translation

DynamoDB-specific exceptions do not cross the repository boundary.

The adapter maps expected conflicts to:

```text
JobAlreadyExistsError
JobNotFoundError
JobClaimConflictError
JobAttemptMismatchError
JobStateConflictError
```

Unexpected AWS failures map to:

```text
RepositoryError
```

This keeps application services independent of boto3 and DynamoDB exception structures.

## Consequences

### Positive

- Claim ownership is enforced atomically.
- Duplicate job creation is rejected safely.
- Stale workers cannot overwrite a newer attempt.
- Delayed dead-letter handling cannot silently replace terminal outcomes.
- The repository contract remains independent of AWS details.
- Tests can verify concurrency rules through observable behavior.
- The design works with DynamoDB's single-item atomicity without transactions.

### Negative

- Each mutation currently requires a read followed by a conditional write.
- Conflict translation may require an additional read after a failed condition.
- `updated_at` carries both business timestamp and concurrency-token responsibilities.
- The repository contains explicit condition expressions that must remain synchronized with the item schema.
- A condition failure does not directly explain which predicate failed.

## Alternatives Considered

### Unconditional overwrites

Rejected because concurrent workers could overwrite newer states and stale attempts could complete jobs they no longer own.

### DynamoDB transactions

Deferred because each lifecycle mutation currently affects one item.

Single-item conditional writes provide the required atomicity with lower conceptual and operational complexity.

Transactions remain an option if future invariants span multiple items.

### Exactly-once processing

Rejected as a system guarantee.

SQS and Lambda operate with at-least-once delivery characteristics. The system instead protects effects through idempotent state transitions, attempt ownership, and conditional writes.

### Distributed locking service

Rejected because DynamoDB already provides atomic conditional mutation on the authoritative job item.

Introducing a separate lock would increase failure modes and require lock-state reconciliation.

### Generic compare-and-swap repository

Deferred because lifecycle-specific operations communicate intent more clearly than a generic `save(expected_version)` API.

The current contract makes claim, completion, failure, retry release, and dead reconciliation explicit.

### Integer version attribute

Deferred for the initial model.

`updated_at` already changes on each domain transition and is sufficient for the current access pattern. A dedicated version number can be introduced if timestamp semantics and concurrency semantics need to be separated.

## Failure Handling

When a conditional write fails, the repository re-reads the current item and classifies the conflict.

Examples:

```text
processing with a valid lease
  → JobClaimConflictError

different active attempt
  → JobAttemptMismatchError

terminal or otherwise incompatible state
  → JobStateConflictError

item removed between read and write
  → JobNotFoundError
```

Unexpected DynamoDB service errors are normalized as `RepositoryError`.

## Testing Strategy

The decision is verified through:

```text
unit tests for item mapping
repository contract tests
Moto-backed DynamoDB integration tests
conditional conflict scenarios
stale attempt scenarios
expired lease reclaim scenarios
terminal-state protection scenarios
unexpected AWS error translation
```

Moto provides fast local feedback for DynamoDB request shape and conditional behavior.

Real AWS validation will be added when infrastructure and deployment slices are introduced.

## Security and Operations

Conditional expressions are constructed by the repository and do not include untrusted expression fragments.

Attribute values are supplied through `ExpressionAttributeValues`.

Operational metrics should eventually track:

```text
claim conflicts
stale attempt conflicts
conditional write failures
repository service errors
dead-letter reconciliations
```

These metrics are intentionally deferred until the observability slice.

## Follow-up Work

- Provision the DynamoDB table with infrastructure as code.
- Add IAM policies scoped to the required table operations.
- Add real-AWS smoke tests in a deployment environment.
- Add repository conflict metrics and structured logs.
- Re-evaluate a dedicated integer version attribute as access patterns evolve.