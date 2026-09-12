# CloudDoc AI Pipeline

Production-minded AWS serverless document intelligence pipeline that ingests business documents, processes them asynchronously, invokes Amazon Bedrock for structured analysis, and exposes reliable job status through a cloud-native control plane.

CloudDoc AI Pipeline `v1.0.0` is the published portfolio release for the approved v1 scope. Repository implementation for that scope is complete. The `dev` environment is deployed, converged, and operationally verified for one happy path and one controlled deterministic failure path. Authoritative sanitized evidence: [Deployed Runtime Evidence](docs/operations/deployed-runtime-evidence.md).

## Business Problem

Organizations receive contracts, invoices, reports, onboarding files, and support attachments that require classification, summarization, and structured field extraction.

Manual processing creates recurring operational issues: latency under volume, inconsistent classification, missed fields, repeated low-value extraction work, unstructured handoffs to downstream systems, opaque failures, and unreliable AI output.

CloudDoc turns an uploaded document into a validated structured result through an asynchronous AWS workflow. Model responses are treated as untrusted input and must pass application-owned validation before a job can succeed.

```json
{
  "document_type": "contract",
  "summary": "A service agreement defining responsibilities and payment terms.",
  "key_fields": {
    "effective_date": "2026-08-01",
    "renewal_term": "12 months"
  },
  "confidence": 0.91,
  "requires_human_review": false
}
```

## Architecture Summary

```text
Client Application
        │
        │ POST /v1/document-jobs
        ▼
API Gateway
        │
        ▼
API Lambda
        │
        ├── provisions upload instructions
        ├── persists the job in DynamoDB
        └── returns nested job + upload
                    │
                    ▼
              Amazon S3
                    │
                    │ ObjectCreated event
                    ▼
              Amazon SQS
                    │
                    ▼
          Processor Lambda
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
   Amazon Bedrock       Amazon DynamoDB
          │                   │
          └──── validated result ────┘

Repeated processing failures
        │
        ▼
      SQS DLQ
        │
        ▼
DLQ Reconciler Lambda
        │
        ▼
DynamoDB job status = dead

Operational side boundary (not business state):
CloudWatch Logs, native AWS metrics, alarms, and operations dashboard

Infrastructure management side path (not runtime request processing):
Infrastructure Operator
    → controlled Terraform Plan / Deploy
    → account-scoped S3 state bucket
    → independent dev/staging/prod state objects

Delivery validation boundary (not runtime request processing):
Pull request
    → Python Quality
    → Infrastructure Quality
        → Lambda package
        → Terraform offline

Identity verification boundary (not runtime request processing, not deployment):
Manual identity check
    → reusable identity workflow
    → GitHub OIDC
    → permissionless AWS role
    → STS GetCallerIdentity
```

Primary processing path: `S3 → standard SQS → Processor Lambda`. EventBridge is intentionally deferred from the v1 primary path; the requirement is durable work processing, bounded retries, backpressure, and dead-letter handling rather than event fan-out.

DynamoDB remains authoritative for `DocumentJob` lifecycle state. CloudWatch provides operational evidence only. Staging and production are not claimed as deployed.

Deeper design: [System Design](docs/architecture/system-design.md), [Project Context](docs/architecture/project-context.md).

## What Is Implemented

Repository and Terraform declare a complete v1 control and processing plane:

* HTTP control plane: `POST /v1/document-jobs`, `GET /v1/document-jobs/{job_id}`
* private S3 ingestion with time-limited pre-signed `PUT` uploads (`text/plain`)
* SQS processing queue, DLQ, and DLQ reconciler topology
* four Terraform-managed Lambda functions with separate execution roles
* DynamoDB job-state persistence with conditional processing ownership and leases
* Amazon Bedrock production provider adapter (Processor-only Nova Micro)
* strict JSON / `AIExtractionResult` validation before success persistence
* structured operational logging, nine CloudWatch alarms, one environment dashboard
* deterministic shared Lambda ZIP packaging and offline automated tests
* account-scoped Terraform state bootstrap, S3-native locking, explicit env state keys
* GitHub OIDC trust, separate state / plan / apply authorization, controlled Plan/Deploy
* credential-free infrastructure CI, immutable GitHub Action SHA pinning, Dependabot for Actions

Technology: Python 3.12, Pydantic, boto3, pytest, Ruff, Terraform, GitHub Actions.

## Operational Status and Guarantees

This version distinguishes repository truth from AWS truth.

### Implemented

Infrastructure and application behavior present in code and IaC for the approved v1 scope, including the control plane, processing plane, Bedrock adapter, observability declarations, CI contracts, and controlled Terraform delivery path.

### Deployed (`dev`)

* GitHub OIDC authentication
* separate state, plan, and apply roles
* remote S3 Terraform state with native lockfiles
* GitHub `dev` and `dev-deploy` Environments
* 61 managed Terraform addresses, 0 taints, remote lock absent
* post-apply convergence verified (`No changes`)

