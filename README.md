# CloudDoc AI Pipeline

Production-minded AWS serverless document intelligence pipeline designed to ingest business documents, process them asynchronously, invoke Amazon Bedrock for structured analysis, and expose reliable job status through a cloud-native architecture.

## Project Status

CloudDoc AI Pipeline contains incrementally implemented application and infrastructure foundations in the repository. Controlled Terraform plan and deployment authorization now exist as repository source. Live AWS activation, GitHub deployment configuration, and operational proof remain pending.

### Status distinction

```text
OIDC identity proof:
    operationally verified

Terraform plan OIDC workflow trust:
    source implemented, AWS apply pending

Terraform state and plan authorization roles:
    source implemented, AWS apply pending

Live remote-state Terraform plan:
    pending operational activation

Deployment identity:
    source implemented, AWS apply pending

Terraform apply authorization:
    source implemented, AWS apply pending

Plan attestation:
    source implemented, live artifact proof pending

Controlled deploy workflow:
    source implemented, GitHub configuration pending

GitHub dev-deploy Environment:
    pending

Live Terraform deployment:
    pending operational proof
```

### Implemented and operationally verified

* existing application capabilities documented in this README
* the original GitHub OIDC identity proof

### Implemented in source, activation pending

* second exact GitHub OIDC reusable-workflow trust entry for `.github/workflows/reusable-terraform-plan.yml`
* permissionless deployment identity `clouddoc-dev-github-deploy-identity` for `.github/workflows/reusable-terraform-deploy.yml`
* separate Terraform authorization bootstrap for state, plan, and apply roles
* backend state-role wiring and mutually exclusive plan/apply provider-role wiring
* manual Terraform plan workflow with sanitized summary and value-free plan attestation
* controlled Terraform deploy workflow with regenerate/compare/apply execution
* deployment request validation and exact plan-run binding
* no binary plan or full plan JSON artifact upload

### Controlled Terraform deployment

The project uses a controlled single-operator Terraform deployment model. It does not simulate independent approval through an artificial second GitHub account. Controls include separate permissionless identities, separate authorization roles, manual plan and deploy phases, exact plan-run and commit validation, value-free plan attestation, explicit destructive-change authorization, non-cancelling deployment concurrency, and native S3 Terraform locking.

Security boundaries:

* the plan identity remains unable to deploy
* the deployment identity is permissionless
* the apply role is separate from state and plan roles
* the deploy workflow uses a value-free attestation rather than a binary plan upload
* binary plan files and full plan JSON are not uploaded
* destructive changes are denied by default
* a verified no-op succeeds without apply
* automatic rollback is intentionally not claimed
* live activation remains pending

Design and operations:

* [Terraform Deployment Authorization](docs/architecture/terraform-deployment-authorization.md)
* [Terraform Deploy Workflow Runbook](docs/operations/terraform-deploy-workflow.md)
* [ADR-028: Controlled Single-Operator Terraform Deployment](docs/adr/ADR-028-controlled-single-operator-terraform-deployment.md)

### Intentionally deferred

* production authorization
* cross-account deployment
* team-based reviewers
* multi-party approval
* automatic rollback
* HCP Terraform
* persistent binary plans
* policy-as-code platforms

Foundations already implemented in the repository include:

