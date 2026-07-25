# ADR-005: Use Server-Owned S3 Object Keys

## Status

Accepted

## Context

CloudDoc needs clients to upload source documents directly to S3.

Allowing clients to choose bucket names, object keys, prefixes, filenames, or content types would increase security risk and make downstream event processing unpredictable.

The system requires a deterministic relationship between a document job and its uploaded source object.

## Decision

CloudDoc will derive the S3 object key on the server from the generated job identifier.

The V1 key format is:

```text
documents/{job_id}/source.txt
```

The client receives a presigned `PutObject` URL for that exact object.

The signed request requires:

```text
HTTP method: PUT
content type: text/plain
short expiration
```

The client cannot choose the bucket, key, filename, content type, or expiration.

## Rationale

A deterministic object key provides:

```text
clear ownership
predictable S3 event routing
simple job-to-object lookup
reduced input surface
consistent downstream processing
easier IAM scoping
```

The canonical key also avoids requiring a separate persisted object-key field in V1 because it can be derived from `job_id`.

## One Source Object per Job

V1 supports one canonical source object:

```text
source.txt
```

This matches the current processing scope of UTF-8 plain-text documents.

Multiple uploads, versions, replacements, and attachments are intentionally deferred until concrete workflows require them.

## Presigning Order

Upload instructions are generated before the job is persisted.

```text
generate job ID
derive object key
generate presigned URL
persist job
return response
```

If presigning fails, no job is persisted.

If persistence fails after presigning, the unused URL expires and no S3 object exists unless the client attempts the upload.

This is accepted because DynamoDB remains the authoritative workflow state and the URL is short-lived.

## Consequences

### Positive

- Clients cannot upload to arbitrary keys.
- Every job maps predictably to one source object.
- Downstream processors can derive ownership from the key.
- S3 event filtering can target the `documents/` prefix.
- IAM permissions can be scoped to the approved bucket and prefix.
- The public API remains small.
- Upload behavior is easy to test.
- Bucket configuration remains private.

### Negative

- V1 supports only one source object per job.
- Replacing an uploaded object would overwrite the canonical key unless bucket versioning is enabled.
- The object key currently embeds the job identifier.
- Future tenant isolation may require an additional prefix.
- The key format becomes an operational contract used by S3 event consumers.

These costs are accepted because the current workflow requires one document per job and predictable asynchronous processing.

## Alternatives Considered

### Let the client provide the object key

Rejected because it would allow arbitrary key selection and complicate authorization, event routing, and downstream ownership checks.

### Preserve the original filename

Deferred because the processing workflow does not currently require it.

Original filenames may contain unsafe characters, personally identifying information, or inconsistent extensions.

If original filename metadata becomes useful, it should be stored separately from the canonical object key.

### Generate an unrelated random object key

Rejected for V1 because deterministic job ownership is more useful than an additional opaque identifier.

The job identifier is already opaque and globally unique.

### Persist the object key in DynamoDB

Deferred because the key is fully derivable from the approved format.

Persisting it now would duplicate state and create a synchronization invariant without adding flexibility.

A persisted key may become appropriate if future workflows allow multiple files or versioned uploads.

### Use a presigned POST form

Rejected because the current client contract requires one direct `PUT` with a fixed key and content type.

A POST policy would be useful for browser form constraints or richer policy fields, but it adds complexity not required by V1.

### Upload through the API Lambda

Rejected because proxying document bytes through Lambda increases latency, cost, payload constraints, and memory pressure.

Direct S3 upload keeps the API path focused on authorization and orchestration.

## Security Considerations

The signing identity must have least-privilege permissions scoped to the documents bucket.

The signed request is restricted to:

```text
one bucket
one key
one method
one content type
one expiration window
```

Authentication and authorization are still required before exposing this flow publicly.

Future tenant-aware authorization must ensure callers can create and access only jobs within their tenant.

## Operational Considerations

The object-key format is part of the asynchronous integration contract.

Future S3 events should verify:

```text
expected bucket
documents/ prefix
source.txt suffix
job ID extraction
authoritative job existence
```

An uploaded object without an authoritative job should not enter processing.

Operational metrics should eventually track:

```text
presigning failures
uploads created
uploads completed
expired unused upload instructions
objects without authoritative jobs
```

## Follow-up Work

- Add S3 event ingestion.
- Validate authoritative job ownership before processing.
- Add SQS buffering and retry behavior.
- Add bucket and IAM definitions through infrastructure as code.
- Evaluate bucket versioning and lifecycle expiration.
- Add authentication and tenant-aware prefixes when identity boundaries are introduced.