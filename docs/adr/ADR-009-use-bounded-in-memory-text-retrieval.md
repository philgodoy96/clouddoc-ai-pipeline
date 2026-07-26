# ADR-009: Use Bounded In-Memory Retrieval for Initial Text Documents

## Status

Accepted

## Context

CloudDoc must retrieve uploaded source documents from Amazon S3 before invoking an AI provider.

The initial workflow supports UTF-8 `text/plain` documents.

The retrieval design must prevent:

```text
unbounded Lambda memory usage
arbitrary bucket access
processing a replaced object silently
accepting unsupported content
feeding invalid text to the AI boundary
leaking AWS SDK types into the application layer
```

The project also needs a retrieval contract that can evolve independently from Processor Lambda orchestration and AI execution.

## Decision

CloudDoc will load the complete initial text document into memory through a bounded application-layer contract.

The application port is:

```text
DocumentTextLoader
```

The AWS adapter is:

```text
S3DocumentTextLoader
```

The configured maximum size is:

```text
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

with an initial default of:

```text
65536 bytes
```

The bucket is supplied by trusted runtime configuration.

The caller supplies only the expected object identity:

```text
object_key
expected_size_bytes
expected_etag
version_id
```

## Retrieval Rules

The adapter will:

```text
reject known oversized event metadata before GetObject
request the configured bucket only
include VersionId when present
validate ContentLength
require ContentType == text/plain
normalize and compare ETag
validate VersionId when present
read at most max_size_bytes + 1 bytes
require body length to match ContentLength
decode the complete body as strict UTF-8
close the response body
```

The adapter returns an immutable `LoadedTextDocument`.

## Error Normalization

Storage failures are translated into application-owned errors:

```text
DocumentNotFoundError
DocumentValidationError
DocumentDependencyError
```

AWS SDK exceptions do not cross into the application layer.

Missing objects are distinct from invalid content and storage dependency failures.

## Why In-Memory Retrieval

The initial document size is deliberately small and bounded.

Loading the complete body simplifies:

```text
strict UTF-8 validation
byte-length verification
future prompt construction
deterministic testing
failure classification
```

At 64 KiB, the memory profile is explicit and acceptable for the intended first workflow.

This is not a general recommendation for all document-processing systems.

## Why Max Plus One

Calling an unbounded body read would depend entirely on metadata correctness.

The adapter therefore reads:

```text
configured maximum + 1 byte
```

The extra byte acts as an overflow sentinel.

This provides a final defensive check even if response behavior or metadata is inconsistent.

## Why Validate Event Identity

An S3 notification describes an object observed at a point in time.

The current object at the same key may later be replaced.

CloudDoc compares:

```text
expected size
expected ETag
expected version when available
```

against the retrieved object.

A stale event must not silently process different content.

Version-aware reads provide the strongest identity when bucket versioning is enabled.

For events without a version ID, size and ETag still detect replacement.

## Why the Bucket Is Not in the Application Reference

Allowing callers to supply a bucket would turn the loader into a generic S3 fetch capability.

CloudDoc owns one configured document bucket for this workflow.

Keeping the bucket in runtime configuration supports:

```text
least-privilege IAM
clear data ownership
predictable cost boundaries
simpler security review
```

## Why Require Canonical text/plain

The initial ingestion contract supports one media type:

```text
text/plain
```

CloudDoc does not infer format from file extension or content.

It also does not accept charset parameters in this first contract.

The body is always decoded explicitly as strict UTF-8, so one canonical media type avoids metadata ambiguity.

## Consequences

### Positive

- Lambda memory usage is bounded.
- Oversized event metadata can fail before an S3 request.
- Body reads remain bounded even if metadata is inconsistent.
- Replaced objects are detected through identity validation.
- Versioned events retrieve the exact object version.
- Invalid UTF-8 never reaches the AI boundary.
- AWS SDK types remain inside infrastructure.
- The bucket cannot be selected by untrusted event data.
- Unit and integration tests remain deterministic and offline.
- The composition root remains explicit and injectable.

### Negative

- The complete supported document is held in memory as bytes and text.
- Documents larger than the configured limit are rejected.
- `text/plain; charset=utf-8` is rejected despite being semantically compatible.
- Metadata mismatches become terminal validation errors.
- Version-aware retrieval depends on bucket versioning and IAM permissions.
- The adapter performs a single bounded read rather than incremental decoding.
- This decision does not address parsing, chunking, or large-document workflows.

These costs are accepted because the initial workflow prioritizes explicit resource bounds and reliable document identity.

## Alternatives Considered

### Unbounded `StreamingBody.read()`

Rejected because it trusts metadata and permits uncontrolled memory consumption.

### Stream directly into the AI provider

Rejected because the system must validate size, object identity, media type, and UTF-8 before crossing the AI boundary.

It would also couple storage transport to provider invocation.

### Incremental UTF-8 decoding

Deferred because the initial 64 KiB limit makes complete bounded decoding simpler and easier to verify.

Incremental decoding becomes relevant for larger document policies.

### Use S3 Select

Rejected because the source is plain text, not a queryable structured-object workflow.

It would add service-specific complexity without improving the current contract.

### Store document content in DynamoDB

Rejected because DynamoDB owns workflow state, while S3 owns uploaded document bytes.

Mixing content into the job item would blur data ownership and introduce item-size pressure.

### Trust only the object key

Rejected because the content at a key can be replaced.

Size, ETag, and version identity protect against stale-event processing.

### Accept any `text/*` media type

Rejected because different text media types carry different semantic and parsing expectations.

The first workflow intentionally supports only canonical plain text.

### Reject empty documents in the loader

Rejected because zero-byte text is structurally valid storage content.

Whether empty text is useful belongs to the processing use case, not the storage adapter.

## Runtime Composition

The loader is built through:

```text
build_document_text_loader
```

using:

```text
RuntimeSettings.documents_bucket_name
RuntimeSettings.max_document_size_bytes
an injectable S3 client factory
```

The builder does not read the environment or cache the adapter.

## Workflow Integration Decision

This ADR does not connect retrieval to the Processor Lambda.

Processing-start currently treats both a newly acquired claim and an already-applied duplicate as successful outcomes without returning a continuation decision.

Retrieval must not begin until the workflow can distinguish:

```text
this worker acquired ownership
another worker already owns or completed the effect
```

A following decision will define the continuation contract before S3 retrieval enters the processing path.

## Operational Considerations

The configured maximum should eventually be observed through:

```text
oversized document count
content-type rejection count
identity mismatch count
UTF-8 rejection count
S3 latency
S3 dependency failure rate
retrieved bytes
```

The default may be adjusted only with consideration for:

```text
Lambda memory
provider context limits
AI input cost
expected business document size
processing timeout
```

## Security Considerations

The Processor Lambda role should eventually receive read access only to:

```text
the configured document bucket
the server-owned document key prefix
required object versions
```

Document content must not be written to application logs.

The adapter validates metadata and content before returning text to future AI orchestration.

## Follow-up Work

- Introduce an explicit processing-start continuation outcome.
- Load the document only for the worker that owns the active attempt.
- Classify retrieval failures into retryable release or terminal failure.
- Add AI-provider invocation.
- Persist results using active attempt identity.
- Add structured logs and metrics.
- Add IAM and Terraform definitions.
- Evaluate larger-document parsing and chunking separately.