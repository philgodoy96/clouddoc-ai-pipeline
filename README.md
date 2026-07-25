# CloudDoc AI Pipeline

Production-minded AWS serverless document intelligence pipeline designed to ingest business documents, process them asynchronously, invoke Amazon Bedrock for structured analysis, and expose reliable job status through a cloud-native architecture.

## Project Status

CloudDoc AI Pipeline is currently in the repository foundation and architecture phase.

The following foundations are already defined:

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

Application behavior and AWS infrastructure will be introduced incrementally through focused implementation slices.

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

Some listed technologies are part of the approved implementation plan and have not yet been introduced into the repository.

## Repository Structure

Current foundation:

```text
.
├── docs/
│   ├── adr/
│   └── architecture/
├── infra/
│   └── terraform/
├── lambdas/
├── src/
│   └── clouddoc/
├── tests/
├── .github/
├── CONTRIBUTING.md
├── LICENSE
├── Makefile
├── pyproject.toml
└── README.md
```

Additional modules will be introduced only when their responsibilities become active.

Planned application boundaries include:

```text
src/clouddoc/
├── domain/
├── schemas/
├── services/
├── providers/
├── repositories/
├── storage/
├── observability/
├── config/
└── bootstrap/
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

## Testing Strategy

Automated tests will not require real Amazon Bedrock calls.

The project will use:

* unit tests for domain rules and state transitions
* unit tests for AI output validation
* deterministic mock-provider tests
* handler tests
* duplicate-event tests
* retry and failure classification tests
* repository integration tests
* event contract tests
* Terraform validation
* manual deployed-environment checks
* manual end-to-end AWS validation

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

The following capabilities are intentionally deferred:

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

## Architecture Decision Records

Significant technical decisions will be documented under:

```text
docs/adr/
```

Planned ADR topics include:

* SQS as the document-processing queue
* Lambda for bounded processing
* direct pre-signed S3 uploads
* DynamoDB conditional processing claims
* AI provider abstraction
* application-owned AI output validation
* at-least-once delivery
* plain-text input for v1
* dead-letter reconciliation

## Contributing

Contribution standards, local setup, branch naming, commit conventions, testing expectations, and pull request requirements are documented in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is licensed under the [MIT License](LICENSE).
