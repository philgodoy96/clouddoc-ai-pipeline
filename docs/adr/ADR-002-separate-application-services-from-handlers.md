# ADR-002: Separate Application Services from Delivery Handlers

## Status

Accepted

## Context

CloudDoc will expose use cases through AWS Lambda and API Gateway.

Without a dedicated application layer, handlers could accumulate responsibilities such as:

```text
parsing events
constructing domain objects
generating identifiers
reading time
calling repositories
translating persistence errors
building responses
deciding lifecycle behavior
```

That design would couple business workflow orchestration to AWS transport details and make use cases harder to test independently.

The project already separates:

```text
domain rules
repository contracts
DynamoDB persistence
AI provider contracts
```

A clear application boundary is needed before delivery adapters are introduced.

## Decision

Implement explicit application service classes for each use case.

Delivery handlers will call application services rather than coordinating domain and repository behavior directly.

Application services depend on protocols and repository contracts, not concrete AWS adapters.

The initial services are:

```text
CreateDocumentJob
GetDocumentJob
```

## Application Contracts

Each use case receives a dedicated immutable input object:

```text
CreateDocumentJobCommand
GetDocumentJobQuery
```

Each use case returns an application-facing view:

```text
DocumentJobView
```

Domain aggregates do not cross the application boundary.

## Dependency Injection

Application services receive dependencies through constructors.

Examples:

```text
DocumentJobRepository
Clock
JobIdGenerator
```

Concrete implementations are assembled later in a composition root.

No dependency-injection framework is introduced.

Constructor injection is sufficient for the current number of dependencies and keeps object construction explicit.

## Error Translation

Known repository failures are translated into application errors:

```text
JobAlreadyExistsError
    → ApplicationConflictError

missing repository result
    → ApplicationNotFoundError

RepositoryError
    → ApplicationDependencyError
```

This prevents delivery handlers from depending on persistence-specific semantics.

The application layer does not translate errors into HTTP status codes. Transport mapping remains the responsibility of the handler layer.

## Consequences

### Positive

- Use cases can be tested without Lambda or API Gateway.
- Application workflows remain independent of boto3.
- Handlers remain small and focused on transport concerns.
- Time and identity generation are deterministic in tests.
- Repository errors do not leak into delivery adapters.
- Domain aggregates are not exposed as response objects.
- Future delivery mechanisms can reuse the same application services.
- Dependency direction is explicit and interview-defensible.

### Negative

- The project gains additional command, query, service, and view types.
- Simple use cases require more files than direct handler-to-repository code.
- Error translation must be maintained across boundaries.
- A composition root will be required to assemble concrete dependencies.

These costs are accepted because they preserve separation as the system grows.

## Alternatives Considered

### Put orchestration directly in Lambda handlers

Rejected because handlers would become coupled to domain construction, repository errors, time, identity generation, and AWS event shapes.

This would make unit testing slower and reduce reuse outside Lambda.

### Use domain objects directly as API responses

Rejected because domain aggregates contain lifecycle behavior and internal state that should not define the external response contract.

A detached immutable view provides a safer boundary.

### Introduce a service framework or dependency-injection container

Deferred because constructor injection is sufficient for the current scope.

A framework would add configuration and indirection without solving a current complexity problem.

### Use free functions instead of service classes

Considered viable, but service classes were selected because they make constructor-injected dependencies explicit and provide a natural unit for composition and testing.

### Catch all exceptions in application services

Rejected because broad exception handling can hide programming defects and weaken failure classification.

Only known repository errors are translated.

### Return `None` for missing jobs

Rejected at the application boundary.

The repository may represent absence with `None`, but the use case requires an explicit not-found outcome.

## Testing Strategy

Application services are verified with isolated unit tests using:

```text
in-memory repository
fixed clock
fixed identifier generator
repository failure doubles
```

Tests cover:

```text
job creation
trace-context propagation
single time snapshot
single identifier generation
detached view creation
not-found translation
conflict translation
dependency failure translation
read-only query behavior
```

Repository and AWS behavior remain covered by separate repository tests.

## Security Considerations

The application layer accepts only the context required by each use case.

It does not accept caller-controlled:

```text
job status
attempt count
creation timestamp
persistence keys
repository conditions
```

Authorization is intentionally deferred to the delivery and identity boundary, but future handlers must perform authorization before invoking application services.

Error context must avoid secrets, document content, credentials, and raw provider responses.

## Operational Considerations

Application errors create stable categories for structured logging and metrics.

Future observability may track:

```text
application conflicts
not-found queries
dependency failures
use-case latency
request_id
correlation_id
job_id
```

Logging implementation is intentionally deferred to the observability slice.

## Follow-up Work

- Add concrete `SystemClock`.
- Add concrete UUID-based job identifier generation.
- Add a composition root for Lambda execution.
- Implement API Gateway request and response mapping.
- Add S3 upload orchestration as a separate application use case.
- Design the external job-result query contract.
- Add structured logging and application metrics.