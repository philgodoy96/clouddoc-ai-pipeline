# Amazon Bedrock AI Provider Integration

## Status

Implemented as an application, runtime-composition, and Terraform infrastructure slice.

The repository now contains:

```text
BedrockAIProvider
runtime provider selection
bounded Bedrock Runtime client configuration
Processor-only Bedrock environment configuration
Processor-only model invocation permission
Bedrock invocation telemetry
deterministic offline provider tests
offline Terraform tests
```

Real AWS inference and end-to-end deployment validation remain separate delivery work.

## Purpose

CloudDoc processes uploaded UTF-8 text documents through an application-owned AI provider contract.

This integration connects the deployed Document Processor to Amazon Bedrock without allowing provider-specific request formats, response formats, SDK exceptions, or IAM details to leak into the application workflow.

The integration is responsible for:

```text
selecting the production AI provider
building a non-streaming Bedrock Converse request
treating document content as untrusted data
requiring one strict JSON response
validating the response as AIExtractionResult
normalizing provider and SDK failures
bounding SDK retry and timeout behavior
granting least-privilege model invocation access
preserving deterministic local and automated testing
```

It is not responsible for:

```text
document-job state ownership
processing-claim acquisition
SQS delivery or redrive
document retrieval from S3
application result persistence
CloudWatch dashboards
model-quality evaluation
RAG
agents
tool calling
human-review workflow
```

## Processing Architecture

```text
SQS processing delivery
        │
        ▼
Processor Lambda
        │
        ├── acquire authoritative DynamoDB processing claim
        ├── load bounded UTF-8 source document from S3
        │
        ▼
ProcessUploadedDocument
        │
        ├── construct AIProviderRequest
        │
        ▼
AIProvider
        │
        ├── MockAIProvider
        │       └── local development and automated tests
        │
        └── BedrockAIProvider
                ├── build Converse request
                ├── invoke configured model
                ├── require completed assistant text response
                ├── parse strict JSON
                ├── validate AIExtractionResult
                └── normalize provider failures
        │
        ▼
ProcessUploadedDocument
        │
        ├── valid result
        │       └── conditionally persist authoritative completion
        │
        ├── deterministic invalid response
        │       └── conditionally persist terminal failure
        │
        └── retryable dependency failure
                ├── conditionally release owned claim
                └── return record failure to SQS
```

Only a worker that owns the current processing attempt may reach document loading or model invocation.

## Application-Owned Provider Boundary

The workflow depends on:

```text
AIProvider
```

The application request is:

```text
AIProviderRequest
├── document_text
├── correlation_id
└── processing_attempt_id
```

The application result is:

```text
AIExtractionResult
├── document_type
├── summary
├── key_fields
├── confidence
└── requires_human_review
```

The application does not depend on:

```text
boto3 Bedrock clients
Converse request dictionaries
Converse response dictionaries
Bedrock exception types
Botocore exception types
model-specific response schemas
IAM policy documents
```

This keeps the application workflow stable while provider-specific translation remains inside `BedrockAIProvider`.

## Runtime Provider Selection

Runtime settings expose:

```text
CLOUDDOC_AI_PROVIDER
CLOUDDOC_BEDROCK_MODEL_ID
CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS
CLOUDDOC_BEDROCK_TEMPERATURE
```

Supported providers are:

```text
mock
bedrock
```

The local default is:

```text
CLOUDDOC_AI_PROVIDER=mock
```

A missing provider setting therefore preserves:

```text
local development
unit tests
integration tests
offline workflows
zero Bedrock inference cost
zero real model requests
```

The deployed Processor Lambda receives:

```text
CLOUDDOC_AI_PROVIDER=bedrock
CLOUDDOC_BEDROCK_MODEL_ID=amazon.nova-micro-v1:0
CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS=1200
CLOUDDOC_BEDROCK_TEMPERATURE=0.00001
```

Create Job, Get Job, and Dead-Letter Reconciler do not receive these settings.

## Explicit Injection Precedence

The runtime composition boundary preserves explicit provider injection.

Precedence is:

```text
explicit ai_provider_factory
        → use the injected provider

no explicit factory
        → select provider from RuntimeSettings
```

Consequences:

```text
tests can inject deterministic providers
tests do not construct Bedrock clients accidentally
Bedrock settings do not override an explicit test dependency
production composition remains configuration-driven
```

