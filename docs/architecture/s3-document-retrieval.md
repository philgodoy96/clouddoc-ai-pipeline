# Bounded S3 Document Retrieval

## Purpose

CloudDoc retrieves uploaded source documents through an explicit application-layer boundary backed by Amazon S3.

The retrieval boundary is responsible for:

```text
loading one server-owned object from the configured bucket
validating event-derived object identity
enforcing a hard in-memory size limit
requiring canonical text/plain metadata
reading the body with an overflow sentinel
decoding the complete body as strict UTF-8
normalizing S3 failures into application errors
closing the streaming response body
```

This slice intentionally stops at validated text retrieval.

It does not yet:

```text
connect retrieval to the Processor Lambda workflow
invoke the AI provider
construct prompts
persist processing results
complete or fail a ProcessingAttempt
release retryable processing claims
```

## Architecture

```text
DocumentObjectReference
    ↓
DocumentTextLoader
    ↓
S3DocumentTextLoader
    ↓
trusted configured S3 bucket
    ↓
GetObject
    ↓
metadata validation
    ↓
bounded body read
    ↓
strict UTF-8 decoding
    ↓
LoadedTextDocument
```

The application layer owns the storage-neutral contract.

The infrastructure layer owns AWS SDK interaction and response normalization.

The runtime layer composes the adapter with trusted configuration and an injectable S3 client factory.

## Application Contract

### DocumentObjectReference

`DocumentObjectReference` captures the identity expected from the uploaded-document event:

```text
object_key
expected_size_bytes
expected_etag
version_id
```

The reference is immutable.

It requires:

```text
a non-blank object key
a non-negative expected size
a non-blank ETag
a non-blank version ID when present
```

The bucket is deliberately absent.

Callers cannot choose an arbitrary storage location. The bucket comes from trusted runtime configuration.

### LoadedTextDocument

`LoadedTextDocument` represents a fully validated text object:

```text
object_key
content
content_type
size_bytes
etag
version_id
```

It is immutable and guarantees:

```text
content_type == text/plain
size_bytes is non-negative
content can be encoded as strict UTF-8
size_bytes matches the UTF-8 encoded content length
```

### DocumentTextLoader

The application port is synchronous:

```python
class DocumentTextLoader(Protocol):
    def load(
        self,
        *,
        reference: DocumentObjectReference,
    ) -> LoadedTextDocument: ...
```

The contract exposes no boto3 client, S3 response, `StreamingBody`, or botocore exception.

## Trusted Bucket Boundary

`S3DocumentTextLoader` receives:

```text
s3_client
bucket_name
max_size_bytes
```

The bucket name is supplied by runtime composition from:

```text
RuntimeSettings.documents_bucket_name
```

The uploaded-document event contributes the object key and expected identity, but it cannot select the bucket.

This protects the retrieval boundary from becoming a generic object-fetch primitive.

## Maximum Document Size

The runtime setting is:

```text
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

Default:

```text
65536 bytes
```

The default represents 64 KiB.

The value must be a positive base-10 integer.

This initial policy supports:

```text
bounded Lambda memory consumption
bounded prompt construction
predictable provider cost
manageable model context usage
deterministic tests
simple failure classification
```

Larger documents are intentionally deferred until the system introduces explicit parsing, chunking, or an alternative processing path.

## Layered Size Enforcement

The loader enforces size in three stages.

### Event-Derived Size

Before calling S3:

```text
reference.expected_size_bytes
    <=
configured maximum
```

A known oversized event is rejected without consuming an S3 request.

### S3 Metadata Size

After `GetObject`:

```text
ContentLength
    <=
configured maximum
```

This prevents reading an object whose authoritative S3 metadata exceeds the policy.

### Bounded Body Read

The body is read with:

```text
max_size_bytes + 1
```

The additional byte is an overflow sentinel.

```text
returned bytes <= maximum
    → continue validation

returned bytes > maximum
    → reject as oversized
```

The adapter never performs an unbounded `read()`.

## Object Identity Validation

The loader compares the retrieved object against the trusted event reference.

### Size

```text
S3 ContentLength
    ==
reference.expected_size_bytes
```

### ETag

S3 response quotation is normalized before comparison:

```text
response ETag
    ==