Staging and production infrastructure are not claimed as deployed.

### Operationally verified (`dev`)

Manually executed deployed-runtime evidence (not an automated suite) verified:

* IAM-authenticated create/get document-job routes
* successful pre-signed upload (`content-type = text/plain`)
* DynamoDB persistence under the uppercase `PK` contract
* real Amazon Bedrock invocation (`provider = bedrock`, model `amazon.nova-micro-v1:0`)
* strict result validation and `succeeded` job persistence
* one controlled oversized-document failure (`document_validation_failed`) before Bedrock
* correlated CloudWatch telemetry for both paths
* controlled Terraform Plan / Deploy and value-free plan attestation
* no DLQ or reconciliation increase attributable to these proofs

Authoritative evidence: [Deployed Runtime Evidence](docs/operations/deployed-runtime-evidence.md).

### This does not imply

* staging or production deployment
* production certification for regulated or customer workloads
* multi-region high availability or disaster recovery
* exactly-once processing or exactly-once Bedrock inference
* load, stress, soak, or model-quality evaluation
* automatic rollback, multi-party approval, or independent segregation of duties
* intentionally induced exhausted-retry / DLQ reconciliation proof
* alarm notification delivery or on-call routing
* branch protection configured in GitHub

CI validates repository contracts. It does not replace deployed-runtime evidence.

## Reliability and Failure Semantics

The system assumes duplicate delivery and partial failure.

**This version guarantees:**

* at-least-once delivery on the S3 → SQS → Lambda path
* idempotent business-effect boundaries via DynamoDB conditional writes and processing leases
* bounded queue retries with dead-letter preservation
* DLQ reconciliation that aligns exhausted deliveries with authoritative job state when invoked
* terminal vs retryable failure classification (invalid model output is terminal; timeout / throttling / temporary unavailability are retryable)
* DynamoDB as the source of truth for job lifecycle; queues describe work to attempt

**This does not claim** exactly-once Lambda execution, exactly-once Bedrock inference, exactly-once log delivery, or lossless logging. Side effects that sit outside the idempotency boundary (including provider inference) can repeat under failure and retry.

Details: [System Design](docs/architecture/system-design.md), [Dead-Letter Job Reconciliation](docs/architecture/dead-letter-job-reconciliation.md), [Engineering Principles](docs/architecture/engineering-principles.md).

## Security / IAM / OIDC Trust Boundary

Delivery and runtime trust are separated deliberately.

* **No long-lived static AWS deployment credentials in GitHub.** Workloads authenticate through GitHub OIDC temporary tokens.
* **Authentication before authorization.** OIDC proves identity; separate IAM roles authorize state, plan, and apply.
* **Permissionless first identities.** Plan/identity and deployment identity roles authenticate only; they do not carry broad AWS permissions.
* **Separate state, plan, and apply roles.** The plan identity cannot deploy; apply is a distinct authorization boundary.
* **Value-free plan attestation.** Binary plan files and full plan JSON are not uploaded as deployment artifacts.
* **Processor-only Bedrock boundary.** Only the Processor role may invoke the selected model; permission is `bedrock:InvokeModel` against one exact foundation-model ARN (no wildcards, no streaming).
* **Separate Lambda execution roles** and private S3 with blocked public access and time-limited pre-signed uploads.
* **Immutable GitHub Action SHA pinning** with same-line release comments; checkout credentials are not persisted.
* **Credential-free validation CI.** PR quality workflows use read-only `contents: read` and do not perform OIDC deployment.

Controlled single-operator deployment is intentional for this portfolio environment. It does not simulate independent approval through a second GitHub account. Automatic rollback is intentionally not claimed.

Details: [GitHub OIDC Trust Bootstrap](docs/architecture/github-oidc-trust-bootstrap.md), [Terraform Plan Authorization](docs/architecture/terraform-plan-authorization.md), [Terraform Deployment Authorization](docs/architecture/terraform-deployment-authorization.md), [ADR-026](docs/adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md), [ADR-027](docs/adr/ADR-027-separate-terraform-state-plan-and-apply-authorization.md), [ADR-028](docs/adr/ADR-028-controlled-single-operator-terraform-deployment.md).

## Local Development and Validation

### Requirements

* Python 3.12
* Git
* Terraform `>= 1.10.0, < 2.0.0` for Terraform / infrastructure workflow work
* a Python virtual environment
* Make, Git Bash, WSL, or equivalent direct commands

AWS authentication is not required for offline formatting, linting, packaging checks, automated tests, or CI-equivalent offline validation. Temporary human AWS authentication is required only for bootstrap maintenance and other intentional operator tasks outside the controlled GitHub Plan/Deploy path.

### Setup

```bash
python -m venv .venv
```

Activate the environment, then:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Validate locally