Runtime composition performs no inference.

It only constructs the object graph.

## Model Decision

The selected v1 production model is:

```text
amazon.nova-micro-v1:0
```

The current document boundary supports only:

```text
content type = text/plain
encoding = UTF-8
maximum size = 65,536 bytes
```

The current AI tasks are:

```text
document classification
concise summarization
bounded key-field extraction
confidence estimation
human-review recommendation
```

Nova Micro aligns with this text-only workload and the project's cost-aware serverless posture.

Multimodal model capability is not required by the current input contract.

## Why the Model ID Is Not a Runtime Default

The Python runtime does not infer or hard-code a production model ID.

Behavior is:

```text
mock selected + model ID absent
        → valid

bedrock selected + model ID absent
        → RuntimeConfigurationError
```

Terraform explicitly selects Nova Micro for the deployed Processor.

This separates:

```text
application configuration contract
from
environment deployment decision
```

Direct dataclass construction is also checked defensively by runtime composition before a Bedrock client is created.

## Bedrock API Decision

The provider uses:

```text
bedrock-runtime.converse
```

The request is synchronous and non-streaming.

The integration does not use:

```text
InvokeModel request payloads
ConverseStream
InvokeModelWithResponseStream
Agents
Knowledge Bases
Flows
batch inference
provisioned throughput
```

Converse provides one normalized interface while the application remains isolated from the transport structure.

## Bedrock Runtime Client

Runtime composition creates:

```python
Config(
    connect_timeout=3,
    read_timeout=40,
    retries={
        "mode": "standard",
        "total_max_attempts": 2,
    },
)
```

The client is created as:

```text
boto3.client("bedrock-runtime", config=...)
```

The runtime does not pass:

```text
static AWS credentials
custom endpoint URL
explicit region override
streaming configuration
```

AWS credentials and Region are resolved through the standard SDK provider chain and the Lambda execution environment.

## Retry Budget

There are two retry layers with different responsibilities.

```text
Botocore standard retry
        → short transport or service recovery
        → two total SDK attempts

SQS redelivery
        → workflow-level retry
        → new processing attempt after safe claim release
```

The Processor Lambda timeout remains:

```text
120 seconds
```

The initial Bedrock client budget is:

```text
connect timeout = 3 seconds
read timeout = 40 seconds
total SDK attempts = 2
```

This leaves runtime budget for:

```text
error normalization
conditional claim release
terminal failure persistence
structured operational handling
Lambda response completion
```

These are initial bounded values.

They require deployed latency evidence before future adjustment.

## Inference Configuration

Configured inference values are:

```text
max output tokens = 1,200
temperature = 0.00001
topP = omitted
streaming = disabled
```

The runtime contract accepts:

```text
max output tokens = 1 through 5,000
temperature = finite value from 0.00001 through 1.0
```

Invalid values are rejected.

The runtime does not:

```text
clamp values
replace invalid values silently
accept NaN
accept positive or negative infinity
accept temperature zero
```

The low temperature is intended to reduce output variance.

The system does not claim absolute determinism.

## Prompt Trust Boundary

The provider sends a system instruction that defines:

```text
CloudDoc extraction role
document content as untrusted data
supported document types
required JSON-only response
prohibition of Markdown and commentary
required result fields
```

The document is placed only in the user message:

```text
<untrusted_document>
{document_text}
</untrusted_document>
```

The provider instructs the model not to follow:

```text
commands in the document
role changes in the document
alternative schemas in the document
requests for credentials
requests for unrelated output
```

Prompt separation reduces risk.

It does not eliminate prompt injection.

The stronger controls are architectural:

```text
no tools
no external actions
no arbitrary AWS access
no secret access
strict response parsing
application-owned validation
bounded document size
least-privilege IAM
no raw response persistence before validation
```

## Converse Request Contract

The provider sends:

```text
modelId
system
messages
inferenceConfig.maxTokens
inferenceConfig.temperature
requestMetadata.correlation_id
requestMetadata.processing_attempt_id
```

The provider does not send:

```text
topP
tool configuration
streaming configuration
guardrail configuration
provider-managed prompt identifier
document location
S3 credentials
DynamoDB identifiers
```

The request metadata carries stable operational identifiers without including document content.

## Response Envelope Contract

The provider accepts only:

```text
response envelope is an object
stopReason = end_turn
output exists
one assistant message exists
message role = assistant
exactly one content block exists
the content block contains exactly one text field
text is non-empty
```