* document-job domain and application services
* AWS adapters and Lambda-compatible handlers
* processing and dead-letter reconciliation
* Terraform processing queues
* private S3 document ingestion
* deterministic Lambda ZIP packaging
* four Terraform-managed Lambda functions
* processing and DLQ event-source mappings
* API Gateway HTTP control plane
* Amazon Bedrock production provider adapter
* runtime provider selection
* strict JSON and AIExtractionResult validation
* Processor-only Nova Micro configuration
* Processor-only least-privilege model invocation permission
* structured operational logging
* control-plane request telemetry
* processing and reconciliation record/batch telemetry
* Bedrock invocation telemetry
* Lambda JSON / INFO / WARN logging configuration
* nine CloudWatch alarms
* one environment-scoped operations dashboard
* offline observability tests
* offline provider and Terraform tests
* account-scoped Terraform state bootstrap
* partial S3 backend
* S3-native locking configuration
* explicit dev/staging/prod state files
* AWS account guard
* guarded Terraform environment workflow
* saved-plan integrity manifests
* offline state and workflow tests
* offline automated tests
* credential-free infrastructure CI
* deterministic Lambda package reproducibility gate
* application and bootstrap Terraform offline CI
* immutable GitHub Action references
* Dependabot maintenance for GitHub Actions
* static CI workflow contract tests
* GitHub OIDC bootstrap root
* strict GitHub workload trust policy
* permissionless development identity role
* manual OIDC identity-check workflow
* reusable identity workflow
* OIDC bootstrap tests
* identity workflow contract tests

Validation workflows are implemented in the repository. Controlled plan and deploy workflow source exists; live plan activation, GitHub `dev-deploy` configuration, and live deployment proof remain pending. Branch protection is not claimed as configured.

GitHub OIDC trust bootstrap, both permissionless identity roles, identity-check workflows, Terraform authorization bootstrap (state, plan, and apply), manual Terraform plan workflows, value-free plan attestation, and controlled deploy workflows are implemented in repository source. The previously completed GitHub OIDC identity proof is the completed operational checkpoint. AWS apply of the extended trust and authorization roles, GitHub Environment and repository-variable configuration, live remote Terraform plan proof, and live controlled deployment proof remain post-merge activation work.

Architecture and delivery foundations already defined include:

* business context and system responsibilities
* synchronous and asynchronous execution boundaries
* S3-based document ingestion
* SQS-based processing and retry strategy
* Lambda runtime responsibilities
* DynamoDB job-state ownership
* AI provider abstraction
* structured output validation
* idempotency and processing-lease strategy
* dead-letter reconciliation
* observability, IAM, security, and cost principles
* Terraform ownership boundaries
* professional contribution and pull request workflow

Implemented-in-repository foundations are distinct from resources created, initialized, planned, or applied in AWS. Real AWS state-bucket bootstrap, remote backend initialization, OIDC bootstrap apply, end-to-end identity verification, and deployment validation remain pending. AWS deployment, real Bedrock invocation, and deployed end-to-end validation remain future work.

## Business Problem

Organizations frequently receive contracts, invoices, reports, onboarding documents, support attachments, and internal files that require classification, summarization, and structured field extraction.

Manual document processing creates recurring operational issues:

* processing time increases with document volume
* classification becomes inconsistent
* important fields may be missed
* employees repeat low-value extraction work
* downstream systems receive unstructured information
* failures are difficult to trace
* AI output may be malformed or unreliable

CloudDoc AI Pipeline is designed to transform uploaded business documents into validated, structured results through an asynchronous AWS workflow.

## Implemented Architecture

