# ADR-015: Provision Standard Processing Queues with Terraform

## Status

Accepted

## Context

CloudDoc already defines application and delivery boundaries for asynchronous document processing and dead-letter reconciliation.

The repository needs executable infrastructure for:

```text
normal processing delivery
bounded delivery retries
exhausted-message retention
future DLQ reconciliation
```

SQS owns message delivery state.

DynamoDB owns the authoritative `DocumentJob` lifecycle.

The first Terraform infrastructure change must establish this messaging topology without combining S3 notifications, Lambda packaging, IAM, observability, and deployment automation in one large change.

## Decision

CloudDoc will provision two standard Amazon SQS queues with Terraform:

```text
processing queue
processing dead-letter queue
```

The processing queue will use:

```text
fifo_queue = false
delay_seconds = 0
visibility_timeout_seconds = 720
message_retention_seconds = 345600
sqs_managed_sse_enabled = true
```

The processing DLQ will use:

```text
fifo_queue = false
delay_seconds = 0
visibility_timeout_seconds = 180
message_retention_seconds = 1209600
sqs_managed_sse_enabled = true
```

The processing queue will use a dedicated:

```text
aws_sqs_queue_redrive_policy
```

with:

```text
deadLetterTargetArn = processing DLQ ARN
maxReceiveCount = 3
```

The processing DLQ will use a dedicated:

```text
aws_sqs_queue_redrive_allow_policy
```

with:

```text
redrivePermission = byQueue
sourceQueueArns = [processing queue ARN]
```

The Terraform root module will export the name, ARN, and URL of both queues.

The topology will be covered by offline Terraform tests with a mocked AWS provider.

## Standard Queue Decision

The processing queue does not require FIFO ordering.

CloudDoc accepts at-least-once delivery and protects effects through authoritative state transitions, attempt ownership, idempotency, and conditional persistence.

A standard queue also supports the planned direct S3 event-notification path.

Global ordering would add constraints without solving a business requirement in the initial system.

## Retry Decision

The processing queue will move a message to the DLQ after:

```text
3 receives
```

This value provides bounded retry opportunities while preventing poison messages from remaining indefinitely in the source queue.

The value is an infrastructure delivery policy.

It is not a maximum business-processing-attempt policy and does not independently authorize a `DocumentJob` transition to `dead`.

## Visibility Timeout Decision

The processing queue will use:

```text
720 seconds
```

This reserves a future Processor Lambda timeout budget of:

```text
120 seconds
```

with a six-times visibility-timeout margin.

The Processor Lambda is not provisioned in this slice.

Encoding the approved queue timeout now prevents the event-source mapping slice from silently selecting an incompatible delivery timeout.

The DLQ will use:

```text
180 seconds
```

because the future DLQ Reconciler Lambda performs a narrow control-plane operation and does not retrieve document bodies or invoke the AI provider.

## Retention Decision

The source queue will retain messages for:

```text
345600 seconds
4 days
```

The DLQ will retain messages for:

```text
1209600 seconds
14 days
```

The longer DLQ retention preserves more time for operational investigation after delivery exhaustion.

## Encryption Decision

Both queues will enable:

```text
SQS-managed server-side encryption
```

CloudDoc will not introduce a customer-managed KMS key in this slice.

SQS-managed encryption provides encryption at rest while avoiding premature:

- key policies
- KMS IAM permissions
- cross-account key administration
- KMS request costs
- operational key ownership

A customer-managed KMS key remains available when a concrete compliance, cross-account, or ownership requirement exists.

## Redrive Policy Resource Decision

CloudDoc will use the dedicated Terraform resource:

```text
aws_sqs_queue_redrive_policy.processing
```

instead of placing the redrive policy inline on the source queue.

This keeps the queue resource and its delivery relationship explicit and independently testable.

The policy uses:

```text
maxReceiveCount = 3
```

as an integer.

## Redrive Allow Policy Decision

The processing DLQ will restrict eligible source queues through:

```text
redrivePermission = byQueue
```

with exactly one ARN:

```text
aws_sqs_queue.processing.arn
```

CloudDoc will not use:

```text
allowAll
wildcard source permissions
multiple unrelated source queues
```

The allow policy controls which queue may designate the DLQ as its dead-letter destination.

It does not perform automatic replay.

## Naming and Tagging

Queue names will use:

```text
${project_name}-${environment}-processing
${project_name}-${environment}-processing-dlq
```

The environment input is limited to:

```text
dev
staging
prod
```

Shared provider tags identify:

```text
Project
Environment
ManagedBy
Component
```

Queue-specific tags identify:

```text
Name
QueueRole
```

## Outputs

The Terraform root will export:

```text
processing_queue_name
processing_queue_arn
processing_queue_url
processing_dlq_name
processing_dlq_arn
processing_dlq_url
```

These outputs create a stable integration boundary for future S3, Lambda, IAM, and observability resources.

## Offline Test Decision

The queue topology will use Terraform native tests with:

```text
mock_provider "aws"
command = plan
```

The tests will validate resource arguments and relationships without AWS credentials or real resource creation.

The test boundary includes:

- naming
- tagging
- standard queue type
- encryption
- visibility timeouts
- retention
- maximum receive count
- DLQ target
- redrive source restriction
- outputs

Real AWS deployment validation remains separate.

## Terraform State Decision

The initial root will use local Terraform state.

Remote state is intentionally deferred until shared development or automated deployment is introduced.

Terraform state files and local variable files remain excluded from Git.

The dependency lock file remains versioned.

## Consequences

### Positive

- The repository now contains executable infrastructure.
- Processing retries are bounded.
- Exhausted messages have a dedicated retention boundary.
- Both queues are encrypted at rest.
- Queue names are environment-scoped.
- The DLQ is restricted to the approved source queue.
- Queue identifiers are available to future infrastructure slices.
- The topology is testable without AWS credentials.
- The infrastructure history remains small and reviewable.
- Automatic replay is not introduced.
- SQS delivery state remains separate from business lifecycle state.

### Negative

- The queue topology is not yet connected to S3.
- No Lambda consumes either queue yet.
- IAM policies are incomplete until runtime resources exist.
- No CloudWatch alarms monitor queue depth or message age.
- Local state is not suitable for shared or automated deployment.
- The 720-second visibility timeout is coupled to a future 120-second Processor Lambda budget.
- Configuration values are fixed slice invariants rather than tunable variables.

## Alternatives Considered

### Provision Queue, S3, Lambda, IAM, and Observability Together

Rejected.

That would produce a large first infrastructure change with several independent failure domains and review concerns.

The project will introduce infrastructure incrementally.

### Use an SQS FIFO Queue

Rejected.

The application does not require global ordering and already handles at-least-once delivery.

FIFO would also conflict with the planned direct S3 notification topology.

### Use No Dead-Letter Queue

Rejected.

Poison messages could remain in the processing queue indefinitely and operational investigation would have no dedicated retention boundary.

### Use Unlimited or High Retry Counts

Rejected.

Repeatedly processing a deterministic poison message increases cost and delays investigation.

Three receives provide bounded retry behavior for the initial system.

### Use Equal Source and DLQ Retention

Rejected.

Exhausted messages require a longer investigation window than normal processing messages.

### Use a Customer-Managed KMS Key Immediately

Deferred.

No current compliance, ownership, or cross-account requirement justifies the additional policy and operational complexity.

### Allow Any Queue to Use the DLQ

Rejected.

The DLQ belongs to the CloudDoc processing topology and should not become a shared destination for unrelated queues.

### Configure Redrive Inline on the Queue

Rejected for this Terraform design.

The dedicated redrive policy resource keeps the relationship explicit and directly testable.

### Automatically Replay DLQ Messages

Rejected.

Replay requires an explicit operational decision and protections against reintroducing poison messages.

### Configure Remote State Immediately

Deferred.

The initial environment is single-engineer and does not yet run automated deployment.

Remote state and locking will be introduced before shared or CI-managed apply workflows.

### Require Real AWS Credentials for Tests

Rejected.

The first validation boundary should be deterministic, fast, and safe for local development and CI.

Deployed AWS validation will complement rather than replace offline tests.

## Follow-Up Decisions

Future ADRs or infrastructure slices must define:

- private S3 document storage
- S3-to-SQS queue policy
- S3 ObjectCreated notifications
- Lambda deployment packaging
- Processor Lambda timeout
- DLQ Reconciler Lambda timeout
- execution-role IAM policies
- SQS event-source mappings
- partial batch failure configuration
- concurrency controls
- CloudWatch metrics and alarms
- remote Terraform state
- plan and apply workflows
- operator investigation and replay procedures