The provider rejects:

```text
missing output
missing message
non-assistant role
zero content blocks
multiple content blocks
non-text content
empty text
unexpected stop reason
max_tokens
guardrail intervention
content filtering
malformed response envelope
```

A non-`end_turn` stop reason is not accepted because the response may be incomplete, transformed, or otherwise unsafe to persist as an authoritative result.

## Strict JSON Contract

The provider applies:

```text
assistant text
        → json.loads
        → require JSON object
        → AIExtractionResult.model_validate
```

The parser rejects:

```text
Markdown code fences
leading commentary
trailing commentary
JSON arrays
JSON scalar values
duplicate object keys
NaN
positive infinity
negative infinity
malformed JSON
```

The provider does not:

```text
search for the first opening brace
strip Markdown fences
remove unknown fields
coerce strings into numbers
coerce strings into booleans
repair malformed JSON
retry with a repair prompt
```

An incompatible response is evidence of an invalid provider result.

It is not silently transformed into valid application data.

## Application Validation

`AIExtractionResult` remains authoritative.

The application contract enforces:

```text
known top-level fields only
supported document types only
non-empty bounded summary
confidence from 0 through 1
strict boolean human-review flag
bounded key-field entry count
JSON-compatible nested values
bounded list sizes
bounded nesting depth
bounded serialized result size
```

A successful Bedrock API call is not a successful document job.

The candidate output must:

```text
parse successfully
validate successfully
be accepted by the current processing attempt
persist through an authoritative conditional state transition
```

## Native Structured Output Decision

The current implementation does not use Bedrock-native structured outputs.

Nova Micro does not provide that capability for this integration, and the application contract contains validation rules beyond simple transport shape.

The selected boundary is:

```text
prompt-constrained JSON
+
strict JSON parsing
+
application-owned Pydantic validation
```

This preserves provider independence and keeps domain acceptance rules inside the application.

A future transport-specific schema may be evaluated only if:

```text
the selected model supports the feature
the schema can represent the required contract
the additional provider coupling has measurable value
application validation remains authoritative
```

## Provider Error Taxonomy

Botocore and Bedrock exceptions do not cross the provider boundary.

Normalized errors are:

```text
AIProviderTimeoutError
AIProviderThrottledError
AIProviderUnavailableError
AIProviderConfigurationError
AIProviderInvalidResponseError
```

### Timeout

Examples include:

```text
ConnectTimeoutError
ReadTimeoutError
ModelTimeoutException
request timeout error codes
```

Behavior:

```text
normalize as AIProviderTimeoutError
release owned processing claim
return record failure
allow SQS retry
```

### Throttling

Examples include:

```text
ThrottlingException
TooManyRequestsException
ServiceQuotaExceededException
```

Behavior:

```text
normalize as AIProviderThrottledError
release owned processing claim
return record failure
allow SQS retry
```

### Temporary unavailability

Examples include:

```text
EndpointConnectionError
ConnectionClosedError
ServiceUnavailableException
InternalServerException
ModelNotReadyException
ModelErrorException
unclassified Botocore transport failure
```

Behavior:

```text
normalize as AIProviderUnavailableError
release owned processing claim
return record failure
allow SQS retry
```

### Configuration or authorization failure

Examples include:

```text
missing or partial credentials
credential retrieval failure
parameter validation failure
AccessDeniedException
ExpiredTokenException
InvalidSignatureException
ResourceNotFoundException
UnauthorizedException
UnrecognizedClientException
ValidationException
```

Behavior:

```text
normalize as AIProviderConfigurationError
treat as an operational dependency failure
release owned processing claim
allow bounded queue redelivery and eventual DLQ handling
```

A configuration failure does not become a terminal document failure.

The document is not invalid merely because the deployment is misconfigured.

### Invalid provider response

Examples include:

```text
invalid response envelope
unexpected stop reason
empty text
invalid JSON
duplicate JSON keys
non-object JSON
schema validation failure
```

Behavior:

```text
normalize as AIProviderInvalidResponseError
persist terminal invalid-response failure for the owned attempt
acknowledge the queue record after authoritative persistence
```

Repeating the same unmodified model request is not assumed to repair a structurally invalid result.

## Data Ownership

