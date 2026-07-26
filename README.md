# CloudDoc AI Pipeline

Production-minded AWS serverless document intelligence pipeline designed to ingest business documents, process them asynchronously, invoke Amazon Bedrock for structured analysis, and expose reliable job status through a cloud-native architecture.

## Project Status

CloudDoc AI Pipeline contains incrementally implemented application and infrastructure foundations in the repository. AWS resource deployment and end-to-end cloud validation remain future work.

Foundations already implemented in the repository include:

* document-job domain and application services
* AWS adapters and Lambda-compatible handlers
* processing and dead-letter reconciliation
* Terraform processing queues
* private S3 document ingestion
* deterministic Lambda ZIP packaging
* offline automated tests

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

Implemented-in-repository foundations are distinct from deployed-and-validated-in-AWS behavior. Remaining application and infrastructure slices will continue to land incrementally.

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

## Planned Processing Flow

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
```

The repository now contains Lambda-compatible handlers and a shared ZIP builder for that runtime. Terraform Lambda function resources remain a follow-up slice; the diagram describes the approved AWS flow, not an already active deployment.

## Planned V1 Capabilities

The first complete version is designed to include:

* document job creation
* direct uploads through time-limited S3 pre-signed URLs
* asynchronous processing through SQS
* Lambda-based API and processor runtimes
* UTF-8 plain-text document support
* Amazon Bedrock classification and extraction
* structured result validation
* deterministic mock AI provider
* DynamoDB job-state persistence
* conditional processing ownership
* bounded retries
* dead-letter queue handling
* dead-letter state reconciliation
* structured CloudWatch logs
* request and correlation identifier propagation
* least-privilege IAM
* Terraform-managed infrastructure
* automated tests without real Bedrock calls
* manual AWS end-to-end validation

## Planned Structured Result

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

Model responses will be treated as untrusted external input.

A provider request completing successfully will not be sufficient to mark a job as successful. Results must pass application-owned validation and be persisted durably.

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

Detailed principles are documented in:

* [Project Context](docs/architecture/project-context.md)
* [System Design](docs/architecture/system-design.md)
* [Engineering Principles](docs/architecture/engineering-principles.md)
* [Lambda Packaging Architecture](docs/architecture/lambda-packaging.md)
* [ADR-017: Package Python Lambdas as a Shared Deterministic ZIP](docs/adr/ADR-017-package-python-lambdas-as-a-shared-zip.md)

## Planned AWS Architecture

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

Lambda ZIP packaging targets Python 3.12 on Linux x86_64. Some listed technologies remain part of the approved implementation plan and have not yet been introduced into every delivery path.

## Repository Structure

Current repository layout:

```text
.
├── docs/
│   ├── adr/
│   └── architecture/
├── infra/
│   └── terraform/
├── lambdas/
├── requirements/
│   ├── lambda.in
│   └── lambda.lock.txt
├── scripts/
│   └── build_lambda_package.py
├── src/
│   └── clouddoc/
│       ├── application/
│       ├── delivery/
│       ├── domain/
│       ├── handlers/
│       ├── infrastructure/
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
├── .github/
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
* a Python virtual environment
* Make, Git Bash, WSL, or equivalent direct commands

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

Automated tests will not require real Amazon Bedrock calls.

The project currently covers or plans coverage for:

* unit tests for domain rules and state transitions
* unit tests for AI output validation
* deterministic mock-provider tests
* handler tests
* duplicate-event tests
* retry and failure classification tests
* repository integration tests
* event contract tests
* Lambda package builder tooling tests
* Terraform validation
* manual deployed-environment checks
* manual end-to-end AWS validation

Builder-tooling tests use temporary directories and local dependency fixtures. They do not install real packages, do not access AWS, and do not require network access.

Manual deployed AWS validation remains future work.

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
* avoid static AWS credentials
* avoid broad administrator policies
* avoid logging full documents or model payloads
* keep Terraform state and environment files out of Git
* use Secrets Manager only when a real secret exists

Packaging security boundaries:

* runtime dependency hashes are verified
* generated artifacts are ignored by Git
* AWS credentials are not required for packaging
* secrets and environment files are not copied
* host-native dependencies are not used for the Linux package

## Reliability Principles

The system assumes duplicate delivery and partial failure.

V1 will use:

* DynamoDB conditional writes
* bounded processing leases
* terminal and retryable error classification
* limited queue retries
* dead-letter preservation
* dead-letter job reconciliation
* structured operational logs
* correlation identifiers
* explicit state transitions

The project does not claim exactly-once Lambda execution or exactly-once Bedrock inference.

## Cost-Aware Design

The planned v1 controls costs through:

* direct S3 uploads
* Lambda-based compute with no idle servers
* DynamoDB on-demand capacity
* deterministic mock inference for tests
* bounded queue retries
* limited document size
* restricted content types
* controlled processor concurrency
* explicit CloudWatch retention
* S3 lifecycle rules
* no provisioned concurrency
* no NAT Gateway requirement
* Terraform teardown documentation

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

Deployment and packaging follow-ups are intentionally sequenced after the shared ZIP foundation:

* Lambda Terraform resources
* execution roles and IAM
* event-source mappings
* runtime environment variables
* CloudWatch log groups
* artifact publication
* CI packaging
* code signing
* Lambda layers
* container-image packaging
* arm64
* real AWS invocation

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

## Contributing

Contribution standards, local setup, branch naming, commit conventions, testing expectations, and pull request requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the [MIT License](LICENSE).
