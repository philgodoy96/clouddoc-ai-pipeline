# DynamoDB Data Model

## Purpose

CloudDoc stores document-processing job state in DynamoDB.

The table is designed around one primary access pattern:

```text
Get and mutate a document job by job_id
```

The current model intentionally avoids secondary indexes because no query pattern requires them yet.

## Table

```text
Table name: clouddoc-document-jobs
Billing mode: PAY_PER_REQUEST
Partition key: pk
Sort key: none
```

## Primary Key

Each document job uses the following partition-key format:

```text
JOB#{job_id}
```

Example:

```text
JOB#job-001
```

The explicit prefix keeps the keyspace extensible if additional entity types are introduced later.

## Stored Attributes

| Attribute | Type | Required | Description |
|---|---:|---:|---|
| `pk` | String | Yes | Partition key in the format `JOB#{job_id}`. |
| `entity_type` | String | Yes | Persisted entity discriminator. Current value: `document_job`. |
| `job_id` | String | Yes | Domain identifier for the document job. |
| `status` | String | Yes | Current lifecycle state. |
| `request_id` | String | Yes | Identifier for the originating request. |
| `correlation_id` | String | Yes | Identifier used to trace the workflow across asynchronous boundaries. |
| `created_at` | String | Yes | UTC ISO-8601 creation timestamp. |
| `updated_at` | String | Yes | UTC ISO-8601 timestamp of the latest state change. |
| `attempts` | Number | Yes | Number of processing claims issued for the job. |
| `active_attempt_id` | String or Null | Yes | Identifier of the worker attempt currently owning the claim. |
| `active_attempt_started_at` | String or Null | Yes | UTC ISO-8601 start time of the active attempt. |
| `active_attempt_lease_expires_at` | String or Null | Yes | UTC ISO-8601 lease-expiration time for the active attempt. |
| `processing_result` | Map or Null | Yes | Validated AI extraction result for succeeded jobs. |
| `error_reason` | String or Null | Yes | Failure or retry-exhaustion reason for failed or dead jobs. |

## Lifecycle States

Supported persisted values for `status`:

```text
pending_upload
processing
succeeded
failed
dead
```

### `pending_upload`

Expected shape:

```text
active_attempt_id = null
active_attempt_started_at = null
active_attempt_lease_expires_at = null
processing_result = null
error_reason = null
```

A retry-released job may return to `pending_upload` with `attempts > 0`.

### `processing`

Expected shape:

```text
attempts >= 1
active_attempt_id != null
active_attempt_started_at != null
active_attempt_lease_expires_at != null
processing_result = null
error_reason = null
```

### `succeeded`

Expected shape:

```text
attempts >= 1
active_attempt_id = null
active_attempt_started_at = null
active_attempt_lease_expires_at = null
processing_result != null
error_reason = null
```

### `failed`

Expected shape:

```text
attempts >= 1
active_attempt_id = null
active_attempt_started_at = null
active_attempt_lease_expires_at = null
processing_result = null
error_reason != null
```

### `dead`

Expected shape:

```text
attempts >= 1
active_attempt_id = null
active_attempt_started_at = null
active_attempt_lease_expires_at = null
processing_result = null
error_reason != null
```

## Timestamp Policy

All persisted timestamps use timezone-aware UTC ISO-8601 strings.

Example:

```text
2026-07-25T12:00:00+00:00
```

The mapper rejects:

```text
naive timestamps
non-UTC offsets
non-string timestamp values
```

This keeps ordering and lease comparisons unambiguous.

## Numeric Representation

DynamoDB represents numbers as `Decimal` values through the boto3 resource API.

The mapper applies these rules:

```text
integral Decimal → int
non-integral Decimal → float
```

This conversion is appropriate for the current AI output contract because persisted results originate from JSON-compatible values.

Exact-decimal business values, such as money, should use a dedicated typed schema rather than generic AI `key_fields`.

## Access Patterns

### Create a job

```text
Key:
  pk = JOB#{job_id}

Condition:
  attribute_not_exists(pk)
```

This prevents duplicate job creation.

### Get a job

```text
Key:
  pk = JOB#{job_id}

Read consistency:
  strongly consistent
```

Strongly consistent reads are used because lifecycle mutations depend on observing the latest state.

### Claim a pending job

```text
Expected state:
  status = pending_upload
  updated_at = previously observed value
```

The write changes the job to `processing`, increments `attempts`, and persists the active lease.

### Reclaim an expired processing job

```text
Expected state:
  status = processing
  active_attempt_lease_expires_at <= claimed_at
  updated_at = previously observed value
```

The write replaces the expired attempt with a new owner and increments `attempts`.

### Complete, fail, or release a claim

```text
Expected state:
  status = processing
  active_attempt_id = expected attempt
  updated_at = previously observed value
```

These conditions prevent stale workers from overwriting the current owner.

### Mark a job dead

```text
Expected state:
  status = previously observed status
  attempts = previously observed attempt count
  updated_at = previously observed value
```

This protects succeeded and failed outcomes from delayed dead-letter reconciliation.

## Optimistic Concurrency

`updated_at` acts as the current optimistic concurrency token.

A mutation succeeds only when the stored item still matches the version previously read by the repository.

This prevents lost updates when multiple workers operate on the same job concurrently.

## Item Mapping Boundary

The persistence mapper is intentionally specific to `DocumentJob`.

It is responsible for:

```text
domain-to-item serialization
DynamoDB-compatible number conversion
strict persisted-value validation
item-to-domain reconstruction
cross-field lifecycle validation through DocumentJob.rehydrate()
```

A generic object-mapping framework was intentionally not introduced because the current system has one aggregate and one known access pattern.

## Example Item

```json
{
  "pk": "JOB#job-001",
  "entity_type": "document_job",
  "job_id": "job-001",
  "status": "processing",
  "request_id": "request-001",
  "correlation_id": "correlation-001",
  "created_at": "2026-07-25T12:00:00+00:00",
  "updated_at": "2026-07-25T12:00:01+00:00",
  "attempts": 1,
  "active_attempt_id": "attempt-001",
  "active_attempt_started_at": "2026-07-25T12:00:01+00:00",
  "active_attempt_lease_expires_at": "2026-07-25T12:05:01+00:00",
  "processing_result": null,
  "error_reason": null
}
```

## Intentionally Deferred

The following concerns are deferred until a concrete access pattern requires them:

```text
Global secondary indexes
Sort keys
Job-status queries
Tenant-level partitioning
Time-to-live attributes
Event-sourcing history
Separate result entities
Table streams
```

This keeps the initial model aligned with the system's current responsibilities while preserving room for future evolution.