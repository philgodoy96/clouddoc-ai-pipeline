# API Gateway Delivery Boundary

## Purpose

CloudDoc exposes document-job use cases through AWS Lambda handlers invoked by API Gateway.

The delivery layer translates between transport concerns and application use cases. It does not contain domain rules, persistence logic, or AWS SDK composition.

## Endpoints

```text
POST /jobs
GET /jobs/{job_id}
```

## Responsibilities

The delivery boundary is responsible for:

```text
parsing API Gateway events
resolving request and correlation identifiers
validating transport-level input
constructing application commands and queries
calling application services
mapping application results to HTTP responses
mapping application errors to safe external errors
serializing JSON responses
```

It is not responsible for:

```text
constructing domain aggregates directly
performing domain transitions
calling boto3
building DynamoDB repositories
evaluating persistence conditions
loading AWS credentials
returning internal exception details
```

## Request Identity

Request ID resolution order:

```text
x-request-id header
API Gateway requestContext.requestId
generated req_<uuid4 hex>
```

Correlation ID resolution order:

```text
x-correlation-id header
resolved request_id
```

Headers are normalized case-insensitively. Blank, non-string, or malformed values are ignored.

## Response Identity

Response headers always expose the current request identity:

```text
x-request-id
x-correlation-id
```

For job-query responses, the body may still contain the trace identifiers associated with the original job creation.

```text
response headers
    → current API request

response body
    → persisted job origin context
```

## Response Shape

API Gateway responses use:

```text
statusCode
headers
body
```

The body is always a JSON string and the content type is:

```text
application/json
```

## Error Shape

```json
{
  "error": {
    "code": "job_not_found",
    "message": "Document job was not found.",
    "request_id": "request-001",
    "correlation_id": "correlation-001"
  }
}
```

Error responses do not expose stack traces, exception class names, DynamoDB table names, boto3 payloads, credentials, or raw internal errors.

## Error Mapping

```text
ApplicationNotFoundError
    → 404

ApplicationConflictError
    → 409

ApplicationDependencyError
    → 503

Invalid request shape
    → 400

Unexpected exception
    → 500
```

Generic exception handling exists only at the outer delivery boundary so the API can return a safe response.

## POST /jobs

The current endpoint accepts an absent body, blank body, or empty JSON object.

It rejects malformed JSON, arrays, strings, numbers, null, base64-encoded bodies, non-empty objects, and caller-controlled lifecycle fields.

The handler constructs `CreateDocumentJobCommand` using the resolved request and correlation identifiers.

Successful creation returns:

```text
HTTP 201
```

## GET /jobs/{job_id}

The handler reads:

```text
pathParameters.job_id
```

The value must be a non-empty, non-whitespace string. Surrounding whitespace is removed. Other types are rejected rather than coerced.

The handler constructs `GetDocumentJobQuery`.

Successful retrieval returns:

```text
HTTP 200
```

A missing job returns:

```text
HTTP 404
```

## Handler Structure

Each handler exposes:

```python
def lambda_handler(event, context): ...
```

and:

```python
def handle(event, context, *, service): ...
```

Tests inject application-service doubles into `handle()`.

## Cold-Start Composition

Each handler caches its service in module scope.

```text
first invocation
    → load settings
    → compose service
    → cache service

warm invocation
    → reuse cached service
```

The service is composed lazily rather than at import time, avoiding import failures in local tools and tests without runtime configuration.

## Security Considerations

All event fields are treated as untrusted input.

The handlers validate event containers, path parameters, and request bodies; reject unsupported encodings; avoid arbitrary object serialization; and never expose internal exception details.

Authentication and authorization are intentionally deferred to a dedicated identity boundary.

## Testing Strategy

Tests verify header normalization, trace precedence, generated request identity, safe success and error responses, invalid request handling, path validation, application error mapping, unexpected exception protection, and trace-header propagation.

## Intentionally Deferred

```text
CORS policy
authentication
authorization
OpenAPI specification
API Gateway deployment
Terraform
structured logging
metrics
distributed tracing
S3 presigned uploads
AI result exposure
request throttling
```