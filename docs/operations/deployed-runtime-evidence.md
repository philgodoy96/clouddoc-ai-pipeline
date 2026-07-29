# Deployed Runtime Evidence

## Purpose

This document records the sanitized operational evidence used to validate the
CloudDoc `dev` environment.

It complements the architecture and runbooks by distinguishing:

```text
implemented in repository source
from
deployed and operationally verified in AWS
```

The evidence intentionally excludes account IDs, complete ARNs, bucket names,
table names, pre-signed URLs, credentials, raw Terraform state, raw plan values,
document contents, complete model responses, and raw CloudWatch records.

## Verification Scope

The verified scope includes:

```text
GitHub Actions OIDC workload authentication
separate Terraform state, plan, and apply authorization
remote S3 Terraform state with native lockfiles
value-free Terraform plan attestation
controlled Terraform deployment
deterministic shared Lambda package publication
AWS IAM-authenticated control-plane requests
pre-signed S3 document upload
S3 → SQS → Processor Lambda delivery
real Amazon Bedrock inference
strict AIExtractionResult validation
authoritative DynamoDB lifecycle persistence
structured CloudWatch trace correlation
one deterministic non-retryable failure path
```

The verified environment is:

```text
dev
```

This evidence does not claim production certification, multi-account
deployment, independent team approval, automated rollback, notification
routing, load testing, model-quality benchmarking, or proof of every possible
failure mode.

## Infrastructure Deployment Evidence

### Final infrastructure convergence

| Evidence | Result |
| --- | --- |
| Commit | `93d53d857506b3772bd791cfa0d4642717d3c371` |
| Terraform Plan run | `30465344265` |
| Terraform Deploy run | `30465512666` |
| Plan actions | 5 create, 0 update, 0 delete, 0 replace |
| Apply actions | 5 added, 0 changed, 0 destroyed |
| Post-apply convergence | No changes |
| Managed Terraform addresses | 61 |
| Tainted resources | 0 |
| Remote lock | Absent |
| Deploy artifacts | 0 |
| `dev-deploy` status | Success |

Run references:

- Terraform Plan:
  `https://github.com/philgodoy96/clouddoc-ai-pipeline/actions/runs/30465344265`
- Terraform Deploy:
  `https://github.com/philgodoy96/clouddoc-ai-pipeline/actions/runs/30465512666`

### Application package correction deployment

A deployed runtime proof exposed a DynamoDB physical-key mismatch:

```text
deployed table partition-key attribute:
    PK

application persistence attribute before correction:
    pk
```

DynamoDB attribute names are case-sensitive. The application was corrected to
use the deployed `PK` contract and the shared Lambda package was republished
through the same controlled deployment path.

| Evidence | Result |
| --- | --- |
| Commit | `2624306308adba8ae7c17cc4156c280a21f70fab` |
| Terraform Plan run | `30470475589` |
| Terraform Deploy run | `30470631374` |
| Plan actions | 0 create, 4 update, 0 delete, 0 replace |
| Updated resources | Four shared-package Lambda functions |
| Mutation boundary | `source_code_hash` only |
| Apply actions | 0 added, 4 changed, 0 destroyed |
| Post-apply convergence | No changes |
| Managed Terraform addresses | 61 |
| Tainted resources | 0 |
| Remote lock | Absent |

Run references:

- Terraform Plan:
  `https://github.com/philgodoy96/clouddoc-ai-pipeline/actions/runs/30470475589`
- Terraform Deploy:
  `https://github.com/philgodoy96/clouddoc-ai-pipeline/actions/runs/30470631374`

## Runtime Happy-Path Evidence

The deployed happy path used one synthetic UTF-8 plain-text document containing
no personal, confidential, regulated, or customer data.

| Evidence | Result |
| --- | --- |
| Commit | `2624306308adba8ae7c17cc4156c280a21f70fab` |
| Job ID | `job_c8cad7c0bf9c4b1bab75a2e76d7d4d7f` |
| Correlation ID | `runtime-pk-fix-proof-20260729T162926Z-0b922852` |
| Create Job | HTTP 201 |
| Initial state | `pending_upload`, attempts `0` |
| Physical DynamoDB key | Uppercase `PK`; lowercase `pk` absent |
| Pre-signed upload | One successful `PUT`, `text/plain` |
| Final state | `succeeded` |
| Attempts | `1` |
| Error reason | `null` |
| Processing result | Validated schema present |
| AI provider | `bedrock` |
| Model | `amazon.nova-micro-v1:0` |
| Provider outcome | `succeeded` |
| Processing DLQ | No increase |
| Reconciliation-failures queue | No increase attributable to the proof |

The final result contained the application-owned contract:

```text
document_type
summary
key_fields
confidence
requires_human_review
```

Complete extracted content is intentionally not recorded in repository
documentation.

### Correlated happy-path telemetry

The proof correlated these structured events:

```text
control_plane.request_completed
    operation = create_document_job
    outcome = succeeded
    status_code = 201

control_plane.request_completed
    operation = get_document_job
    outcome = succeeded
    status_code = 200

ai_provider.invocation_completed
    provider_name = bedrock
    outcome = succeeded

processing.record_completed
    outcome = processed

processing.batch_completed
    outcome = succeeded
    failed_record_count = 0
```