```text
Client Application
        │
        │ POST /document-jobs
        ▼
API Gateway
        │
        ▼
API Lambda
        │
        ├── creates the job in DynamoDB
        └── returns a pre-signed S3 upload URL
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
    → guarded Terraform workflow
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

The repository declares the control plane, queues, event-source mappings, Lambdas, runtime composition, Bedrock adapter, exact IAM boundary, structured operational logging, CloudWatch alarms, and the operations dashboard. The AWS environment has not yet been deployed and validated. The diagram describes the approved architecture as implemented in the repository, not an already active AWS deployment. DynamoDB remains authoritative for `DocumentJob` lifecycle state; CloudWatch provides operational evidence only. CI validates repository contracts; it does not deploy or prove deployed AWS behavior. The identity verification path is implemented in repository source and is intentionally separate from application runtime and deployment authorization; it is not yet verified against AWS.

## V1 Capabilities

### Implemented in the repository

* document job creation
* direct uploads through time-limited S3 pre-signed URLs
* asynchronous processing through SQS
* Lambda-based API and processor runtimes
* UTF-8 plain-text document support
* Amazon Bedrock production provider adapter
* structured result validation
* deterministic mock AI provider
* DynamoDB job-state persistence
* conditional processing ownership
* bounded retries
* dead-letter queue handling
* dead-letter state reconciliation
* least-privilege IAM declarations
* Terraform-managed infrastructure
* structured CloudWatch operational logs
* nine CloudWatch alarms
* one environment-scoped CloudWatch operations dashboard
* offline automated tests without real Bedrock or CloudWatch calls

### Remaining before validated v1

* live activation and operational proof of controlled Terraform deployment
* real end-to-end AWS validation
* real alarm validation
* operator notification routing

## Structured Result Contract

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

Model responses are treated as untrusted external input.

A provider request completing successfully is not sufficient to mark a job as successful. The Bedrock adapter requires strict JSON parsing and application-owned `AIExtractionResult` validation before persistence.

## Architecture Principles

The system is designed around the following principles:

* separate the synchronous control plane from asynchronous processing
* keep Lambda handlers thin
* isolate AWS-specific adapters from domain and application logic
* use SQS as a durable processing work queue
* accept at-least-once delivery
* enforce idempotent business effects
* coordinate processing through DynamoDB conditional writes
* use bounded processing leases
* isolate Bedrock behind an AI provider contract
* validate every AI result
* preserve exhausted messages in a DLQ
* reconcile queue failure state with business state
* propagate stable workflow identifiers
* avoid logging sensitive document content
* apply least-privilege IAM
* control retries, concurrency, logging, and retention costs
* manage infrastructure through Terraform
* use explicit environment state identity
* use S3-native locking
* enforce a wrong-account guard for authenticated Terraform operations
* apply only from a reviewed saved plan
* never migrate state automatically
* keep state and plan artifacts outside Git
* validation is separate from deployment
* GitHub Actions validation workflows use read-only permissions
* authentication before authorization
* no long-lived AWS keys in GitHub
* exact workload trust
* OIDC isolated from validation workflows
* permissionless first identity
* no checkout during identity proof
* external actions use full immutable SHAs
* checkout credentials are not persisted
* Terraform CI remains backend-free and credential-free
* generated artifacts are validated but not published

Detailed principles are documented in:

* [Project Context](docs/architecture/project-context.md)
* [System Design](docs/architecture/system-design.md)
* [Engineering Principles](docs/architecture/engineering-principles.md)
* [Lambda Packaging Architecture](docs/architecture/lambda-packaging.md)
* [Bedrock AI Provider Integration](docs/architecture/bedrock-ai-provider-integration.md)
* [CloudWatch Observability](docs/architecture/cloudwatch-observability.md)
* [Infrastructure CI Validation](docs/architecture/infrastructure-ci-validation.md)
* [GitHub OIDC Trust Bootstrap](docs/architecture/github-oidc-trust-bootstrap.md)
* [Terraform Plan Authorization](docs/architecture/terraform-plan-authorization.md)
* [Terraform Deployment Authorization](docs/architecture/terraform-deployment-authorization.md)
* [ADR-027: Separate Terraform State, Plan, and Apply Authorization](docs/adr/ADR-027-separate-terraform-state-plan-and-apply-authorization.md)
* [ADR-028: Controlled Single-Operator Terraform Deployment](docs/adr/ADR-028-controlled-single-operator-terraform-deployment.md)
* [Terraform Plan Workflow Runbook](docs/operations/terraform-plan-workflow.md)
* [Terraform Deploy Workflow Runbook](docs/operations/terraform-deploy-workflow.md)
* [Terraform Authorization Bootstrap](infra/bootstrap/terraform-authorization/README.md)
* [ADR-017: Package Python Lambdas as a Shared Deterministic ZIP](docs/adr/ADR-017-package-python-lambdas-as-a-shared-zip.md)
* [ADR-023: Use Amazon Nova Micro through Bedrock Converse](docs/adr/ADR-023-use-amazon-nova-micro-through-bedrock-converse.md)
* [ADR-024: Use Native AWS Metrics and Structured Application Logs](docs/adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)
* [Terraform State and Environment Workflow](docs/architecture/terraform-state-and-environment-workflow.md)
* [ADR-025: Use S3 Native Locking and Explicit Environment State](docs/adr/ADR-025-use-s3-native-locking-and-explicit-environment-state.md)
* [ADR-026: Separate OIDC Authentication from Deployment Authorization](docs/adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md)

## AWS Architecture

The v1 architecture uses:

* Amazon API Gateway
* AWS Lambda
* Amazon S3
* Amazon SQS
* Amazon SQS dead-letter queue
* Amazon Bedrock
* Amazon DynamoDB
* Amazon CloudWatch
* AWS Identity and Access Management
* Terraform

The repository declares these components and the Bedrock processing-path adapter. Declared code and infrastructure remain distinct from deployed-and-validated AWS behavior.

The initial processing path is:

```text
S3 → standard SQS queue → Processor Lambda
```

EventBridge is intentionally deferred from the primary v1 path because the current requirement is durable work processing, bounded retries, backpressure, and dead-letter handling rather than event fan-out.

## Technology Stack

### Application

* Python 3.12
* Pydantic
* boto3
* pytest
* Ruff

### AWS

* API Gateway
* Lambda
* S3
* SQS
* SQS DLQ
* Bedrock
* DynamoDB
* CloudWatch
* IAM

### Infrastructure and delivery

* Terraform
* GitHub Actions
* Git
* pip-tools

Lambda ZIP packaging targets Python 3.12 on Linux x86_64. Bedrock is integrated in the Processor application path and Terraform IAM boundary; real AWS deployment and inference validation remain pending.

## Repository Structure

Current repository layout:

```text
.
├── .github/
│   ├── dependabot.yml
│   └── workflows/
│       ├── aws-identity-check.yml
│       ├── infrastructure-quality.yml
│       ├── python-quality.yml
│       └── reusable-aws-identity.yml
├── docs/
│   ├── adr/
│   └── architecture/
├── infra/
│   ├── bootstrap/
│   │   ├── github-oidc/
│   │   └── terraform-state/
│   └── terraform/
│       └── environments/
├── lambdas/
├── requirements/
│   ├── lambda.in
│   └── lambda.lock.txt
├── scripts/
│   ├── build_lambda_package.py
│   └── terraform_workflow.py
├── src/
│   └── clouddoc/
│       ├── application/
│       ├── delivery/
│       ├── domain/
│       ├── handlers/
│       ├── infrastructure/
│       ├── observability/
│       ├── providers/
│       ├── repositories/
│       ├── runtime/
│       └── schemas/
├── tests/
│   ├── contract/
│   ├── fakes/
│   ├── integration/
│   ├── tooling/
│   │   └── test_lambda_package_builder.py
│   └── unit/
│       ├── ci/
│       ├── infrastructure/
│       │   └── test_github_oidc_bootstrap.py
│       └── scripts/
├── CONTRIBUTING.md
├── LICENSE
├── Makefile
├── pyproject.toml
└── README.md
```

Local packaging also produces generated paths that are ignored by Git and are not versioned repository contents:

```text
.lambda-build/
artifacts/lambda/
```

## Local Development

### Requirements

* Python 3.12
* Git
* Terraform `>= 1.10.0, < 2.0.0` for Terraform and infrastructure workflow work
* a Python virtual environment
* Make, Git Bash, WSL, or equivalent direct commands

AWS CLI is optional. AWS authentication is not required for offline OIDC bootstrap validation, CI-equivalent offline validation, formatting, linting, packaging checks, or automated tests. Temporary human AWS authentication will be required for the first real bootstrap plan and apply, including the state-bucket and GitHub OIDC trust roots, and for later remote backend initialization, plan, apply, and output against AWS.

### Setup

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it.

Linux or macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Install the project and development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### Quality Checks

Run formatting verification:

```bash
python -m ruff format . --check
```

Run linting:

```bash
python -m ruff check .
```

Run tests:

```bash
python -m pytest
```

Run all current checks with Make:

```bash
make check
```

CI-equivalent local commands:

```powershell
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

