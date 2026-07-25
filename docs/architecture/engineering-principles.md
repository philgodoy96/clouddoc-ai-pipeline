# Engineering Principles

## Purpose

This document defines the public engineering principles that guide the design and implementation of CloudDoc AI Pipeline.

These principles apply to application code, AWS integrations, infrastructure, tests, documentation, and operational behavior.

They are intended to keep the system understandable, reviewable, secure, and reliable as the repository evolves.

## Architecture Principles

### Make system boundaries explicit

The codebase must reflect the responsibilities defined by the architecture.

Business rules, AWS adapters, persistence implementations, AI providers, and runtime handlers must remain distinguishable.

### Prefer a modular serverless application

The project uses multiple AWS runtimes but remains one cohesive application.

Microservices, container orchestration, and distributed service boundaries must not be introduced without a concrete operational requirement.

### Keep runtime handlers thin

Lambda handlers are infrastructure adapters.

A handler should:

1. receive the AWS event
2. normalize external data
3. bind execution context
4. resolve application dependencies
5. invoke one application use case
6. map the result back to the runtime contract

Handlers must not become the primary location for business rules.

### Depend inward

Domain and application code must not depend on AWS event formats or boto3 response structures.

Allowed dependency direction:

```text
Lambda adapters
      ↓
Application services
      ↓
Domain rules and interfaces
      ↓
AWS-specific implementations
```

Domain modules must not import:

* boto3
* Lambda event types
* API Gateway payloads
* SQS message structures
* Bedrock SDK responses
* Terraform concepts

### Add abstractions only for real boundaries

Interfaces should isolate meaningful external dependencies or architectural responsibilities.

Approved examples include:

* AI provider
* document job repository
* document storage

Generic abstractions without clear ownership must be avoided.

## Serverless Design Principles

### Keep synchronous work bounded

The API path must remain limited to:

* input validation
* identifier generation
* job persistence
* pre-signed URL generation
* status retrieval

Document processing and model inference must remain asynchronous.

### Design for ephemeral execution

Lambda execution environments are disposable.

Application correctness must not depend on:

* local in-memory state
* persistent local disk
* one warm runtime
* one invocation processing a message only once

### Make timeouts part of the design

Lambda timeout, provider timeout, SQS visibility timeout, and processing lease duration must be configured together.

The system must avoid conditions where a queue message becomes visible while a valid worker is still processing it.

### Protect downstream services

Processor concurrency must be bounded deliberately to protect:

* Bedrock quotas
* DynamoDB write capacity
* Lambda account concurrency
* model inference cost

## Event-Driven Design Principles

### Assume at-least-once delivery

S3 notifications, SQS delivery, and Lambda event processing may repeat.

Duplicate events are normal and must not be treated as exceptional infrastructure behavior.

### Separate events from business state

Queue messages describe work that should be attempted.

DynamoDB stores the authoritative current job state.

A queue message must not be trusted as proof that a job is still eligible for processing.

### Normalize external events at the boundary

AWS event envelopes must be converted into internal application event models.

Application services must not traverse deeply nested SQS and S3 dictionaries.

### Distinguish notification from work

Services must be selected according to delivery semantics and consumer needs.

The use of an event-driven architecture does not imply that every event belongs on EventBridge.

Durable processing work belongs in a work queue when buffering, backpressure, and retry ownership are required.

## Job State Principles

### Persist only meaningful states

A lifecycle state should exist because it provides business or operational value.

The system must not add infrastructure solely to persist every conceptual moment in a workflow.

### Enforce transitions conditionally

State transitions that coordinate processing must use DynamoDB conditional writes.

Blind updates are not acceptable for:

* processing claims
* terminal completion
* retry release
* dead-letter reconciliation

### Treat terminal states as immutable

Ordinary duplicate delivery must not move `succeeded`, `failed`, or `dead` jobs back into active processing.

Manual replay, if introduced, must be an explicit operational capability.

### Use bounded processing leases

The `processing` state must include an expiration rule.

A worker crash or timeout must not permanently block the job.

## Idempotency and Retry Principles

### Design idempotent effects

The system does not assume exactly-once execution.

Repeated delivery must not create inconsistent business outcomes.

### Acquire ownership before expensive work

The processor must successfully claim the job before:

* retrieving complete document content
* invoking Bedrock
* performing other expensive side effects

### Do not retry terminal input errors

Unsupported or permanently invalid input must fail once and be acknowledged.

Examples include:

* unsupported content type
* invalid encoding
* oversized document
* invalid controlled object key

