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
UUIDProcessingAttemptIdGenerator
S3PresignedDocumentUploadProvider
S3DocumentTextLoader
CreateDocumentJob
GetDocumentJob
StartDocumentProcessing
ProcessUploadedDocument
ReconcileDeadLetteredDocument
MockAIProvider
BedrockAIProvider
ApplicationUploadedDocumentProcessor
ApplicationDeadLetteredDocumentProcessor
```

Control-plane composition builds job creation and query services. Processing-plane composition builds the uploaded-document processor and dead-letter reconciler.

## Package Structure

```text
src/clouddoc/
├── infrastructure/
│   ├── __init__.py
│   ├── clock.py
│   ├── identifiers.py
│   └── ...
└── runtime/
    ├── __init__.py
    ├── settings.py
    └── composition.py
```

## Responsibilities

The runtime layer is responsible for:

```text
loading validated configuration
constructing AWS clients and resources
selecting concrete adapter implementations
selecting the configured AI provider
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
IAM policy enforcement
```

## Runtime Settings

`RuntimeSettings` loads and validates the configuration required by the running application.

Shared application settings:

```text
CLOUDDOC_JOBS_TABLE_NAME
CLOUDDOC_DOCUMENTS_BUCKET_NAME
CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS
CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS
CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES
```

AI provider selector:

```text
CLOUDDOC_AI_PROVIDER
```

Supported values are `mock` and `bedrock`. The local and automated-test default is `mock`.

Conditional Bedrock model setting:

```text
CLOUDDOC_BEDROCK_MODEL_ID
```

Required when `CLOUDDOC_AI_PROVIDER=bedrock`. Absent for the mock provider.

Bounded Bedrock inference settings:

```text
CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS
CLOUDDOC_BEDROCK_TEMPERATURE
```

Defaults are `1200` output tokens and temperature `0.00001`.

The loader rejects:

```text
missing required values
empty values
whitespace-only values
unsupported provider names
missing Bedrock model ID when bedrock is selected
out-of-range inference settings
```

When an explicit environment mapping is supplied, settings are read only from that mapping and do not fall back to `os.environ`.

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

### build_document_upload_provider

Constructs:

```text
boto3 S3 client
S3PresignedDocumentUploadProvider
```

### build_document_text_loader

Constructs:

```text
boto3 S3 client
S3DocumentTextLoader
```

### build_ai_provider

Selects and constructs the configured AI provider.

`mock` selection returns:

```text
MockAIProvider
```

`bedrock` selection constructs:

```text
bedrock-runtime client
bounded botocore Config
BedrockAIProvider
```

Unsupported provider values fail with `RuntimeConfigurationError`.

Missing or empty Bedrock model ID fails defensively with `RuntimeConfigurationError` even if settings construction was bypassed.

### build_create_document_job_service

Constructs:

```text
DynamoDBDocumentJobRepository
S3PresignedDocumentUploadProvider
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

### build_uploaded_document_processor

Constructs:

```text
DynamoDBDocumentJobRepository
StartDocumentProcessing
S3DocumentTextLoader
configured AI provider
ProcessUploadedDocument
ApplicationUploadedDocumentProcessor
```

Provider selection uses an explicit AI provider factory when supplied. Otherwise the builder calls `build_ai_provider` with the configured settings and optional Bedrock client factory.

S3 and Bedrock client factories remain injectable for offline tests.

### build_dead_lettered_document_processor

Constructs:

```text
DynamoDBDocumentJobRepository
ReconcileDeadLetteredDocument
ApplicationDeadLetteredDocumentProcessor
```

## Bedrock SDK Configuration

When Bedrock is selected, composition applies:

```text
connect timeout = 3 seconds
read timeout = 40 seconds
retry mode = standard
total max attempts = 2
```

These values are initial application execution-budget defaults pending deployed measurements.

Deep Bedrock request and response behavior is documented in [Bedrock AI Provider Integration](bedrock-ai-provider-integration.md).

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

Handlers call composition functions through module-scoped warm caches.

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

Injectable boundaries include:

```text
DynamoDB resource factory
S3 client factory
Bedrock runtime client factory
AI provider factory
```

Example:

```python
build_uploaded_document_processor(
    settings=settings,
    dynamodb_resource_factory=fake_dynamodb_factory,
    s3_client_factory=fake_s3_factory,
    ai_provider_factory=lambda: fake_provider,
)
```

This allows unit tests to verify:

```text
requested AWS service names
configured table and bucket names
provider selection
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
real S3
real Bedrock
```

Composition tests remain offline. Repository behavior remains covered separately by Moto-backed integration tests.

## Object Lifetime

Composition functions return new instances for each builder call.

Lambda handlers cache composed services at module scope for warm invocations.

The composition builders themselves do not introduce global caching. Object lifetime remains a delivery/runtime lifecycle concern owned by the handlers.

## Startup Failure Behavior

Invalid environment configuration raises:

```text
RuntimeConfigurationError
```

during runtime construction.

Startup failures include:

```text
unsupported AI provider
missing Bedrock model ID when bedrock is selected
invalid shared application settings
```

AWS resource construction failures are allowed to surface during startup composition.

This follows a fail-fast strategy:

```text
invalid configuration
    → fail during cold start

valid configuration with application execution failure
    → application-layer error handling
```

## Handler Expectations

Handlers should not construct:

```text
boto3 resources
DynamoDB table references
repositories
clocks
identifier generators
AI providers
application services
```

Instead, handlers obtain already composed use cases through the composition root.

This avoids duplicated wiring and inconsistent runtime configuration.

## Security Considerations

The composition root does not accept caller-controlled table names, bucket names, or model identifiers from request payloads.

Those values are loaded from trusted runtime configuration.

AWS access is governed by execution roles. Declared IAM boundaries restrict DynamoDB, S3, and Processor-only Bedrock invocation. Runtime composition itself does not enforce IAM.

Secrets are not stored in application objects.

## Operational Considerations

Centralized composition provides one location for future runtime concerns such as:

```text
structured logger creation
metrics adapters
tracing adapters
runtime health checks
provider client telemetry
```

These concerns are intentionally deferred until their dedicated slices.

## Intentionally Deferred

The following remain intentionally deferred:

```text
CloudWatch logging construction
metrics
distributed tracing
dependency-injection framework
runtime health checks
provider client telemetry
```

The current composition root aligns with the dependencies required by the implemented control-plane and processing-plane use cases.

## Related Documentation

- [Bedrock AI Provider Integration](bedrock-ai-provider-integration.md)
- [Claim-Aware AI Invocation](claim-aware-ai-invocation.md)
- [Lambda Runtime Infrastructure](lambda-runtime-infrastructure.md)
