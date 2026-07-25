# Application Service Boundary

## Purpose

CloudDoc separates application use cases from delivery handlers and infrastructure adapters.

The application layer coordinates:

```text
domain objects
repository contracts
time providers
identifier generators
application-facing response models
error translation
```

It does not contain AWS-specific code, HTTP response construction, Lambda event parsing, or persistence implementation details.

## Responsibilities

The application layer is responsible for:

```text
orchestrating one business use case
constructing domain objects
calling repository contracts
translating known repository failures
returning stable application views
preserving trace context
keeping handlers thin
```

The current application services are:

```text
CreateDocumentJob
GetDocumentJob
```

## Package Structure

```text
src/clouddoc/application/
├── __init__.py
├── errors.py
├── ports.py
├── create_document_job.py
└── get_document_job.py
```

Application-facing response models live separately:

```text
src/clouddoc/schemas/job_views.py
```

## Dependency Direction

The intended dependency direction is:

```text
delivery handlers
    ↓
application services
    ↓
domain and repository contracts
    ↓
infrastructure adapters
```

Application services depend on abstractions such as:

```text
DocumentJobRepository
Clock
JobIdGenerator
```

They do not depend on:

```text
boto3
DynamoDBDocumentJobRepository
API Gateway event shapes
Lambda context objects
HTTP status codes
S3 clients
Bedrock clients
```

## CreateDocumentJob

### Input

```text
CreateDocumentJobCommand
```

Fields:

```text
request_id
correlation_id
```

The caller does not provide:

```text
job_id
status
attempt count
created_at
updated_at
```

Those values are owned by the application and domain.

### Flow

```text
generate job_id
read current UTC time
construct CorrelationContext
construct DocumentJob
persist through DocumentJobRepository
return DocumentJobView
```

### Invariants

The service ensures:

```text
created_at and updated_at use the same clock snapshot
the initial status is pending_upload
attempts start at zero
request_id is preserved
correlation_id is preserved
the domain aggregate does not escape the application boundary
```

### Failure Translation

```text
JobAlreadyExistsError
    → ApplicationConflictError

RepositoryError
    → ApplicationDependencyError
```

The dependency error may include limited operational context such as:

```text
job_id
```

It does not expose boto3 or infrastructure-specific exception structures.

## GetDocumentJob

### Input

```text
GetDocumentJobQuery
```

Fields:

```text
job_id
```

### Flow

```text
read through DocumentJobRepository
translate absence into application not-found
convert DocumentJob into DocumentJobView
return detached view
```

### Failure Translation

```text
missing repository result
    → ApplicationNotFoundError

RepositoryError
    → ApplicationDependencyError
```

## Application Ports

### Clock

```python
class Clock(Protocol):
    def now(self) -> datetime: ...
```

The clock is injected so application tests remain deterministic and production code does not scatter direct `datetime.now()` calls.

Implementations must return timezone-aware UTC datetimes.

### JobIdGenerator

```python
class JobIdGenerator(Protocol):
    def generate(self) -> str: ...
```

Identifier generation is injected so the application service owns identity creation without coupling itself to UUID or another concrete strategy.

## DocumentJobView

`DocumentJobView` is the stable application representation of a job.

Current fields:

```text
job_id
status
request_id
correlation_id
created_at
updated_at
attempts
error_reason
```

The view is immutable and detached from the domain aggregate.

This prevents callers from invoking lifecycle transitions or relying on private aggregate state.

## Why the Processing Result Is Not Exposed Yet

The current view focuses on job lifecycle and traceability.

The AI extraction result is intentionally deferred from this contract because the public result shape should be designed together with the query API, response versioning, and authorization rules.

This avoids coupling the external contract prematurely to the internal provider output.

## Error Boundary

Application errors provide a stable vocabulary for delivery adapters:

```text
ApplicationConflictError
ApplicationNotFoundError
ApplicationDependencyError
```

A future HTTP handler may translate them into transport semantics without importing repository errors.

Example:

```text
ApplicationNotFoundError
    → HTTP 404

ApplicationConflictError
    → HTTP 409

ApplicationDependencyError
    → HTTP 503 or internal failure policy
```

The application layer itself does not decide HTTP status codes.

## Testing Strategy

Application services are tested with:

```text
InMemoryDocumentJobRepository
fixed clock doubles
fixed identifier generators
repository failure doubles
application-facing assertions
```

Tests verify:

```text
deterministic time
deterministic identity
trace-context propagation
repository interaction effects
error translation
detached response views
absence of domain mutation during queries
```

DynamoDB integration is not required for application-service unit tests because persistence behavior is covered separately by repository contract and integration tests.

## Handler Expectations

Future handlers should be responsible only for:

```text
parsing transport input
extracting or generating request metadata
constructing application command or query objects
calling one application service
mapping application results to transport responses
mapping application errors to transport errors
```

Handlers must not:

```text
construct DocumentJob directly
import DynamoDBDocumentJobRepository as business logic
perform lifecycle transitions
translate botocore exceptions
generate persistence condition expressions
return mutable domain aggregates
```

## Composition Root

Concrete dependencies will be assembled outside the application services.

A future composition root will connect:

```text
DynamoDBDocumentJobRepository
SystemClock
UUIDJobIdGenerator
CreateDocumentJob
GetDocumentJob
Lambda handlers
```

This keeps dependency construction separate from use-case behavior.

## Intentionally Deferred

The following are intentionally deferred:

```text
S3 upload orchestration
presigned URL generation
HTTP request and response schemas
Lambda handlers
dependency-injection framework
authentication and authorization
AI result exposure
pagination and list queries
application-level retries
```

These concerns will be introduced only when their corresponding system boundaries are designed.