```text
Amazon S3
        → source document bytes

DynamoDB
        → authoritative DocumentJob state
        → processing attempt ownership
        → validated bounded result
        → normalized failure state

Amazon SQS
        → delivery
        → retry
        → dead-letter preservation

Amazon Bedrock
        → transient managed inference

BedrockAIProvider
        → provider request and response translation

AIExtractionResult
        → application-owned candidate result contract

CloudWatch
        → operational metadata without document content
```

The provider does not become a state owner.

## IAM Boundary

Only the Processor role receives Bedrock model invocation permission.

The dedicated policy is:

```text
data.aws_iam_policy_document.processor_bedrock_invoke
aws_iam_role_policy.processor_bedrock_invoke
```

The action is exactly:

```text
bedrock:InvokeModel
```

The resource is exactly:

```text
arn:${partition}:bedrock:${region}::foundation-model/amazon.nova-micro-v1:0
```

The ARN is:

```text
partition-aware
regional
accountless for the foundation-model resource
model-specific
free of wildcards
```

The policy does not grant:

```text
bedrock:*
bedrock:InvokeModelWithResponseStream
bedrock:ApplyGuardrail
bedrock:GetFoundationModel
bedrock:ListFoundationModels
bedrock:CreateModelInvocationJob
foundation-model/*
Resource = *
```

No Bedrock permission is granted to:

```text
Create Job Lambda
Get Job Lambda
Dead-Letter Reconciler Lambda
API Gateway
S3
SQS
DynamoDB
```

The shared application package may contain the provider code.

IAM determines which runtime may produce a valid Bedrock external effect.

## Model Access Boundary

Terraform manages:

```text
Processor runtime environment
exact model invocation IAM permission
```

Terraform does not manage:

```text
Marketplace purchase
account-wide model enablement
long-lived Bedrock API keys
console users
provisioned throughput
cross-region inference profiles
```

Model availability and account access in the selected Region remain deployment prerequisites.

## Logging Boundary

The provider emits one terminal structured event per `extract` call:

```text
ai_provider.invocation_completed
```

Success is emitted only after `AIExtractionResult` validation succeeds.

Safe metadata may include:

```text
provider_name
model_id
correlation_id
processing_attempt_id
provider_request_id
stop_reason
input_tokens
output_tokens
total_tokens
duration_ms
provider_latency_ms
normalized provider outcomes
provider_error_code
exception_type
retryable
```

`duration_ms` is wall-clock time around the extract attempt. `provider_latency_ms` is taken from provider response metadata when present and finite. Malformed metadata is tolerated by omission rather than failure.

Normalized outcomes include success and provider failure categories such as:

```text
succeeded
timed_out
throttled
unavailable
configuration_error
invalid_response
internal_error
```

Logger failure is isolated and cannot change the provider outcome.

It must not log:

```text
document_text
full system prompt
full user prompt
raw model response
summary
key_fields
presigned upload URL
AWS credentials
authorization values
```

Bedrock model invocation logging remains disabled because content capture is outside the current privacy boundary.

Detailed contracts are documented in [CloudWatch Observability](cloudwatch-observability.md) and [ADR-024](../adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md).

## Reliability Invariants

```text
Only the claim-owning worker may invoke Bedrock.

The local default provider remains mock.

The deployed Processor selects Bedrock.

Explicit provider injection has precedence over configured composition.

Only the Processor role may invoke the selected model.

No wildcard Bedrock permission exists.

The model response is always untrusted input.

No model result is accepted before application validation.

No result is persisted before attempt ownership is checked.

Transient provider failures release the owned claim.

Invalid model output is terminal for the current job attempt.

Configuration failures remain operational dependency failures.

Malformed JSON is never repaired silently.

Document content is never logged by the provider.

The system does not claim exactly-once inference.
```

## Concurrency and Cost Position

The processing event source mapping uses:

```text
batch size = 1
maximum event-source concurrency = 5
```

The approximate maximum Bedrock concurrency originating from this queue is therefore five, subject to Lambda and service behavior.

Cost controls include:

```text
Nova Micro
text-only input
65,536-byte document limit
1,200 output-token limit
low temperature
batch size one
maximum event-source concurrency five
two total SDK attempts
three SQS receives before DLQ
mock provider for automated tests
no streaming
no provisioned throughput
no model fallback
no cross-region inference profile
```

The project accepts a bounded duplicate-inference risk.

Inference and DynamoDB persistence do not share one atomic transaction.