### Retry transient dependencies within bounds

Temporary AWS or provider failures may be retried through SQS.

Retries must remain bounded to prevent:

* infinite model cost
* repeated poison-message execution
* unbounded log volume
* hidden operational incidents

### Preserve exhausted work

Messages that exhaust retry policy must be retained in a DLQ.

The related job must be reconciled into a truthful terminal state.

### Document non-atomic external work

A Bedrock inference call and a DynamoDB write do not share one transaction.

The system must not claim exactly-once inference.

Partial-failure behavior must be tested and documented.

## AI Integration Principles

### Treat model output as untrusted

Model responses are external input.

A provider request completing successfully does not make its result valid.

### Validate output inside the application

Every AI result must pass application-owned validation.

Validation must cover:

* required fields
* supported document types
* confidence range
* key-field shape
* human-review flag
* summary limits
* serialized result size

### Centralize provider access

Bedrock calls must remain inside the Bedrock provider implementation.

Application services and Lambda handlers must not construct Bedrock requests directly.

### Preserve provider independence at application boundaries

The application-facing provider contract must not expose raw boto3 or Bedrock response objects.

Provider-specific errors must be mapped into normalized application errors.

### Keep mock behavior deterministic

Automated tests must use a deterministic mock provider.

The mock provider must support:

* valid results
* transient failures
* invalid result payloads
* predictable assertions

Automated tests must not require real Bedrock calls.

### Avoid unnecessary provider expansion

The provider abstraction exists for boundary isolation and deterministic testing.

Additional production AI providers must not be introduced without a real product or resilience requirement.

## Data and Persistence Principles

### Model DynamoDB from access patterns

The table design must begin with documented reads and writes.

The initial primary access pattern is:

```text
Get one job by job_id.
```

Indexes must not be added speculatively.

### Use explicit repository operations

Repository methods must represent real state transitions and access patterns.

Preferred examples:

```text
create_job
get_job
claim_job
complete_job
fail_job
release_retryable_claim
mark_dead
```

Generic CRUD repositories should be avoided when they hide conditional or event-driven behavior.

### Keep document bytes out of DynamoDB

S3 owns source document content.

DynamoDB owns workflow state and bounded validated results.

### Bound result size

The application must ensure that stored results remain comfortably below DynamoDB item-size constraints.

Large future results should be stored in S3 and referenced from the job record.

### Preserve normalized failures

Persistent failure information must be safe, stable, and useful.

Raw exception objects and full provider payloads must not be stored.

## S3 Principles

### Keep the bucket private

Public access must remain blocked.

Uploads are authorized through time-limited pre-signed URLs.

### Generate controlled keys

The platform generates object keys based on job identity.

Clients must not choose arbitrary storage paths.

### Validate the uploaded object

The processor must compare actual object metadata against the expected job metadata.

Pre-signed authorization alone does not prove that an object is valid for processing.

### Restrict supported inputs

Content type, encoding, and size limits must be enforced before inference.

### Apply deliberate retention

S3 lifecycle rules must reflect cost and operational requirements.

Documents must not be retained indefinitely by accident.

## SQS and DLQ Principles

### Use the queue as a buffer

SQS separates document arrival from processor capacity.

It is not the authoritative job database.

### Begin with small batches

V1 begins with batch size one to make processing behavior and cost attribution easier to understand.

Batch size may increase only after correctness and observability are established.

### Use partial batch responses

Record-level failures must not cause successful records in the same batch to be retried.

### Align visibility and runtime timeouts

The visibility timeout must exceed the Processor Lambda timeout with a deliberate safety margin.

### Keep retries bounded

The queue redrive policy must limit the number of receives.

### Reconcile dead-letter state

The DLQ Reconciler must update the associated job to `dead` conditionally.

The reconciler must not automatically redrive messages.

## Observability Principles

### Use structured logs

Application logs must use consistent JSON fields and stable event names.

Free-form log sentences alone are insufficient for operational analysis.

### Propagate workflow context

Logs should include, when available:

* `job_id`
* `request_id`
* `correlation_id`
* `aws_request_id`
* `processing_attempt_id`
* `event_type`
* `status`
* `error_code`
* `retryable`

### Distinguish identifiers

A request identifier traces one API request.

A correlation identifier traces the full workflow.

An AWS request identifier traces one Lambda invocation.

A processing attempt identifier traces one acquired worker claim.

These identifiers must not be treated as interchangeable.

### Do not log sensitive content

Logs must not include:

* complete documents
* full prompts
* complete raw model responses
* pre-signed URLs
* credentials
* authorization values

### Prefer actionable metrics

Metrics and alarms should reveal conditions that require investigation.

Examples include:

* visible DLQ messages
* elevated processor errors
* increasing queue age
* provider validation failures
* skipped duplicate processing
* job success and failure counts

## Security Principles

### Use least-privilege IAM

Each Lambda function must receive only the permissions required by its responsibility.

API, processor, and DLQ reconciler roles must remain separate.

### Avoid wildcard resource access

IAM policies should scope:

* S3 bucket and prefix
* DynamoDB table
* SQS queue
* DLQ
* approved Bedrock model or inference profile
* CloudWatch resources where practical

Broad administrator-style policies are not acceptable.

### Use IAM roles instead of static credentials

Application code must not contain AWS access keys.

Secrets Manager must not be introduced unless the system has a real secret to manage.

### Encrypt stored data

The S3 bucket must use server-side encryption.

DynamoDB encryption defaults remain enabled.

Customer-managed KMS keys require a specific key-management or compliance reason.

### Keep deployment assumptions documented

Required AWS region, Bedrock model access, account permissions, and runtime configuration must be explicit.

## Cost-Control Principles

### Avoid always-on infrastructure

V1 must not introduce idle compute services without a workload requirement.

### Use mock inference by default in tests

Automated tests must not incur Bedrock model cost.

### Bound input and retry behavior

Document size, provider retries, queue retries, Lambda timeouts, and processor concurrency must be configured deliberately.

### Control logging volume

Logs should provide operational value without storing document payloads or excessively verbose model data.

### Configure retention

CloudWatch log retention and S3 object lifecycle must be set intentionally.

### Make teardown safe and documented

Development infrastructure must be removable through Terraform.

Destructive operations must remain explicit.

## Terraform Principles

### Manage AWS resources through code

Application infrastructure must not depend on undocumented console configuration.

### Keep environments composable

Environment-specific configurations should compose shared modules rather than duplicate large resource definitions.

### Build modules around responsibilities

Terraform modules should represent meaningful infrastructure capabilities.

A module per individual resource is not automatically desirable.

### Validate before applying

Infrastructure changes must pass:

```text
terraform fmt -check
terraform init -backend=false
terraform validate
```

before review.

### Keep state out of Git

Terraform state, plan files, local variable files, and working directories must not be committed.

### Document backend evolution

Local state may be acceptable during initial individual development if it is excluded from Git.

Collaborative or production-style environments require an encrypted remote state backend with locking.

## Testing Principles

### Test behavior at the correct boundary

The project distinguishes:

* unit tests
* integration tests
* contract tests
* deployed-environment validation

### Keep unit tests independent from AWS

Unit tests must not require:

* AWS credentials
* deployed infrastructure
* network access
* real Bedrock calls

### Use deterministic test doubles

Provider, repository, and storage boundaries should use controlled fakes or stubs where appropriate.

### Test failure behavior

The suite must cover more than successful processing.

Important cases include:

* invalid AI output
* unsupported documents
* duplicate messages
* concurrent processing claims
* expired processing leases
* retryable provider failures
* terminal input failures
* persistence failure
* dead-letter reconciliation

### Do not overstate emulated integration tests

Tests using emulated AWS services validate application integration behavior.

They do not replace validation against real deployed AWS services.

### Keep fixtures safe

Test documents and event payloads must not contain real confidential information.

## Documentation Principles

### Keep documentation truthful

README and architecture documents must distinguish between:

* implemented capability
* planned capability
* intentionally deferred capability

### Record major decisions

Significant architectural choices should become Architecture Decision Records.

### Separate current design from decision history

Architecture documents describe the current system.

ADRs explain why important decisions were made.

### Treat operations as part of the system

Deployment, troubleshooting, dead-letter handling, cost controls, and teardown must be documented.

## Contribution Principles

### Keep changes focused

Branches, commits, and pull requests should represent one coherent objective.

### Preserve architectural boundaries

New code must follow the dependency direction and component ownership defined in the architecture documentation.

### Run validations before review

Changes should pass the relevant formatting, linting, tests, and Terraform validation commands before a pull request is considered ready.

### Explain trade-offs

Pull requests should document why a change was made and what consequences or deferred work remain.

### Avoid hidden scope expansion

New tools, AWS services, libraries, indexes, and architectural layers require a clear technical purpose.

Technology selection must follow requirements rather than portfolio decoration.