No correlated control-plane 5xx, provider error, retryable processing failure,
terminal processing failure, DLQ delivery, or reconciliation failure was
observed.

## Controlled Failure-Path Evidence

The controlled failure proof used one synthetic UTF-8 plain-text document whose
encoded size was exactly one byte above the configured maximum.

```text
configured maximum:
    65,536 bytes

proof document:
    65,537 bytes
```

This input was selected from executable source and tests before the request was
created. The expected branch was a deterministic, non-retryable document
validation failure before Bedrock invocation.

| Evidence | Result |
| --- | --- |
| Commit | `2624306308adba8ae7c17cc4156c280a21f70fab` |
| Job ID | `job_281d484b9cc94c09b870c728738eb7fd` |
| Correlation ID | `runtime-failure-proof-20260729T164343Z-58e26e6b` |
| Create Job | HTTP 201 |
| Upload | One successful pre-signed `PUT` |
| Initial state | `pending_upload`, attempts `0` |
| Final state | `failed` |
| Attempts | `1` |
| Error reason | `document_validation_failed` |
| Processing result | Absent |
| Retryable | `false` |
| Bedrock invocation | Not reached |
| SQS batch item failures | `0` |
| Processing DLQ | No increase |
| Reconciliation-failures queue | No increase attributable to the proof |

The job moved directly to the expected terminal application state before the
first status poll observed an intermediate `processing` state.

### Correlated controlled-failure telemetry

The proof correlated:

```text
control_plane.request_completed
    operation = create_document_job
    outcome = succeeded
    status_code = 201

processing.record_completed
    outcome = terminal_failure_recorded
    failure_reason = document_validation_failed

processing.batch_completed
    outcome = succeeded
    failed_record_count = 0

control_plane.request_completed
    operation = get_document_job
    outcome = succeeded
    status_code = 200
```

The absence of `ai_provider.invocation_completed` was expected because document
validation occurs before provider invocation.

The non-retryable record was acknowledged and removed without entering the
processing DLQ. The intentional business failure was not misclassified as a
control-plane or infrastructure outage.

## Observability Evidence

The deployed proof established that:

```text
API Gateway access logs record the expected POST and GET outcomes
control-plane Lambda logs preserve request and correlation identifiers
asynchronous processing logs preserve job and workflow context
Bedrock telemetry identifies provider, model, outcome, and safe metadata
DynamoDB remains authoritative for business lifecycle state
SQS queue counts support, but do not replace, correlated workflow evidence
```

The deployed CloudWatch dashboard and alarm resources exist under Terraform
management.

No synthetic alarm-state transition or external notification delivery was
performed. Operator notification routing remains intentionally deferred because
the current project scope focuses on runtime correctness, traceability, state
safety, and controlled deployment.

## Security and Data-Handling Boundaries

The operational proofs preserved these boundaries:

```text
AWS IAM authentication for control-plane routes
no long-lived AWS credentials in GitHub
private S3 document storage
time-limited pre-signed uploads
no document content in operational logs
no raw model response in operational logs
no pre-signed URL in evidence
no direct operator DynamoDB writes
no direct operator SQS messages
no direct Lambda invocation
no direct Lambda code update
no Terraform state mutation outside the controlled workflow
```

Synthetic proof objects and jobs were retained as bounded environment evidence.
They contain no personal or customer data.

## What Is Proven

The evidence proves, for the current `dev` deployment:

- the remote-state and deployment authorization model operates successfully;
- reviewed Terraform plans can be bound to controlled deployments;
- Terraform converges with 61 managed addresses, zero taints, and no lock;
- the shared Lambda artifact can be updated without infrastructure replacement;
- an authenticated client can create and retrieve document jobs;
- document jobs persist under the uppercase `PK` table contract;
- a pre-signed upload triggers the asynchronous processing pipeline;
- the deployed Processor invokes Amazon Bedrock Nova Micro;
- provider output is validated before successful persistence;
- a deterministic non-retryable validation failure reaches the correct terminal
  state without unnecessary retry or DLQ delivery;
- structured logs correlate synchronous and asynchronous execution without
  exposing document or model content.

## What Is Intentionally Not Claimed

The evidence does not prove:

- production readiness for regulated or customer workloads;
- load, stress, soak, or multi-region behavior;
- every retryable dependency failure;
- exhausted-retry and DLQ reconciliation through an intentionally induced
  provider outage;
- automatic rollback;
- notification delivery;
- independent segregation of duties;
- cross-account deployment;
- model accuracy across a representative evaluation dataset;
- cost behavior at production traffic volume;
- exactly-once model invocation.

These are explicit future decisions rather than hidden project limitations.

## Current Project Status

```text
repository implementation:
    complete for the approved v1 scope

dev infrastructure deployment:
    completed and converged

runtime happy path:
    completed and verified

controlled deterministic failure path:
    completed and verified

real Bedrock invocation:
    completed and verified

final documentation:
    completed by the documentation PR containing this evidence

engineering review:
    next gate

conceptual engineering review:
    after engineering review

v1.0.0 release:
    after final reviews
```