```bash
make check
make lambda-package-check
python scripts/terraform_workflow.py offline-check
python -m pytest tests/unit/ci/test_github_actions_workflows.py -q
```

OIDC bootstrap offline validation:

```powershell
terraform -chdir=infra/bootstrap/github-oidc fmt -check -recursive
terraform -chdir=infra/bootstrap/github-oidc validate
terraform -chdir=infra/bootstrap/github-oidc test
python -m pytest tests/unit/infrastructure/test_github_oidc_bootstrap.py -q
```

Intended GitHub check names (branch protection is not claimed as configured):

```text
Python Quality / Format, lint, and test
Infrastructure Quality / Lambda package
Infrastructure Quality / Terraform offline
```

`AWS Identity Check` is a manual identity proof, not one of the three intended required PR checks.

Packaging, guarded Terraform commands, and contribution workflow:

* [Lambda Packaging Architecture](docs/architecture/lambda-packaging.md)
* [Terraform State and Environment Workflow](docs/architecture/terraform-state-and-environment-workflow.md)
* [Terraform Plan Workflow Runbook](docs/operations/terraform-plan-workflow.md)
* [Terraform Deploy Workflow Runbook](docs/operations/terraform-deploy-workflow.md)
* [CONTRIBUTING.md](CONTRIBUTING.md)

## Production Hardening Triggers

Under a stronger production threat model or operating environment, revisit:

* multi-account separation and production authorization beyond the single-operator `dev` model
* multi-party approval, deployment reviewers, and explicit rollback contracts
* DR / RTO / RPO requirements (cross-region replication, restore drills)
* load, stress, and soak evidence before capacity claims
* alert routing, on-call ownership, and notification delivery
* branch protection activation after required checks are stable on `main`
* broader operational monitoring (distributed tracing, SLOs) when traffic justifies it

These are triggers for stronger controls, not a backlog of missing v1 features. Product capabilities intentionally outside v1 include end-user authentication products, multi-tenancy, PDF/OCR, RAG, agents, and container orchestration platforms.

## Architecture and Operations Docs

| Topic | Authoritative doc |
| --- | --- |
| Runtime evidence | [Deployed Runtime Evidence](docs/operations/deployed-runtime-evidence.md) |
| System design | [System Design](docs/architecture/system-design.md) |
| Project context | [Project Context](docs/architecture/project-context.md) |
| Engineering principles | [Engineering Principles](docs/architecture/engineering-principles.md) |
| Bedrock integration | [Bedrock AI Provider Integration](docs/architecture/bedrock-ai-provider-integration.md) |
| Failure / DLQ reconciliation | [Dead-Letter Job Reconciliation](docs/architecture/dead-letter-job-reconciliation.md) |
| Observability | [CloudWatch Observability](docs/architecture/cloudwatch-observability.md) |
| Lambda packaging | [Lambda Packaging Architecture](docs/architecture/lambda-packaging.md) |
| Terraform state | [Terraform State and Environment Workflow](docs/architecture/terraform-state-and-environment-workflow.md) |
| IAM / OIDC trust | [GitHub OIDC Trust Bootstrap](docs/architecture/github-oidc-trust-bootstrap.md) |
| Plan authorization | [Terraform Plan Authorization](docs/architecture/terraform-plan-authorization.md) |
| Deploy authorization | [Terraform Deployment Authorization](docs/architecture/terraform-deployment-authorization.md) |
| Plan runbook | [Terraform Plan Workflow Runbook](docs/operations/terraform-plan-workflow.md) |
| Deploy runbook | [Terraform Deploy Workflow Runbook](docs/operations/terraform-deploy-workflow.md) |
| Infrastructure CI | [Infrastructure CI Validation](docs/architecture/infrastructure-ci-validation.md) |
| Authorization bootstrap | [Terraform Authorization Bootstrap](infra/bootstrap/terraform-authorization/README.md) |
| ADRs | [Architecture Decision Records](docs/adr/README.md) |

## Repository Structure

```text
.
├── .github/workflows/          # quality, OIDC identity, plan, deploy
├── docs/                       # architecture, operations, ADRs
├── infra/
│   ├── bootstrap/              # OIDC, authorization, state bucket
│   └── terraform/environments/ # explicit env identity (no workspaces)
├── lambdas/
├── requirements/               # Lambda lock inputs
├── scripts/                    # packaging, Terraform workflow, attestation
├── src/clouddoc/               # domain, application, adapters, handlers
├── tests/
├── CONTRIBUTING.md
├── LICENSE
├── Makefile
├── pyproject.toml
└── README.md
```

Generated local outputs (ignored by Git): `.lambda-build/`, `artifacts/lambda/`, `artifacts/terraform/`.

## Contributing

Contribution standards, local setup, branch naming, commit conventions, testing expectations, and pull request requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the [MIT License](LICENSE).
