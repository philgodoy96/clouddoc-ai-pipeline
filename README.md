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

Implemented-in-repository foundations are distinct from deployed-and-validated-in-AWS behavior. AWS deployment, real Bedrock invocation, and deployed end-to-end validation remain future work.

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
```

The repository declares the control plane, queues, event-source mappings, Lambdas, runtime composition, Bedrock adapter, exact IAM boundary, structured operational logging, CloudWatch alarms, and the operations dashboard. The AWS environment has not yet been deployed and validated. The diagram describes the approved architecture as implemented in the repository, not an already active AWS deployment. DynamoDB remains authoritative for `DocumentJob` lifecycle state; CloudWatch provides operational evidence only.

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

* controlled deployment
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

Detailed principles are documented in:

* [Project Context](docs/architecture/project-context.md)
* [System Design](docs/architecture/system-design.md)
* [Engineering Principles](docs/architecture/engineering-principles.md)
* [Lambda Packaging Architecture](docs/architecture/lambda-packaging.md)
* [Bedrock AI Provider Integration](docs/architecture/bedrock-ai-provider-integration.md)
* [CloudWatch Observability](docs/architecture/cloudwatch-observability.md)
* [ADR-017: Package Python Lambdas as a Shared Deterministic ZIP](docs/adr/ADR-017-package-python-lambdas-as-a-shared-zip.md)
* [ADR-023: Use Amazon Nova Micro through Bedrock Converse](docs/adr/ADR-023-use-amazon-nova-micro-through-bedrock-converse.md)
* [ADR-024: Use Native AWS Metrics and Structured Application Logs](docs/adr/ADR-024-use-native-aws-metrics-and-structured-application-logs.md)

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
* Terraform validation with 29 expected test runs

Builder-tooling tests use temporary directories and local dependency fixtures. They do not install real packages, do not access AWS, and do not require network access.

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

Implemented reliability controls include:

* DynamoDB conditional writes
* bounded processing leases
* terminal and retryable error classification
* limited queue retries
* dead-letter preservation
* dead-letter job reconciliation
* correlation identifiers
* explicit state transitions

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

* remote Terraform state
* CI packaging and infrastructure gates
* controlled deployment
* real AWS invocation and end-to-end validation
* real CloudWatch dashboard and alarm validation
* operator notification routing
* operator recovery tooling
* SLOs
* distributed tracing
* operator runbooks
* artifact publication
* code signing
* Lambda layers
* container-image packaging
* arm64

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

## Contributing

Contribution standards, local setup, branch naming, commit conventions, testing expectations, and pull request requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the [MIT License](LICENSE).