reference.expected_etag
```

### Version

When the event supplies `version_id`:

```text
GetObject includes VersionId
response VersionId matches the reference
```

When no version ID is supplied, the loader requests the current object and still validates size and ETag.

This prevents a stale unversioned event from silently processing a replacement object.

## Content-Type Policy

The only accepted media type is:

```text
text/plain
```

The adapter intentionally rejects:

```text
application/json
text/html
text/plain; charset=utf-8
missing content type
```

Using one canonical value keeps the initial ingestion contract deterministic.

Charset parameters are unnecessary because decoding is explicitly enforced as strict UTF-8.

## UTF-8 Validation

After bounded reading and metadata validation, the complete body is decoded with:

```text
utf-8
errors=strict
```

Invalid byte sequences raise `DocumentValidationError`.

The content is not partially decoded or repaired.

Silent replacement characters would weaken document identity and could produce unpredictable AI input.

## Empty Documents

A zero-byte `text/plain` object is structurally valid at the retrieval boundary.

```text
content == ""
size_bytes == 0
```

Whether empty content is meaningful for AI processing belongs to a later application workflow.

This keeps storage validation separate from AI input semantics.

## Error Taxonomy

The application contract defines:

```text
DocumentLoadError
├── DocumentNotFoundError
├── DocumentValidationError
└── DocumentDependencyError
```

### DocumentNotFoundError

Used for normalized missing-object cases:

```text
404
NoSuchKey
NoSuchVersion
NotFound
```

### DocumentValidationError

Used when the object or response violates the trusted retrieval contract:

```text
oversized event metadata
oversized S3 metadata
unsupported content type
size mismatch
ETag mismatch
version mismatch
missing response body
invalid response shape
non-binary body
truncated or inconsistent body size
invalid UTF-8
```

### DocumentDependencyError

Used for storage dependency failures:

```text
S3 throttling
network failure
endpoint failure
SDK transport failure
access failure
unexpected S3 service error
stream read failure
```

This taxonomy allows future orchestration to distinguish terminal input failures from retryable dependency failures without importing AWS-specific exceptions.

## Response-Body Lifecycle

When S3 returns a response body, the adapter closes it in a `finally` block.

Cleanup occurs after:

```text
successful retrieval
metadata validation failure
body read failure
UTF-8 validation failure
```

A body-close exception does not replace a successfully validated result or the primary retrieval failure.

This prevents transport cleanup behavior from obscuring the business outcome.

## Runtime Composition

The runtime builder is:

```python
build_document_text_loader(
    *,
    settings: RuntimeSettings,
    s3_client_factory: S3ClientFactory = boto3.client,
) -> DocumentTextLoader
```

Composition:

```text
RuntimeSettings
    ├── documents_bucket_name
    └── max_document_size_bytes
            ↓
injected S3 client factory
            ↓
S3DocumentTextLoader
```

The builder:

```text
creates one S3 client per call
does not read environment variables
does not cache the loader
does not retrieve an object
does not construct DynamoDB resources
```

The injected factory keeps composition tests offline.

## Current Workflow Boundary

The loader is composed but not yet injected into the Processor Lambda workflow.

That sequencing is intentional.

`StartDocumentProcessing` currently returns no explicit continuation decision. Both of these paths return successfully:

```text
new claim acquired
duplicate already covered by an active claim
```

Connecting retrieval immediately could allow a duplicate delivery without ownership to continue reading and later processing the object.

A following slice must introduce an explicit outcome such as:

```text
claim acquired
effect already applied
```

Only the worker that owns the active attempt should continue into document retrieval and future AI execution.

## Security Considerations

The loader:

```text
uses a runtime-controlled bucket
uses a server-controlled canonical key
does not accept arbitrary S3 URIs
does not expose SDK responses to the application layer
does not log document content
validates metadata before trusting the body
reads with a hard bound
```

Future IAM policy should grant the Processor Lambda only the required object-read actions for the document bucket and relevant key prefix.

Version-aware reads may also require permission for versioned object access.

## Cost Considerations

The 64 KiB default bounds:

```text
S3 data transfer into the Lambda process
Lambda memory used for the raw byte body
UTF-8 text held in memory
future prompt size
future model input cost
```

The implementation performs one `GetObject` request for a valid reference.

Known oversized event metadata is rejected before issuing that request.

Conditional AI cost control remains a later workflow responsibility.

## Testing Strategy

Unit tests cover:

```text
application contract invariants
structural protocol compliance
trusted bucket propagation
version-aware and unversioned requests
bounded max-plus-one reads
metadata validation
ETag normalization
missing objects
SDK dependency failures
stream read failures
body cleanup
invalid UTF-8
empty text
```

Moto-backed integration tests cover:

```text
successful UTF-8 round trip
exact version retrieval
missing keys
content-type rejection
invalid UTF-8
configured size enforcement
stale unversioned event detection
empty text objects
```

All tests use fake credentials or injected clients and do not access AWS.

## Intentionally Deferred

```text
Processor Lambda integration
claim-continuation outcome
S3 retrieval after ownership acquisition
AI-provider invocation
prompt construction
domain-specific empty-document rejection
attempt-aware result persistence
retryable claim release
terminal failure persistence
lease heartbeat or extension
structured document formats
chunking
OCR
structured logging
CloudWatch metrics
IAM policy
Terraform
real AWS integration tests
```