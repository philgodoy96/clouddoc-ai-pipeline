# S3 Event Ingestion Contract

## Purpose

CloudDoc receives uploaded-document notifications through the following asynchronous path:

```text
S3 ObjectCreated
    → standard SQS queue
    → Processor Lambda
```

This boundary normalizes SQS-wrapped S3 notifications into typed delivery events without performing job lookup, state transitions, document processing, or AI inference.

## Why S3 Publishes Directly to SQS

S3 can publish object-created notifications directly to SQS.

An intermediate Lambda is intentionally avoided because it would add:

```text
an additional runtime hop
another failure boundary
extra deployment and IAM configuration
additional operational cost
duplicate retry semantics
```

The queue provides the decoupling required between upload traffic and processing capacity.

## Delivery Semantics

The queue is a standard SQS queue.

The system therefore assumes:

```text
at-least-once delivery
possible duplicate messages
best-effort ordering
batch delivery
independent retry behavior
```

No exactly-once processing guarantee is inferred from the transport.

## Incoming Event Layers

The Processor Lambda receives an outer SQS batch:

```json
{
  "Records": [
    {
      "messageId": "message-001",
      "body": "{"Records":[...]}"
    }
  ]
}
```

Each SQS `body` contains a serialized S3 notification:

```json
{
  "Records": [
    {
      "eventName": "ObjectCreated:Put",
      "s3": {
        "bucket": {
          "name": "clouddoc-documents"
        },
        "object": {
          "key": "documents%2Fjob-001%2Fsource.txt",
          "size": 128,
          "eTag": "etag-001",
          "sequencer": "0055AED6DCD90281E5"
        }
      }
    }
  ]
}
```

Both layers may contain multiple records.

The parser supports:

```text
N SQS records
    ×
M S3 records per SQS body
```

Input ordering is preserved in the normalized result.

## Normalized Event

A valid notification becomes:

```python
UploadedDocumentEvent(
    message_id="message-001",
    event_name="ObjectCreated:Put",
    bucket_name="clouddoc-documents",
    object_key="documents/job-001/source.txt",
    job_id="job-001",
    object_size=128,
    etag="etag-001",
    sequencer="0055AED6DCD90281E5",
    version_id=None,
)
```

This is a delivery model, not a domain aggregate.

It captures normalized transport and S3 metadata for a future application use case.

## Canonical Document Object Key

The shared document-key contract accepts only:

```text
documents/{job_id}/source.txt
```

Examples:

```text
documents/job-001/source.txt
documents/job_5f68f94b5c664ae3bdfdd013231c06a7/source.txt
```

Rejected examples:

```text
documents/job-001/other.txt
documents/job-001/source.pdf
uploads/job-001/source.txt
documents/source.txt
documents//source.txt
documents/job-001/nested/source.txt
```

The `job_id` must be non-empty and contain no whitespace.

The same contract is used for:

```text
presigned upload generation
S3 event ingestion
job ownership extraction
```

## URL Decoding

S3 notification object keys are URL encoded.

The parser applies semantics equivalent to:

```python
urllib.parse.unquote_plus
```

before canonical-key validation.

For example:

```text
documents%2Fjob-001%2Fsource.txt
    → documents/job-001/source.txt
```

A plus sign is decoded as whitespace:

```text
documents%2Fjob+001%2Fsource.txt
    → documents/job 001/source.txt
```

Because canonical job identifiers reject whitespace, the decoded key is rejected as invalid.

Decoding before validation ensures validation applies to the actual object key rather than its encoded representation.

## Event Name Validation

The parser accepts concrete events in the family:

```text
ObjectCreated:*
```

Examples:

```text
ObjectCreated:Put
ObjectCreated:Post
ObjectCreated:Copy
ObjectCreated:CompleteMultipartUpload
```

It rejects non-creation events such as:

```text
ObjectRemoved:Delete
ObjectRestore:Completed
ReducedRedundancyLostObject
```

The V1 client uses `PutObject`, but accepting the `ObjectCreated` family avoids unnecessary coupling to one S3 creation subtype.

## Bucket Validation

The parser receives the expected bucket explicitly:

```python
expected_bucket_name: str
```

Every S3 record must reference that bucket.

Notifications from another bucket raise:

```text
UnexpectedS3BucketError
```

This is defense in depth against incorrect event-notification or permission configuration.

The parser does not verify bucket existence or call AWS.

## Strict Input Validation

The parser does not silently coerce invalid values.

It requires:

```text
outer event to be an object
Records fields to be non-empty lists
SQS records to be objects
messageId to be a non-empty string
body to be a non-empty JSON string
S3 records to be objects
object size to be a non-negative integer
present optional metadata to be non-empty strings
```

Values such as these are rejected for object size:

```text
true
false
"128"
128.0
null
-1
```

A zero-byte object remains representable at the delivery boundary. A future application use case may reject it according to processing policy.

## Error Taxonomy

All current parser errors describe deterministic payload failures.

```text
EventParsingError
├── MalformedQueueEventError
├── MalformedQueueMessageError
├── MalformedS3NotificationError
├── UnsupportedS3EventError
├── UnexpectedS3BucketError
└── InvalidDocumentObjectKeyError
```

These errors are not classified as transient infrastructure failures.

The future Lambda handler will define whether each message should be retried, acknowledged as permanently invalid, or moved to a DLQ.

## Idempotency Boundary

The normalized event captures:

```text
SQS message ID
bucket
object key
S3 sequencer
ETag
version ID
```

This slice does not define a final idempotency key.

Reasons:

```text
SQS message IDs may change after republication
ETags are not universal event identities
sequencers require an explicit same-key ordering policy
version IDs depend on bucket versioning
the authoritative effect depends on current job state
```

Idempotent processing will be defined with the application use case that starts document processing.

## Data Ownership Validation

The parser extracts `job_id` from the object key but does not query DynamoDB.

A syntactically valid object key does not prove that an authoritative job exists.

The future processor use case must verify:

```text
job exists
job owns the expected object
current job state permits processing
duplicate delivery does not repeat effects
```

## Testing Strategy

Unit tests cover:

```text
one SQS record with one S3 record
multiple SQS records
multiple S3 records per SQS body
input ordering
URL decoding
plus-sign decoding before validation
canonical job-ID extraction
expected bucket enforcement
ObjectCreated event family
unsupported S3 events
malformed outer envelopes
malformed queue records
invalid JSON bodies
malformed S3 notifications
invalid object keys
strict object-size validation
optional S3 metadata
blank optional metadata
blank parser configuration
```

The parser tests require no AWS credentials, boto3 clients, Moto resources, or network access.

## Intentionally Deferred

```text
Processor Lambda handler
partial SQS batch failure responses
DynamoDB job lookup
job state transitions
idempotency implementation
SQS acknowledgement policy
DLQ reconciliation
S3 document download
UTF-8 content validation
AI provider invocation
Terraform
real S3 and SQS resources
```