`AWS Identity Check` is a manual identity proof. It is not one of the three intended required pull-request validation checks.

### Lambda Packaging

Regenerate the committed Lambda runtime lock:

```bash
make lambda-lock
```

`lambda-lock` intentionally updates the committed dependency lock.

Build the shared Lambda ZIP:

```bash
make lambda-package
```

`lambda-package` may access the package registry for locked Linux wheels.

Build and verify the artifact SHA-256:

```bash
make lambda-package-check
```

`lambda-package-check` builds and verifies SHA-256.

CI builds the package twice from clean outputs, compares both SHA-256 digests, and does not publish the generated ZIP.

Remove generated package outputs only:

```bash
make lambda-clean
```

`lambda-clean` removes only generated package outputs.

The builder can also be invoked directly:

```bash
python scripts/build_lambda_package.py
```

Generated ZIP and checksum files under `artifacts/lambda/` are local build outputs. Do not commit them.

### Terraform Workflow

Offline validation and guarded environment operations use `scripts/terraform_workflow.py`. The script does not expose `destroy`, `force-unlock`, `-lock=false`, or `-auto-approve`.

Run offline checks (no AWS credentials):

```powershell
python scripts/terraform_workflow.py offline-check
```

When AWS authentication is configured for future real operations, set runtime inputs (use your account values; do not commit them):

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID
```

Guarded commands (require future AWS authentication except `show-plan`):

```powershell
python scripts/terraform_workflow.py init --environment dev
python scripts/terraform_workflow.py plan --environment dev
python scripts/terraform_workflow.py show-plan --environment dev
python scripts/terraform_workflow.py apply --environment dev --confirm-environment dev
python scripts/terraform_workflow.py deploy --environment dev --confirm-environment APPLY-DEV
python scripts/terraform_workflow.py output --environment dev
```

`show-plan` and local `apply` use the existing saved-plan contract under `artifacts/terraform/<environment>/`. `deploy` is the controlled regenerate/compare/apply contract used by the GitHub deploy path. Real remote backend initialization, live plan activation, and live controlled deployment remain pending.

## Packaging Contract

The shared deployment artifact is:

```text
artifacts/lambda/clouddoc-app.zip
```

The archive contains:

* the `clouddoc` package at ZIP root
* locked runtime dependencies
* explicitly packaged Boto3

The package targets:

```text
Python 3.12
manylinux2014_x86_64
CPython cp312
```

Equivalent inputs produce a stable archive hash because ordering, timestamps, permissions, and compression behavior are controlled. This is intentionally deterministic packaging within that contract, not cryptographic signing or universal reproducibility across arbitrary environments.

## Testing Strategy

Automated tests do not require AWS credentials or real CloudWatch or Bedrock calls.

Current coverage includes:

* unit tests for domain rules and state transitions
* unit tests for AI output validation
* deterministic mock-provider tests
* Bedrock provider unit tests with an injected fake client
* runtime provider-selection tests
* strict JSON and response-envelope tests
* provider error-normalization tests
* handler tests
* duplicate-event tests
* retry and failure classification tests
* repository integration tests
* event contract tests
* Lambda package builder tooling tests
* operational logger tests
* control-plane telemetry tests
* processing and reconciliation telemetry tests
* Bedrock invocation telemetry tests
* offline CloudWatch alarm and dashboard tests
* offline Terraform tests for Processor-only Bedrock configuration and IAM
* bootstrap Terraform root tests (four runs)
* bootstrap static contract tests (seven tests)
* mocked Terraform OIDC tests (four runs)
* static OIDC bootstrap security contracts (11 tests)
* guarded workflow unit tests with subprocess mocking and plan-manifest integrity checks (55 tests)
* Terraform validation with 29 expected test runs in the application root
* 49 CI workflow contract tests
* identity-workflow source contracts within the CI workflow suite
* credential-free GitHub Actions validation execution
* independent infrastructure jobs
* artifact-independent Terraform CI

Builder-tooling tests use temporary directories and local dependency fixtures. They do not install real packages, do not access AWS, and do not require network access. Bootstrap and workflow tests likewise require no AWS.

Manual deployed-environment checks and end-to-end AWS validation remain future work.

Testing guidance will evolve under:

```text
docs/testing/
```

## Security Principles

The project is designed to:

* keep the S3 bucket private
* use pre-signed uploads
* block public access
* encrypt stored data
* separate Lambda IAM roles
* allow only the Processor role to invoke the selected model
* grant `bedrock:InvokeModel` against one exact foundation-model ARN
* avoid Bedrock wildcard actions or resources
* avoid streaming permission
* avoid static AWS credentials
* avoid broad administrator policies
* avoid logging full documents, raw model responses, or model payloads
* allowlist operational log fields as flat scalars only
* avoid raw request, event, or provider payload logging
* avoid document or model-content logging
* avoid high-cardinality metric dimensions
* avoid `cloudwatch:PutMetricData` permission
* keep Bedrock model invocation logging disabled
* keep explicit non-secret environment tfvars and backend files committed
* keep Terraform state, local `terraform.tfvars`, backend metadata, saved plans, manifests, generated artifacts, and credentials outside Git
* enforce a wrong-account guard and bucket/account binding for authenticated Terraform operations
* keep credentials out of committed backend files
* reject automatic local-state migration
* never bypass S3 lockfiles or locking
* use Secrets Manager only when a real secret exists
* use read-only validation workflow permissions (`contents: read`)
* pin external actions to full immutable SHAs with same-line release comments
* disable checkout credential persistence (`persist-credentials: false`)
* keep validation CI free of OIDC and AWS secrets
* avoid static AWS credentials in GitHub
* grant `id-token: write` only to identity workflows
* keep validation workflows credential-free
* trust exact repository, ID, branch, environment, and workflow claims
* keep the first identity role permissionless
* request a 15-minute identity session
* validate and mask the AWS account during identity proof
* validate generated artifacts without publishing them

`id-token: write` only allows a workflow to request a GitHub OIDC token. AWS trust and role policies decide whether that token can assume an IAM role.

Packaging security boundaries:

* runtime dependency hashes are verified
* generated artifacts are ignored by Git
* AWS credentials are not required for packaging
* secrets and environment files are not copied into the package
* host-native dependencies are not used for the Linux package

Immutable action SHAs reduce mutable-tag drift; they do not by themselves make an action trusted.

## Reliability Principles

The system assumes duplicate delivery and partial failure.

Implemented reliability controls include:

* DynamoDB conditional writes
* bounded processing leases
* terminal and retryable error classification
* limited queue retries
* dead-letter preservation
* dead-letter job reconciliation
* correlation identifiers
* explicit state transitions
* versioned Terraform state objects with environment-specific state keys
* S3 lockfiles for Terraform coordination
* isolated per-environment Terraform metadata under `infra/terraform/.terraform-data/<environment>`
* saved-plan integrity manifests with SHA-256 verification before apply
* explicit apply environment confirmation
* stable required-check names for intended branch protection
* no path-filter skipping of quality workflows
* branch-scoped cancellation of obsolete workflow runs
* two-build Lambda digest comparison
* exact Terraform version in CI (`1.15.8`)
* same offline Terraform command locally and in CI
* manual-only AWS identity caller
* workflow-call-only reusable identity workflow
* preflight context validation before role assumption
* expected role ARN validation
* GetCallerIdentity proof after federation
* GitHub run ID session correlation

Provider failure classification:

* invalid model response is terminal
* timeout, throttling, and temporary unavailability are retryable
* configuration failure is an operational dependency failure
* retryable provider failure releases the owned processing claim
* logging failure does not change business outcomes
* native AWS metrics remain aggregate operational signals
* DynamoDB remains authoritative business state
* structured logs are best-effort operational evidence

The project does not claim exactly-once Lambda execution, exactly-once Bedrock inference, exactly-once log delivery, or lossless logging.

## Cost-Aware Design

Implemented cost controls include:

* direct S3 uploads
* Lambda-based compute with no idle servers
* DynamoDB on-demand capacity
* Amazon Nova Micro as the selected model
* text-only input
* 65,536-byte document limit
* 1,200 output-token limit
* maximum event-source concurrency of five
* two total SDK attempts
* deterministic mock provider in tests
* no streaming
* no provisioned throughput
* bounded queue retries
* restricted content types
* explicit CloudWatch retention
* native AWS metrics instead of custom application metrics
* one CloudWatch dashboard per environment
* nine focused CloudWatch alarms
* one terminal operational event instead of start/completion pairs
* bounded log retention
* no route-level detailed metrics
* no event-source mapping detailed metrics
* no X-Ray
* S3 lifecycle rules
* no provisioned concurrency
* no NAT Gateway requirement
* Terraform teardown documentation
* one account-scoped Terraform state bucket per AWS account (declared in bootstrap)
* S3-native locking without DynamoDB
* SSE-S3 for Terraform state (no KMS key or replication yet)
* bounded noncurrent state version retention in the bootstrap bucket contract
* parallel CI jobs
* bounded CI job timeouts
* cancellation of obsolete workflow runs
* no CI artifact retention for validation workflows
* no AWS resource cost from credential-free validation CI

## Intentionally Deferred from V1

The following product capabilities are intentionally deferred:

* authentication
* multi-tenant SaaS behavior
* production frontend
* ECS or Fargate processing
* EC2
* Kubernetes
* advanced PDF parsing
* scanned-document OCR
* Amazon Textract
* full RAG workflows
* embeddings and vector databases
* LangGraph or agentic orchestration
* multiple production AI providers
* real-time streaming
* advanced analytics dashboards
* automated DLQ redrive
* formal compliance claims

These decisions keep the first release focused on one complete, observable, recoverable serverless document-processing workflow.

Remaining deployment and operational follow-ups:

* branch protection activation
* AWS apply of extended OIDC trust and deployment identity
* AWS apply of Terraform state, plan, and apply authorization roles
* GitHub repository variables for plan and deploy
* GitHub `dev-deploy` Environment
* live remote-state Terraform plan proof
* live controlled Terraform deployment proof
* real AWS deployment validation
* real state-bucket bootstrap in AWS
* real remote backend initialization
* real AWS invocation and end-to-end validation
* real CloudWatch dashboard and alarm validation
* operator notification routing
* operator recovery tooling
* SLOs
* distributed tracing
* code signing
* Lambda layers
* container-image packaging
* arm64
* production authorization
* cross-account deployment
* team-based reviewers
* multi-party approval
* automatic rollback
* HCP Terraform
* persistent binary plans
* policy-as-code platforms

Branch protection should be configured after the validation workflows run successfully on `main`. It is not claimed as active.

## Architecture Decision Records

Significant technical decisions will be documented under:

```text
docs/adr/
```

Planned and recorded ADR topics include:

* SQS as the document-processing queue
* Lambda for bounded processing
* direct pre-signed S3 uploads
* DynamoDB conditional processing claims
* AI provider abstraction
* application-owned AI output validation
* at-least-once delivery
* plain-text input for v1
* dead-letter reconciliation
* shared deterministic Lambda ZIP packaging
* Amazon Nova Micro through Bedrock Converse
* native AWS metrics and structured application logs
* S3-native locking and explicit environment Terraform state
* separate OIDC authentication from deployment authorization
* separate Terraform state, plan, and apply authorization
* controlled single-operator Terraform deployment

## Contributing

Contribution standards, local setup, branch naming, commit conventions, testing expectations, and pull request requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the [MIT License](LICENSE).
