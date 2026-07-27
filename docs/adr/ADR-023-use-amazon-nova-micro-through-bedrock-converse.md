# ADR-023: Use Amazon Nova Micro Through Bedrock Converse

## Status

Accepted

## Context

CloudDoc requires one real production AI provider for its asynchronous document-processing path.

The application workflow already owns:

```text
processing-claim acquisition
bounded document loading
provider-independent request construction
application-owned result validation
attempt-aware successful completion
retryable claim release
terminal failure persistence
```

The workflow depends on the internal:

```text
AIProvider
```

contract rather than a specific model SDK.

The production provider must support:

```text
UTF-8 text-only documents
document classification
concise summarization
bounded key-field extraction
confidence estimation
human-review recommendation
strict application validation
bounded latency and retry behavior
least-privilege IAM
deterministic offline tests
```

The selected integration must not require changes to the application workflow or allow provider-specific exception types to cross the provider boundary.

## Decision

CloudDoc will use:

```text
Amazon Bedrock
Amazon Nova Micro
model ID = amazon.nova-micro-v1:0
Bedrock Converse API
synchronous non-streaming invocation
```

The provider implementation will be:

```text
BedrockAIProvider
```

Local development and automated tests will continue to use:

```text
MockAIProvider
```

The deployed Processor Lambda will select Bedrock through runtime configuration.

## Model Decision

The v1 workload is text-only.

The accepted source contract is:

```text
content type = text/plain
encoding = UTF-8
maximum size = 65,536 bytes
```

The required model tasks are:

```text
classification
summarization
structured field extraction
confidence estimation
human-review recommendation
```

Nova Micro is selected because it aligns with:

```text
text-only input
low-cost serverless inference
low-latency processing posture
bounded JSON response requirements
current classification and extraction scope
```

Multimodal capability is not required by the v1 document boundary.

## Converse API Decision

CloudDoc will use:

```text
bedrock-runtime.converse
```

rather than a model-specific `InvokeModel` request body.

Converse provides a normalized request and response interface while preserving the application-owned provider boundary.

The request will be:

```text
synchronous
non-streaming
one system instruction
one user message
bounded inference configuration
request metadata for correlation
```

The integration will not use:

```text
ConverseStream
InvokeModelWithResponseStream
Agents
Knowledge Bases
Flows
batch inference
```

## Provider Abstraction Decision

Application services will continue to depend on:

```text
AIProvider
```

The Bedrock adapter will own:

```text
Converse request construction
prompt boundary
response-envelope extraction
strict JSON parsing
application schema validation
Botocore error normalization
Bedrock service error normalization
```

The adapter will not own:

```text
DynamoDB job state
SQS retry count
processing-claim acquisition
document retrieval
terminal-state transitions
workflow logging policy
```

## Runtime Selection Decision

Runtime configuration will expose:

```text
CLOUDDOC_AI_PROVIDER
CLOUDDOC_BEDROCK_MODEL_ID
CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS
CLOUDDOC_BEDROCK_TEMPERATURE
```

Supported provider values are:

```text
mock
bedrock
```

The default is:

```text
mock
```

Selecting `bedrock` requires an explicit non-empty model ID.

The Python runtime will not hard-code or infer a default production model ID.

Terraform will select Nova Micro for the deployed Processor Lambda.

## Explicit Injection Decision

An explicitly injected AI-provider factory will have precedence over runtime selection.

```text
explicit factory
        → injected provider

no explicit factory
        → provider selected from RuntimeSettings
```

This preserves:

```text
offline composition tests
deterministic workflow tests
provider substitution
no accidental model calls
```

## Inference Configuration Decision

The deployed configuration will use:

```text
max output tokens = 1,200
temperature = 0.00001
topP = omitted
streaming = disabled
```

The runtime accepts:

```text
max output tokens from 1 through 5,000
finite temperature from 0.00001 through 1.0
```

Invalid values fail configuration validation.

Values are not clamped or silently repaired.

The low temperature is selected to reduce variance for extraction tasks.

CloudDoc does not claim deterministic model output.

## Prompt Boundary Decision

The system instruction will define:

```text
the CloudDoc extraction role
the document as untrusted data
the supported document types
the exact top-level output fields
JSON-only output
no Markdown
no commentary
```

The document text will appear only inside a dedicated user-content boundary:

```text
<untrusted_document>
...
</untrusted_document>
```

The prompt will instruct the model not to follow commands, role changes, schema changes, or unrelated requests contained in the document.

Prompt engineering is not treated as a complete prompt-injection defense.

The stronger controls are:

```text
no tools
no external actions
no secret access
no arbitrary AWS permissions
strict parsing
strict application validation
bounded content
least-privilege IAM
```

## Response Validation Decision

The provider will accept only:

```text
stopReason = end_turn
one assistant message
one content block
one text field
non-empty text
one JSON object
one application-valid AIExtractionResult
```

The provider will reject:

```text
unexpected stop reasons
multiple content blocks
non-text blocks
empty output
Markdown fences
leading commentary
trailing commentary
JSON arrays
JSON scalars
duplicate object keys
NaN
infinity
unknown top-level fields
invalid document types
invalid confidence
invalid boolean values
oversized results
excessive nesting
```