If inference succeeds and authoritative persistence fails, a later processing attempt may invoke the model again.

## Automated Testing

Provider tests use an injected fake Bedrock Runtime client.

They verify:

```text
request construction
model and inference parameter propagation
system and document separation
request metadata propagation
successful result validation
strict response-envelope behavior
strict JSON behavior
duplicate-key rejection
non-standard-number rejection
application schema rejection
timeout mapping
throttling mapping
unavailability mapping
configuration mapping
absence of real AWS calls
```

Runtime composition tests verify:

```text
mock default
fresh provider construction
configured Bedrock selection
bounded Botocore Config
bedrock-runtime service selection
model configuration propagation
unsupported-provider rejection
missing-model rejection before client construction
explicit provider-factory precedence
offline composition
ai_provider.invocation_completed telemetry
logger failure isolation
```

Terraform tests verify:

```text
Processor-specific Bedrock environment
exact selected model
bounded inference values
exact foundation-model ARN
Processor-only policy attachment
bedrock:InvokeModel as the only action
absence of streaming permission
absence of wildcard actions and resources
absence of Bedrock configuration on other Lambdas
absence of Bedrock permissions in existing business policies
```

Automated tests do not invoke Amazon Bedrock.

## Failure Modes

### Bedrock model ID missing

Runtime startup fails with `RuntimeConfigurationError`.

No Bedrock client is created.

### Unsupported AI provider

Runtime startup fails instead of falling back silently.

### AWS credentials unavailable

The provider normalizes the failure as configuration-related.

The workflow follows the dependency-failure path.

### Processor role lacks permission

Bedrock returns an authorization failure.

The provider normalizes it as `AIProviderConfigurationError`.

### Model unavailable in the configured Region

Invocation fails as a configuration or availability problem depending on the service response.

Deployment preflight and smoke validation must diagnose the account and Region prerequisite.

### Provider throttling

The claim is released conditionally.

SQS may redeliver the message.

### Provider timeout

The claim is released conditionally.

SQS may redeliver the message.

### Response truncated or incomplete

A non-`end_turn` stop reason is rejected.

No candidate result is persisted.

### Response contains malformed JSON

The provider returns `AIProviderInvalidResponseError`.

The workflow persists a terminal invalid-response failure when the current attempt still owns the job.

### Response passes JSON parsing but violates the application schema

The candidate result is rejected before persistence.

### Model invocation succeeds but persistence fails

A later retry may invoke Bedrock again.

The system does not claim exactly-once inference.

## Intentionally Deferred

```text
real AWS inference validation
deployed end-to-end validation
real AWS metric validation
real dashboard inspection
token-to-currency cost attribution
prompt version registry
Bedrock prompt management
native structured outputs
Bedrock Guardrails
PII detection
document redaction
multiple production models
model fallback
automatic model routing
cross-region inference profiles
global inference profiles
application inference profiles
provisioned throughput
streaming inference
batch inference
Bedrock model invocation logging
quality evaluation datasets
RAG
embeddings
vector databases
agents
tool calling
human-review workflow
PDF processing
OCR
Textract
```

These capabilities have separate contracts, failure modes, costs, and validation requirements.

They are not required to establish the current production-provider boundary.

## Validation Commands

```bash
python -m pytest tests/unit/providers/test_bedrock_ai_provider.py -q
python -m pytest tests/unit/runtime/test_settings.py -q
python -m pytest tests/unit/runtime/test_composition.py -q
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform test
make check
make lambda-package-check
git diff --check
```

No AWS credentials or real model invocation are required for this automated validation path.

## Related Documentation

- [System Design](system-design.md)
- [Runtime Composition](runtime-composition.md)
- [Claim-Aware AI Invocation](claim-aware-ai-invocation.md)
- [Attempt-Aware Processing Finalization](attempt-aware-processing-finalization.md)
- [Lambda Runtime Infrastructure](lambda-runtime-infrastructure.md)
- [Processing Queue Consumer Infrastructure](processing-queue-consumer-infrastructure.md)
- [CloudWatch Observability](cloudwatch-observability.md)
- [ADR-023: Use Amazon Nova Micro Through Bedrock Converse](../adr/ADR-023-use-amazon-nova-micro-through-bedrock-converse.md)
- [ADR-024: Use Native AWS Metrics and Structured Application Logs](../adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)
