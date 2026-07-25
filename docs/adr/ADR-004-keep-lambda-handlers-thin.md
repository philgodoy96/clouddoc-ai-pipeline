# ADR-004: Keep Lambda Handlers Thin

## Status

Accepted

## Context

CloudDoc exposes application use cases through AWS Lambda and API Gateway.

A Lambda handler can easily become responsible for event parsing, trace resolution, domain construction, repository construction, business orchestration, error translation, JSON serialization, and AWS SDK calls.

The project already separates domain behavior, application services, repository contracts, DynamoDB adapters, and runtime composition. The delivery layer should preserve those boundaries.

## Decision

Keep Lambda handlers thin.

Handlers may:

```text
resolve request context
validate transport input
construct application commands or queries
invoke one application service
map application errors
serialize safe transport responses
```

Handlers must not:

```text
construct domain aggregates directly
perform domain transitions
import boto3
construct DynamoDB repositories
build persistence condition expressions
translate botocore exceptions
decide repository semantics
```

## Handler Shape

Each handler provides:

```python
def lambda_handler(event, context): ...
```

and:

```python
def handle(event, context, *, service): ...
```

The Lambda entrypoint obtains the runtime-composed service. The testable `handle()` function accepts an injected application service.

## Runtime Composition

Application services are composed lazily and cached at module scope.

```text
first invocation
    → load runtime settings
    → build application service
    → cache service

warm invocation
    → reuse service
```

Lazy initialization avoids import-time failure in local tooling and unit tests when runtime environment variables are absent.

## Request Context

The delivery layer resolves `request_id` and `correlation_id`.

Request ID precedence:

```text
x-request-id
API Gateway requestContext.requestId
generated request ID
```

Correlation ID precedence:

```text
x-correlation-id
resolved request_id
```

These identifiers are returned in response headers and included in external error payloads.

## Error Boundary

Handlers map application errors to transport semantics:

```text
ApplicationNotFoundError
    → HTTP 404

ApplicationConflictError
    → HTTP 409

ApplicationDependencyError
    → HTTP 503
```

Invalid transport input maps to HTTP 400. Unexpected exceptions map to HTTP 500.

Generic exception handling is allowed only at this outer boundary so internal details are not exposed to clients.

## Consequences

### Positive

- Handlers remain small and reviewable.
- Application services remain reusable outside API Gateway.
- Handler tests do not require AWS access.
- Transport validation is isolated from business rules.
- boto3 and DynamoDB details do not leak into delivery code.
- Error responses remain stable and safe.
- Request and correlation identifiers are consistently propagated.
- Warm invocations can reuse composed services.

### Negative

- Additional delivery helper modules are required.
- Similar handlers may contain small amounts of repeated response mapping.
- Module-level service caching introduces explicit runtime state.
- Structured logging for unexpected failures is not implemented yet.
- Lazy composition means configuration errors surface on first invocation rather than module import.

These costs are accepted because they preserve separation and testability.

## Alternatives Considered

### Put business orchestration directly in handlers

Rejected because handlers would become tightly coupled to domain and persistence behavior.

### Use a web framework

Deferred because the initial API surface contains only two handlers. Adding FastAPI, Mangum, or another framework would introduce routing, middleware, packaging, and lifecycle behavior without solving a current complexity problem.

### Use AWS Lambda Powertools immediately

Deferred until observability requirements are designed. Tools will be introduced for explicit architectural purpose rather than collection.

### Compose services at module import time

Rejected because importing handler modules in local tests or tooling would require runtime configuration and AWS construction immediately.

### Return raw application exceptions

Rejected because internal messages may contain infrastructure details and do not form a stable external contract.

### Return raw domain objects

Rejected because domain aggregates contain lifecycle behavior and internal state.

### Catch all exceptions inside application services

Rejected because broad application-level handling could hide programming defects. Unexpected exceptions are handled only at the external delivery boundary.

## Security Considerations

Handlers treat all API Gateway event fields as untrusted and reject malformed containers, non-string path parameters, blank identifiers, unsupported bodies, caller-controlled lifecycle fields, and unsupported base64 bodies.

Internal exception details are never returned to clients.

Authentication and authorization remain intentionally deferred to a dedicated identity slice.

## Operational Considerations

The delivery boundary already propagates request and correlation identifiers.

A future observability slice should add structured logs, error classification, handler latency metrics, cold-start indicators, dependency failure metrics, and trace propagation.

## Testing Strategy

Unit tests inject service doubles into `handle()` and verify request parsing, validation, trace propagation, success mapping, application error mapping, unexpected exception protection, response serialization, and absence of internal error disclosure.

## Follow-up Work

- Add structured logging for handler execution and failures.
- Add metrics for success, client errors, and dependency errors.
- Add authentication and authorization.
- Add OpenAPI documentation.
- Add infrastructure-as-code definitions for API Gateway and Lambda.
- Add S3 presigned-upload orchestration.