## No Silent Repair Decision

The provider will not:

```text
strip Markdown fences
search for the first JSON object
remove unknown fields
coerce strings into numbers
coerce strings into booleans
repair malformed JSON
issue an automatic repair prompt
```

Malformed or incompatible output will become:

```text
AIProviderInvalidResponseError
```

The application-owned schema remains authoritative.

## Native Structured Output Decision

CloudDoc will not use Bedrock-native structured outputs in this integration.

Nova Micro does not provide that capability for the selected boundary, and the application contract contains validation rules that remain application concerns.

The accepted approach is:

```text
prompt-constrained JSON
+
strict JSON parsing
+
AIExtractionResult validation
```

Native structured outputs may be reconsidered only if:

```text
the selected model supports them
the transport schema represents the required shape
application validation remains authoritative
provider coupling has measurable value
```

## Stop Reason Decision

The only accepted stop reason is:

```text
end_turn
```

Other values are treated as invalid provider responses.

In particular, a token-limit stop may indicate truncation and must not produce a persisted result.

## Error Normalization Decision

The adapter will expose normalized application-facing errors:

```text
AIProviderTimeoutError
AIProviderThrottledError
AIProviderUnavailableError
AIProviderConfigurationError
AIProviderInvalidResponseError
```

Botocore and Bedrock exception types will not cross the provider boundary.

### Retryable dependency failures

Timeout, throttling, temporary network failure, temporary service failure, and model-readiness errors will follow the retryable dependency path:

```text
conditionally release the owned claim
return the SQS record as failed
allow bounded redelivery
```

### Configuration failures

Credential, authorization, invalid static configuration, and missing-model failures will be normalized separately.

They remain operational dependency failures.

They will not become terminal document failures because the document is not invalid when the deployment is misconfigured.

### Invalid model response

A structurally invalid model response will follow the terminal invalid-response path:

```text
conditionally persist terminal failure
acknowledge the SQS record
```

## SDK Timeout and Retry Decision

The Bedrock Runtime client will use:

```text
connect timeout = 3 seconds
read timeout = 40 seconds
retry mode = standard
total SDK attempts = 2
```

`total_max_attempts` is used so the value includes:

```text
initial request
+
one SDK retry
```

The Processor Lambda timeout remains:

```text
120 seconds
```

The SDK budget leaves time for workflow-level error handling and conditional state changes.

SQS redelivery remains a separate workflow-level retry mechanism.

## IAM Decision

Only the Processor Lambda role will receive:

```text
bedrock:InvokeModel
```

The resource will be the exact selected foundation model:

```text
arn:${partition}:bedrock:${region}::foundation-model/amazon.nova-micro-v1:0
```

The ARN will be:

```text
partition-aware
regional
accountless
model-specific
free of wildcards
```

The policy will not grant:

```text
bedrock:*
bedrock:InvokeModelWithResponseStream
foundation-model/*
Resource = *
```

No Bedrock permission will be granted to Create Job, Get Job, Dead-Letter Reconciler, API Gateway, S3, SQS, or DynamoDB.

## Separate IAM Policy Decision

The Bedrock permission will be held in a dedicated Processor inline policy rather than added to the existing DynamoDB and S3 business policy.

This makes the model-invocation capability:

```text
independently reviewable
independently testable
independently removable
clearly scoped to one external effect
```

## Runtime Environment Isolation Decision

The five existing application settings remain shared across all Lambda functions.

Only the Processor receives:

```text
CLOUDDOC_AI_PROVIDER
CLOUDDOC_BEDROCK_MODEL_ID
CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS
CLOUDDOC_BEDROCK_TEMPERATURE
```

Other functions do not need model configuration because they cannot invoke the model.

## Model Access Decision

Terraform will manage:

```text
runtime environment configuration
least-privilege invocation permission
```

Terraform will not manage:

```text
Marketplace purchases
account-wide model access
long-lived Bedrock API keys
provisioned throughput
cross-region inference profiles
```

Model availability and access in the deployment account and Region remain preconditions for deployed validation.

## Data and Logging Decision

Document text and raw model output will not be logged.

Safe future operational fields include:

```text
provider name
model ID
correlation ID
processing-attempt ID
provider request ID
stop reason
token usage
latency
normalized error category
```

The integration will not require:

```text
document text
full prompt
raw response
summary
key fields
presigned URL
credentials
```

for routine diagnostics.

## Offline Test Decision

Provider tests will use an injected fake Bedrock Runtime client.

Runtime composition tests will use an injected Bedrock client factory.

Terraform tests will use a mocked AWS provider and plan-time assertions.

Automated tests will validate:

```text
Converse request contract
prompt separation
strict response parsing
application validation
error taxonomy
runtime provider selection
explicit injection precedence
bounded SDK configuration
Processor-only environment configuration
exact model ARN
exact IAM action
absence of wildcard and streaming permissions
isolation from other Lambdas
```

Automated tests will not:

