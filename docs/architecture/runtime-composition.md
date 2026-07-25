# Runtime Composition

## Purpose

CloudDoc centralizes runtime dependency construction in an explicit composition root.

The runtime layer is responsible for assembling concrete adapters and application services without introducing transport behavior.

Current runtime composition connects:

```text
RuntimeSettings
boto3 DynamoDB resource
DynamoDBDocumentJobRepository
SystemClock
UUIDJobIdGenerator
CreateDocumentJob
GetDocumentJob
```

## Package Structure

```text
src/clouddoc/
├── infrastructure/
│   ├── __init__.py
│   ├── clock.py
│   └── identifiers.py
└── runtime/
    ├── __init__.py
    ├── settings.py
    └── composition.py
```

## Responsibilities

The runtime layer is responsible for:

```text
loading validated configuration
constructing AWS resources
selecting concrete adapter implementations
assembling application services
failing fast on invalid startup configuration
keeping handlers free from dependency wiring
```

It is not responsible for:

```text
API Gateway event parsing
Lambda response construction
HTTP status mapping
business-rule decisions
domain transitions
repository implementation details
structured logging policy
```

## Runtime Settings

`RuntimeSettings` loads and validates the configuration required by the running application.

Current setting:

```text
CLOUDDOC_JOBS_TABLE_NAME
```

The loader rejects:

```text
missing values
empty values
whitespace-only values
```

The settings object is immutable after creation.

### Credential Resolution

CloudDoc does not load AWS credentials into `RuntimeSettings`.

Credential resolution remains the responsibility of the standard boto3 provider chain and the Lambda execution role.

The runtime layer therefore avoids storing or passing:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
```

as application settings.

## Concrete Infrastructure Adapters

### SystemClock

`SystemClock` implements the application `Clock` port.

It returns:

```text
timezone-aware UTC datetime
```

using:

```python
datetime.now(UTC)
```

This keeps runtime timestamps compatible with the domain's UTC invariants.

### UUIDJobIdGenerator

`UUIDJobIdGenerator` implements the application `JobIdGenerator` port.

Generated identifiers follow:

```text
job_<uuid4 hex>
```

Example:

```text
job_5f68f94b5c664ae3bdfdd013231c06a7
```

The prefix improves readability in logs, errors, and persistence keys while the UUID remains opaque.

## Composition Functions

### build_document_job_repository

Constructs:

```text
boto3 DynamoDB resource
configured table reference
DynamoDBDocumentJobRepository
```

Input:

```text
RuntimeSettings
optional DynamoDB resource factory
```

The optional factory allows unit tests to inspect composition without network access.

### build_create_document_job_service

Constructs:

```text
DynamoDBDocumentJobRepository
SystemClock
UUIDJobIdGenerator
CreateDocumentJob
```

### build_get_document_job_service

Constructs:

```text
DynamoDBDocumentJobRepository
GetDocumentJob
```

## Dependency Direction

The dependency direction remains:

```text
delivery handler
    ↓
runtime composition
    ↓
application service
    ↓
domain and repository contracts
    ↓
concrete infrastructure adapters
```

Handlers will call composition functions or receive services created by a bootstrap module.

Application services never import the runtime layer.

## Explicit Construction

The composition root uses ordinary Python functions and constructor injection.

It does not use:

```text
dependency-injection container
service locator
global registry
reflection-based wiring
framework-specific injection
```

This keeps the dependency graph visible during code review and straightforward to explain in interviews.

## Testability

The DynamoDB resource factory is injectable:

```python
build_document_job_repository(
    settings=settings,
    dynamodb_resource_factory=fake_factory,
)
```

This allows unit tests to verify:

```text
requested AWS service name
configured table name
repository type
application service type
concrete clock adapter
concrete identifier adapter
```

without:

```text
AWS credentials
network access
Moto
real DynamoDB
```

Repository behavior remains covered separately by Moto-backed integration tests.

## Object Lifetime

Composition functions currently return new instances for each call.

No singleton, cache, or service container is introduced yet.

A future Lambda bootstrap module may create services during cold start and reuse them across invocations.

That decision belongs to the delivery/runtime lifecycle boundary because the consumer determines the desired object lifetime.

## Startup Failure Behavior

Invalid environment configuration raises:

```text
RuntimeConfigurationError
```

during runtime construction.

AWS resource construction failures are allowed to surface during startup composition.

This follows a fail-fast strategy:

```text
invalid configuration
    → fail during cold start

valid configuration with application execution failure
    → application-layer error handling
```

## Handler Expectations

Future handlers should not construct:

```text
boto3 resources
DynamoDB table references
repositories
clocks
identifier generators
application services
```

Instead, handlers should obtain already composed use cases.

This avoids duplicated wiring and inconsistent runtime configuration.

## Security Considerations

The composition root does not accept caller-controlled table names.

The table name is loaded from trusted runtime configuration.

AWS access is governed by the execution role and should be restricted to the required DynamoDB table operations.

Secrets are not stored in application objects.

## Operational Considerations

Centralized composition provides one location for future runtime concerns such as:

```text
client configuration
timeouts
retry settings
structured logger creation
metrics adapters
tracing adapters
cold-start caching
```

These concerns are intentionally deferred until their dedicated slices.

## Intentionally Deferred

The following are intentionally deferred:

```text
Lambda bootstrap caching
API Gateway handlers
S3 clients
Bedrock clients
CloudWatch logging
metrics
distributed tracing
custom boto3 retry configuration
dependency-injection framework
runtime health checks
```

The current composition root is intentionally small and aligned with the dependencies required by the implemented use cases.