# Presigned S3 Upload Flow

## Purpose

CloudDoc creates document jobs together with short-lived S3 upload instructions.

The upload flow lets clients place one source document into the server-owned object location associated with a job without exposing AWS credentials or allowing arbitrary S3 keys.

## Flow

```text
client
    → POST /jobs
    → CreateDocumentJob
    → generate job_id
    → derive canonical object key
    → generate presigned S3 PutObject URL
    → persist pending_upload job
    → return job and upload instructions
```

The client then uploads the document directly to S3 using the returned URL and required headers.

## Creation Response

```json
{
  "job": {
    "job_id": "job_5f68f94b5c664ae3bdfdd013231c06a7",
    "status": "pending_upload",
    "request_id": "request-001",
    "correlation_id": "correlation-001",
    "created_at": "2026-07-25T12:00:00Z",
    "updated_at": "2026-07-25T12:00:00Z",
    "attempts": 0,
    "error_reason": null
  },
  "upload": {
    "method": "PUT",
    "url": "https://example-presigned-url",
    "headers": {
      "content-type": "text/plain"
    },
    "object_key": "documents/job_5f68f94b5c664ae3bdfdd013231c06a7/source.txt",
    "expires_in_seconds": 900
  }
}
```

## Upload Contract

The V1 upload contract is intentionally narrow.

```text
HTTP method: PUT
content type: text/plain
source filename: source.txt
default expiration: 900 seconds
```

The client must upload with the exact signed content type:

```text
Content-Type: text/plain
```

A different content type may invalidate the signature.

## Canonical Object Key

Each job owns one canonical source object:

```text
documents/{job_id}/source.txt
```

Example:

```text
documents/job_5f68f94b5c664ae3bdfdd013231c06a7/source.txt
```

The server derives this key from the generated job identifier.

The client does not provide:

```text
bucket name
object key
prefix
filename
content type
expiration
```

## Application Boundary

The application layer depends on:

```text
DocumentUploadProvider
```

The contract exposes:

```python
def create_upload(
    *,
    job_id: str,
) -> PresignedDocumentUpload: ...
```

The application service does not import boto3 or S3 exceptions.

Provider failures are represented by:

```text
DocumentUploadProviderError
```

and translated into:

```text
ApplicationDependencyError
```

## Infrastructure Adapter

`S3PresignedDocumentUploadProvider` implements the application port.

It signs:

```text
S3 operation: PutObject
bucket: runtime-configured
key: server-derived
content type: text/plain
expiration: runtime-configured
HTTP method: PUT
```

The adapter does not create the S3 object. It creates a temporary signed request.

## Runtime Configuration

Required:

```text
CLOUDDOC_DOCUMENTS_BUCKET_NAME
```

Optional:

```text
CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS
```

Default expiration:

```text
900
```

The expiration value must be a positive integer.

AWS credentials remain under the standard boto3 credential chain and Lambda execution role.

## Failure Ordering

CloudDoc generates upload instructions before persisting the job.

```text
generate job_id
generate upload instructions
construct job
persist job
return response
```

### Presigning Failure

```text
upload provider fails
    → no job is persisted
    → ApplicationDependencyError
```

This avoids an orphan pending job with no usable upload instructions.

### Persistence Failure After Presigning

```text
presigning succeeds
repository write fails
    → job is not persisted
    → unused presigned URL expires naturally
```

A presigned URL does not create an object by itself. An object appears only if the client successfully uses the URL.

This is an accepted V1 trade-off because the URL is short-lived and the job remains the authoritative workflow record.

## Data Ownership

DynamoDB owns job lifecycle state.

S3 owns the uploaded source document.

The relationship is derived through:

```text
job_id
    → documents/{job_id}/source.txt
```

The application does not persist the bucket name in the public job response.

## Security Considerations

The design prevents clients from selecting arbitrary S3 keys.

The presigned request is limited by:

```text
specific bucket
specific object key
specific HTTP method
specific content type
short expiration
```

The response does not expose AWS credentials.

Future infrastructure must apply least-privilege permissions so the signing Lambda may generate uploads only for the approved bucket and object prefix.

## Testing Strategy

Unit tests verify:

```text
canonical object-key construction
fixed PUT method
fixed text/plain content type
expiration validation
provider contract compatibility
configured bucket and expiration
SDK error translation
invalid presigned URL rejection
bucket metadata not exposed
application failure ordering
wrapped create-job response
runtime composition
```

Moto-backed integration tests verify that boto3 generates an S3 Signature Version 4 URL scoped to the expected bucket, object key, expiration, and signed headers.

## Intentionally Deferred

```text
S3 event handling
SQS publication
processor Lambda
Bedrock processing
multipart uploads
multiple files per job
document replacement
object versioning
antivirus scanning
content-length enforcement
tenant-specific prefixes
bucket lifecycle rules
Terraform and IAM
```

These concerns will be introduced after the upload contract and asynchronous processing flow are designed.