```text
require AWS credentials
invoke Amazon Bedrock
create AWS resources
incur inference cost
```

## Consequences

### Positive

- The deployed Processor has a real managed AI provider.
- Application services remain independent of Bedrock request and response structures.
- The deterministic mock remains available for local and automated testing.
- Model responses remain untrusted until strict application validation succeeds.
- Prompt and document instructions are separated.
- Malformed JSON is not silently repaired.
- Provider failures have explicit operational categories.
- SDK retries and timeouts are bounded.
- Only the Processor can invoke the selected model.
- IAM targets one exact foundation-model ARN.
- No streaming or wildcard model permission exists.
- Provider selection remains testable through explicit injection.
- The implementation does not require real AWS calls in automated tests.
- The selected model matches the current text-only scope and cost posture.

### Negative

- Prompt-constrained JSON cannot guarantee valid model output.
- Nova Micro does not provide native structured outputs for this integration.
- A model response may still vary at low temperature.
- Configuration failures may consume bounded SQS receives before reaching the DLQ.
- Bedrock model access and regional availability remain external deployment prerequisites.
- Inference and DynamoDB persistence are not one atomic transaction.
- A retry may repeat a successful but unpersisted inference.
- The provider contains model-service-specific error mapping.
- Exact service behavior remains unverified until real AWS deployment.
- The initial timeout budget is not based on deployed latency measurements.
- One fixed production model provides no fallback during a model-specific outage.

## Alternatives Considered

### Continue Using Only MockAIProvider

Rejected for the deployed Processor.

The mock is appropriate for deterministic testing but cannot prove real model integration, IAM, provider error handling, or deployment behavior.

### Amazon Nova Lite

Deferred.

Nova Lite provides capabilities beyond the current text-only input contract.

The current v1 scope does not justify paying for or coupling to unused multimodal behavior.

### A Different Bedrock Foundation Model

Deferred.

The project requires one bounded, cost-aware production model before introducing model comparison, routing, or fallback.

Future model changes remain possible through runtime configuration and the provider boundary.

### InvokeModel With a Model-Specific Payload

Rejected.

A model-specific request body would increase transport coupling.

Converse provides the required synchronous request boundary with a normalized interface.

### ConverseStream

Rejected.

The workflow needs one bounded structured result rather than progressive user-facing output.

Streaming would introduce additional parsing, timeout, partial-output, and IAM concerns without product value in the current asynchronous pipeline.

### Native Bedrock Structured Outputs

Not selected.

The selected model does not provide the required capability for this integration, and application-owned validation must remain authoritative.

### Automatic JSON Repair

Rejected.

Repair heuristics could hide provider-contract failures, alter meaning, coerce unsafe values, and make persisted results harder to defend.

### Retry Invalid Model Output Automatically

Rejected for the current workflow.

Invalid output is treated as a deterministic provider-result failure rather than assumed temporary unavailability.

A future quality-evaluation and repair strategy requires explicit budgets, metrics, and acceptance criteria.

### Treat Configuration Failure as Terminal Document Failure

Rejected.

Deployment configuration is not a property of the document.

Terminally failing jobs would destroy recoverability after IAM or model-access remediation.

### Hard-Code Nova Micro in Python Runtime

Rejected.

The application configuration contract and deployment environment decision remain separate.

Terraform selects the deployed model.

### Grant `bedrock:*`

Rejected.

The Processor requires one external effect against one selected model.

A wildcard would expand blast radius without architectural need.

### Grant `InvokeModelWithResponseStream`

Rejected.

The provider does not stream.

Granting an unused action would violate least privilege.

### Grant Access to `foundation-model/*`

Rejected.

The deployed runtime is approved for one exact model.

Future model changes require an explicit infrastructure review.

### Add Bedrock Permission to the Existing Processor Business Policy

Rejected.

A dedicated policy keeps model invocation independently reviewable and testable.

### Cross-Region Inference Profile

Deferred.

The current slice prioritizes simple regional ownership, data-residency reasoning, IAM scope, failure diagnosis, and cost attribution.

### Provisioned Throughput

Deferred.

The current workload has no measured sustained demand that justifies reserved model capacity.

### Model Fallback

Deferred.

Fallback requires quality equivalence, schema compatibility, routing policy, cost controls, and operational evidence.

### Bedrock Guardrails

Deferred.

Guardrails have independent policy, cost, testing, false-positive, and failure-mode contracts.

The current provider has no tools or external actions and already applies strict application validation.

## Follow-Up Decisions

Future work must define:

```text
deployed Bedrock preflight validation
real AWS smoke inference
model-access readiness checks
CloudWatch provider telemetry
token and cost attribution
provider latency alarms
provider error alarms
prompt version management
model-quality evaluation
Guardrail requirements
PII and redaction requirements
model fallback criteria
cross-region inference requirements
```

Real deployment validation must confirm:

```text
model availability in the selected Region
account access to Nova Micro
exact IAM permission behavior
observed latency against the 40-second read timeout
token usage shape
response validity rate
retry behavior
CloudWatch diagnostic evidence
```