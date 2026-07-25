# ADR-003: Use an Explicit Composition Root

## Status

Accepted

## Context

CloudDoc has separate layers for:

```text
domain behavior
application services
repository contracts
DynamoDB persistence
runtime infrastructure adapters
```

Future Lambda handlers need concrete application services.

Without a centralized composition boundary, each handler could independently construct:

```text
runtime settings
boto3 resources
DynamoDB table references
repositories
clocks
identifier generators
application services
```

That would duplicate wiring, increase configuration drift, and couple transport code to infrastructure construction.

The project needs one clear location where abstract dependencies are connected to concrete implementations.

## Decision

Use an explicit composition root implemented with ordinary Python functions and constructor injection.

The composition root builds concrete repositories and application services from validated runtime settings.

Initial composition functions are:

```text
build_document_job_repository
build_create_document_job_service
build_get_document_job_service
```

The runtime package owns this composition.

Application services do not import or depend on the runtime package.

## Configuration

`RuntimeSettings` loads required environment configuration.

Current required setting:

```text
CLOUDDOC_JOBS_TABLE_NAME
```

Invalid configuration fails during startup composition.

AWS credentials remain outside application settings and are resolved through the standard boto3 credential chain.

## Dependency Construction

The creation use case is assembled as:

```text
RuntimeSettings
    ↓
boto3 DynamoDB resource
    ↓
DynamoDBDocumentJobRepository
    ↓
CreateDocumentJob
       ├── SystemClock
       └── UUIDJobIdGenerator
```

The query use case is assembled as:

```text
RuntimeSettings
    ↓
boto3 DynamoDB resource
    ↓
DynamoDBDocumentJobRepository
    ↓
GetDocumentJob
```

## Consequences

### Positive

- Dependency construction is centralized.
- Handlers remain focused on transport concerns.
- Application services remain independent of AWS.
- Runtime configuration is validated consistently.
- The dependency graph is explicit and easy to review.
- Unit tests can replace AWS construction with a fake resource factory.
- No dependency-injection framework is required.
- Future runtime concerns have one controlled integration point.

### Negative

- Composition functions must be updated when constructors change.
- Multiple service builders may currently construct separate repository instances.
- Object lifetime is not yet centralized.
- Some tests inspect private service dependencies to verify wiring.
- The runtime package becomes a required coordination point for new adapters.

These costs are accepted because they preserve clarity and avoid hidden framework behavior.

## Alternatives Considered

### Construct dependencies directly in Lambda handlers

Rejected because it would duplicate wiring and couple handlers to boto3, table names, repositories, and infrastructure adapters.

### Use a dependency-injection framework

Deferred because the current dependency graph is small and static.

A framework would introduce registration configuration, lifecycle semantics, and indirection without solving a current problem.

### Use a service locator

Rejected because dependencies would become implicit and application code could retrieve infrastructure globally.

Constructor injection keeps dependencies visible.

### Use module-level global services immediately

Deferred because object lifetime should be decided when Lambda bootstrap behavior is introduced.

The current composition functions remain explicit and easy to test.

### Pass concrete repositories directly into handlers from tests only

Rejected as the primary design because production still needs a consistent construction path.

The composition root provides one production and testable wiring boundary.

### Let application services load environment variables

Rejected because configuration and infrastructure construction are runtime responsibilities.

Application services should depend only on typed contracts and values supplied through constructors.

## Object Lifetime

The initial decision is to construct new instances when a composition function is called.

A future Lambda bootstrap module may cache composed services at module load time to reuse SDK resources and reduce repeated cold-start work.

That future cache should remain outside application services.

## Failure Behavior

Invalid runtime configuration raises:

```text
RuntimeConfigurationError
```

during startup.

AWS SDK construction failures are allowed to surface from composition.

Application execution errors remain represented by application-layer errors.

This separation distinguishes:

```text
startup configuration failure
runtime infrastructure construction failure
use-case execution failure
```

## Testing Strategy

Composition is unit tested with a fake boto3-style resource factory.

Tests verify:

```text
DynamoDB service selection
configured table selection
repository construction
creation service construction
query service construction
clock adapter selection
identifier generator selection
absence of real AWS access
```

Repository behavior is tested separately through repository contract tests and Moto-backed integration tests.

## Security Considerations

The table name comes from trusted runtime configuration rather than request input.

AWS permissions should be provided through a least-privilege Lambda execution role.

The composition root does not load, expose, or persist AWS secret values.

## Operational Considerations

The explicit composition root will be the integration point for future:

```text
structured logging adapters
metrics clients
tracing
SDK retry configuration
timeouts
client reuse
cold-start initialization
```

Those concerns will be introduced through dedicated decisions rather than added opportunistically to handlers.

## Follow-up Work

- Add Lambda bootstrap modules that compose services during cold start.
- Reuse composed SDK resources across invocations where appropriate.
- Add API Gateway handlers.
- Add structured logging and correlation context propagation.
- Add S3 and Bedrock adapters through the same composition boundary.
- Define least-privilege IAM through infrastructure as code.