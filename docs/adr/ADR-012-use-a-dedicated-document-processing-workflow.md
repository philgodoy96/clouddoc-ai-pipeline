# ADR-012: Use a Dedicated Application Workflow for Claim-Aware Document Processing

## Status

Accepted

## Context

The uploaded-document processor originally coordinated only processing-start authorization and bounded document retrieval.

Adding AI-provider invocation introduced additional responsibilities:

- acquire authoritative processing ownership
- interpret continuation outcomes
- build a document object reference
- load and validate document text
- construct an AI-provider request
- propagate authoritative correlation context
- invoke the provider
- translate normalized failures
- return a validated workflow result

Keeping all of this logic inside an infrastructure adapter would mix application orchestration with delivery adaptation.

The Processor Lambda must remain unaware of application results, provider implementations, storage clients, and processing-attempt details.

CloudDoc also uses at-least-once SQS delivery. Duplicate messages must not perform S3 reads or AI inference unless the current worker owns the authoritative processing attempt.

## Decision

CloudDoc will use a dedicated application workflow:

```text
ProcessUploadedDocument
```

The workflow will coordinate:

```text
StartDocumentProcessing
    ↓
DocumentTextLoader
    ↓
AIProvider
    ↓
DocumentProcessingResult
```

The workflow will:

1. request processing ownership
2. stop immediately for `EFFECT_ALREADY_APPLIED`
3. require an owned `ProcessingAttempt` and authoritative `correlation_id`
4. retrieve the validated document only after claim acquisition
5. build `AIProviderRequest` from application-owned data
6. invoke the provider abstraction
7. return an explicit validated workflow result

The infrastructure adapter:

```text
ApplicationUploadedDocumentProcessor
```

will only:

- delegate to `ProcessUploadedDocument`
- translate known `ApplicationError` values
- preserve `process(...) -> None`

The Processor Lambda will continue depending only on the `UploadedDocumentProcessor` protocol.

The runtime composition root will inject `MockAIProvider` as the default provider for this slice and will support a replaceable provider factory.

## Decision Details

### Explicit continuation authority

A claim-acquired processing-start result carries:

```text
ProcessingAttempt
correlation_id
```

An already-applied result carries neither.

This prevents duplicate deliveries from receiving authority that belongs to another worker.

### Explicit workflow result

`ProcessUploadedDocument` returns:

```text
DocumentProcessingResult
```

with:

```text
PROCESSED
EFFECT_ALREADY_APPLIED
```

A processed result includes:

```text
ProcessingAttempt
AIExtractionResult
```

An already-applied result includes neither.

The result is internal to the application and infrastructure composition. It does not cross the Lambda delivery contract.

### Provider independence

The application workflow depends on `AIProvider`, not Amazon Bedrock.

Provider-specific concerns remain outside the workflow:

- SDK requests
- model identifiers
- authentication
- throttling headers
- provider response envelopes
- transport retries

### Deterministic provider first

`MockAIProvider` is the default runtime provider for this incremental slice.

This validates the workflow before introducing cloud-provider variability and inference cost.

Amazon Bedrock remains the planned production provider.

## Consequences

### Positive

- Application orchestration has one explicit owner.
- The infrastructure adapter remains narrow.
- The Lambda handler remains unchanged.
- Duplicate events are suppressed before S3 retrieval.
- Duplicate events are suppressed before AI invocation.
- Correlation context comes from the authoritative job.
- Provider requests include the owned processing-attempt ID.
- AI-provider implementations remain replaceable.
- Application tests can run without AWS.
- Runtime composition remains injectable and deterministic.
- Validated extraction results are represented explicitly.
- Future completion and failure persistence have a clear orchestration boundary.

### Negative

- The workflow introduces another application type and result contract.
- The application service coordinates multiple collaborators.
- Private object-graph inspection remains useful in composition tests until dedicated graph-inspection helpers are justified.
- Provider failures are not yet classified into retryable and terminal application outcomes.
- The workflow currently returns a result that the delivery adapter intentionally discards.
- Durable job completion remains incomplete.

### Transitional reliability consequence

A retrieval or provider failure occurs after the worker acquired a processing claim.

Until attempt-aware failure transitions are implemented, a redelivery may observe the active claim and return `EFFECT_ALREADY_APPLIED`.

This means the redelivery can be acknowledged without repeating the failed effect, leaving the job in `processing`.

The system therefore does not yet guarantee eventual DLQ delivery for failures that occur after claim acquisition.

This is accepted only as an incremental implementation state. Attempt-aware failure handling is the next required reliability slice.

## Alternatives Considered

### Keep orchestration in the infrastructure adapter

Rejected.

The adapter would own claim decisions, storage retrieval, provider requests, provider invocation, and error translation. That would blur application and infrastructure responsibilities and make future completion logic harder to test and explain.

### Invoke the provider directly from the Lambda handler

Rejected.

The handler would become coupled to processing attempts, provider contracts, result schemas, and application errors. It would no longer be a thin SQS partial-batch boundary.

### Place orchestration inside the AI provider

Rejected.

A provider should translate between the application provider contract and one inference implementation. It should not acquire processing claims, load S3 objects, or control job-state transitions.

### Persist completion in the same slice

Deferred.

Successful completion requires an attempt-aware conditional write and a clear strategy for stale workers, write conflicts, and retry behavior. Combining orchestration extraction, AI invocation, and durable completion in one change would make the reliability boundary harder to review.

### Integrate Amazon Bedrock immediately

Deferred.

The current engineering objective is to validate workflow ownership and application boundaries. Bedrock-specific IAM, model configuration, payload mapping, throttling, and cost controls will be introduced after failure and completion semantics are safe.

### Return `None` directly from the application workflow

Rejected.

An explicit result preserves the distinction between:

```text
the current worker completed retrieval and inference
another delivery already applied or owns the effect
```

It also provides the attempt and validated extraction required by future durable completion.

## Follow-Up Decisions

The next reliability work must define:

- retryable claim release
- terminal failure persistence
- stale-attempt rejection
- completion persistence
- behavior when the lease expires during inference
- failure behavior when a conditional state write is rejected
- reconciliation for stale `processing` jobs

A later ADR should document the Bedrock adapter, model selection, prompt versioning, and provider-specific resilience policy.