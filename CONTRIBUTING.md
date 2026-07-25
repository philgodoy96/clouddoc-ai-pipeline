# Contributing

Thank you for your interest in contributing to CloudDoc AI Pipeline.

This repository follows a focused, reviewable development workflow. Changes should preserve the documented architecture, remain small enough to evaluate confidently, and include the validation required by the affected area.

## Development Principles

Contributions should:

* address one coherent objective
* preserve architectural boundaries
* include appropriate automated tests
* document meaningful trade-offs
* avoid unrelated refactoring
* avoid introducing tools or services without a clear requirement
* distinguish implemented behavior from planned behavior
* keep sensitive data and local configuration out of Git

The project architecture is documented under:

```text
docs/architecture/
```

Significant decisions are recorded under:

```text
docs/adr/
```

Contributors should review the relevant documentation before modifying system boundaries or infrastructure responsibilities.

## Local Requirements

The project currently requires:

* Python 3.12
* Git
* a Python virtual environment
* Make, Git Bash, WSL, or equivalent direct Python commands

Terraform and AWS tooling will be documented when infrastructure implementation becomes active.

## Local Setup

Clone the repository:

```bash
git clone https://github.com/philgodoy96/clouddoc-ai-pipeline.git
cd clouddoc-ai-pipeline
```

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

## Development Commands

Install dependencies:

```bash
make install
```

Format source files:

```bash
make format
```

Check formatting:

```bash
make format-check
```

Run linting:

```bash
make lint
```

Run tests:

```bash
make test
```

Run tests with coverage:

```bash
make test-cov
```

Run the complete local validation suite:

```bash
make check
```

Equivalent direct commands may be used when Make is unavailable:

```bash
python -m ruff format . --check
python -m ruff check .
python -m pytest
```

## Branch Naming

Branches should use a short category and a descriptive kebab-case name.

Accepted examples:

```text
chore/repository-foundation
docs/add-event-flow
feat/add-job-state-model
feat/add-mock-ai-provider
test/add-duplicate-event-coverage
fix/prevent-terminal-job-reprocessing
refactor/extract-processing-claim-service
```

Common prefixes:

```text
chore/
docs/
feat/
fix/
test/
refactor/
build/
ci/
```

Avoid vague branch names such as:

```text
changes
updates
final
fixes
new-work
```

## Commit Messages

Commit messages follow a conventional, action-oriented format:

```text
<type>: <concise description>
```

Examples:

```text
chore: initialize repository foundation
build: configure Python development tooling
docs: add approved architecture foundations
feat: add document job state transitions
test: add duplicate processing coverage
fix: reject expired processing claims
refactor: extract DynamoDB item mapper
ci: add Terraform validation workflow
```

Commit messages should:

* describe one focused change
* use imperative language
* avoid punctuation at the end of the subject
* remain understandable without reading the full diff
* avoid generic wording

Do not use messages such as:

```text
update
changes
final
fixes
project complete
misc
```

## Commit Scope

Each commit should represent one coherent engineering step.

Avoid combining:

* application behavior and unrelated documentation
* infrastructure and unrelated refactoring
* new features and broad formatting changes
* multiple architectural decisions
* generated files and unrelated source edits

Small commits make changes easier to review, test, revert, and explain.

## Architectural Boundaries

Contributions must preserve the dependency direction documented in:

```text
docs/architecture/engineering-principles.md
```

Key rules include:

* Lambda handlers remain thin infrastructure adapters.
* Domain modules must not depend on boto3 or AWS event structures.
* Application services must not consume raw API Gateway, SQS, or S3 event dictionaries.
* Bedrock access must remain inside the AI provider implementation.
* DynamoDB access must remain inside the repository implementation.
* S3 document access must remain inside the storage implementation.
* Application services own use-case orchestration.
* DynamoDB remains the authoritative job-state store.
* Raw document contents and complete model payloads must not be logged.
* Automated tests must not invoke Amazon Bedrock.

Changes that intentionally alter one of these rules require an architecture review and, when appropriate, a new ADR.

## Adding Dependencies

New dependencies require a clear technical purpose.

Before adding a library, consider:

* what responsibility it owns
* whether the standard library is sufficient
* whether an existing dependency already solves the problem
* runtime and package-size impact
* security and maintenance implications
* compatibility with AWS Lambda
* whether the dependency is required in production or only during development

Dependencies must not be added solely to demonstrate familiarity with a tool.

## AWS Service Changes

New AWS services or integrations require documented justification.

A change should explain:

* the problem being solved
* why existing services are insufficient
* delivery and failure semantics
* IAM implications
* operational complexity
* cost implications
* testing approach
* Terraform ownership

Console-only infrastructure changes are not accepted as part of the application architecture.

## DynamoDB Changes

DynamoDB changes must begin with explicit access patterns.

A pull request adding a key, index, or new item type should document:

* the new read or write operation
* expected key structure
* consistency requirements
* conditional-write behavior
* idempotency implications
* item-size considerations
* migration or compatibility concerns

Generic indexes added for possible future queries should be avoided.

## AI Integration Changes

AI-related changes must preserve the provider boundary.

The application must:

* treat model output as untrusted
* validate structured results
* avoid scattering provider calls
* normalize provider errors
* support deterministic tests
* avoid real model calls in automated test suites
* avoid logging full prompts, documents, or raw responses

Changes to the structured output schema should include:

* validation tests
* backward-compatibility consideration
* result-size consideration
* updated API or architecture documentation

## Testing Expectations

Contributions should add tests at the appropriate boundary.

### Unit tests

Use for:

* domain rules
* state transitions
* validation
* service orchestration
* provider error mapping
* event normalization
* duplicate-delivery behavior

Unit tests must not require AWS credentials or network access.

### Integration tests

Use for:

* repository mappings
* S3 storage behavior
* interactions between internal components
* emulated AWS service behavior
* complete application flows using deterministic providers

Emulated AWS tests do not replace deployed AWS validation.

### Contract tests

Use for:

* API request and response shapes
* SQS and S3 event fixtures
* provider interface guarantees
* structured AI output contracts

### Manual validation

Infrastructure and real AWS integrations may require a documented manual checklist.

Manual testing must complement, not replace, automated coverage.

## Documentation Expectations

Documentation should be updated when a change affects:

* architecture
* system boundaries
* API contracts
* environment variables
* deployment
* operational procedures
* failure handling
* security assumptions
* cost behavior
* intentionally deferred scope

Architecture documents describe the current design.

ADRs preserve the reasoning behind significant decisions.

README content must accurately distinguish between:

* implemented capabilities
* planned capabilities
* intentionally deferred capabilities

## Pull Requests

Every pull request should include:

* a clear summary
* the concrete changes introduced
* the reason for the change
* validation instructions
* relevant trade-offs
* follow-up work

Pull requests should be small enough to review confidently.

A pull request is not ready for review when:

* tests are failing
* formatting or linting fails
* unrelated changes are included
* architecture changes are undocumented
* manual validation steps are missing
* generated or secret files are tracked
* implemented and planned behavior are described inaccurately

## Required Local Validation

Before opening or updating a pull request, run:

```bash
python -m ruff format . --check
python -m ruff check .
python -m pytest
```

When Terraform files are affected, also run:

```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

Additional checks may be introduced as the repository evolves.

## Pull Request Review Checklist

Before requesting review, verify:

* the branch contains one coherent objective
* the commit history is focused and understandable
* architecture boundaries are preserved
* tests cover success and failure behavior
* no real Bedrock calls are required by automated tests
* no sensitive payloads are logged
* no local environment or Terraform state files are tracked
* documentation reflects the actual implementation
* trade-offs and follow-up work are explicit
* all relevant validation commands pass

## Security

Never commit:

* AWS credentials
* access tokens
* private keys
* `.env` files
* Terraform state
* pre-signed URLs
* real confidential documents
* production model payloads
* sensitive logs

Security-sensitive changes should explain:

* the threat or risk addressed
* the IAM impact
* the data exposure impact
* failure behavior
* how the change was validated

## Reporting Issues

Issues should include:

* a concise description
* expected behavior
* observed behavior
* reproduction steps
* relevant logs with sensitive content removed
* environment details
* whether the problem is consistent or intermittent

Do not include credentials, full document content, pre-signed URLs, or confidential extracted data in issue reports.
