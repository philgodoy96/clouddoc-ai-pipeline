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

Relevant references include:

* [Infrastructure CI Validation](docs/architecture/infrastructure-ci-validation.md)
* [GitHub OIDC Trust Bootstrap](docs/architecture/github-oidc-trust-bootstrap.md)
* [Terraform State and Environment Workflow](docs/architecture/terraform-state-and-environment-workflow.md)
* [Lambda Runtime Infrastructure](docs/architecture/lambda-runtime-infrastructure.md)
* [ADR-026: Separate OIDC Authentication from Deployment Authorization](docs/adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md)

Significant decisions are recorded under:

```text
docs/adr/
```

Contributors should review the relevant documentation before modifying system boundaries or infrastructure responsibilities.

## Local Requirements

The project currently requires:

* Python 3.12
* Git
* Terraform `>= 1.10.0, < 2.0.0` for Terraform and infrastructure workflow changes
* a Python virtual environment
* Make, Git Bash, WSL, or equivalent direct Python commands

AWS CLI is optional. AWS authentication is not required for offline OIDC bootstrap validation, CI-equivalent offline validation, formatting, linting, packaging checks, or automated tests. Temporary human AWS authentication will be required for the first real bootstrap plan and apply, and for later remote backend initialization, plan, apply, and output against AWS.

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

## Terraform Workflow

Infrastructure changes must preserve the guarded Terraform workflow documented in [Terraform State and Environment Workflow](docs/architecture/terraform-state-and-environment-workflow.md) and [ADR-025](docs/adr/ADR-025-use-s3-native-locking-and-explicit-environment-state.md).

Before opening or updating a pull request that touches Terraform, bootstrap, or `scripts/terraform_workflow.py`, run:

```powershell
python scripts/terraform_workflow.py offline-check
```

For authenticated operations against AWS (when credentials are configured in the future), use the guarded workflow commands rather than direct `terraform init`, `plan`, or `apply` against the application root.

Never:

* commit Terraform state
* commit local `terraform.tfvars`
* commit saved plans or plan manifests under `artifacts/terraform/`
* commit credentials or secrets
* bypass locking (`-lock=false`, `force-unlock`, or equivalent)
* use Terraform workspaces for environment selection
* migrate state automatically
* apply configuration directly without the saved-plan contract

## GitHub OIDC and Identity Trust

Changes to GitHub OIDC trust or identity verification require focused security review.

Paths that trigger this review:

```text
infra/bootstrap/github-oidc
.github/workflows/aws-identity-check.yml
.github/workflows/reusable-aws-identity.yml
```

Reviewers must inspect:

```text
trusted repository
repository ID
owner ID
branch
environment
workflow ref
OIDC audience
role permissions
session duration
action SHA
workflow permissions
checkout behavior
AWS account validation
```

Before opening or updating a pull request that touches those paths, run:

```powershell
terraform -chdir=infra/bootstrap/github-oidc fmt -check -recursive
terraform -chdir=infra/bootstrap/github-oidc validate
terraform -chdir=infra/bootstrap/github-oidc test
python -m pytest tests/unit/infrastructure/test_github_oidc_bootstrap.py -q
python -m pytest tests/unit/ci/test_github_actions_workflows.py -q
```

Identity contribution rules:

```text
Do not add AWS access keys to GitHub Secrets.
Do not add OIDC permission to validation workflows.
Do not add wildcard trust without an approved architecture decision.
Do not attach application permissions to the verification role.
Do not add checkout to the identity proof without a reviewed need.
Do not execute the real bootstrap from an unreviewed branch.
```

The identity workflows are implemented in repository source. They cannot succeed end-to-end until the OIDC bootstrap root is applied, the GitHub `dev` Environment exists, the repository variables exist, and the workflows are available on `main`. Do not claim AWS identity federation is active before that verification succeeds.

Architecture references:

* [GitHub OIDC Trust Bootstrap](docs/architecture/github-oidc-trust-bootstrap.md)
* [ADR-026: Separate OIDC Authentication from Deployment Authorization](docs/adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md)

## Continuous Integration

Credential-free validation workflows run on pull requests to `main`, pushes to `main`, and manual `workflow_dispatch`.

Intended GitHub check names:

```text
Python Quality / Format, lint, and test
Infrastructure Quality / Lambda package
Infrastructure Quality / Terraform offline
```

These are the intended required checks once branch protection is configured after the workflows run successfully on `main`. Branch protection is not claimed as currently enforced. `AWS Identity Check` is a manual identity proof and is not one of the three intended required pull-request validation checks.

Before opening a pull request, contributors should run:

```powershell
make check
make lambda-package-check
python scripts/terraform_workflow.py offline-check
```

CI security rules for validation workflows:

```text
external actions require full immutable SHAs
same-line release comments are required
checkout credentials remain disabled (persist-credentials: false)
permissions remain minimal (contents: read)
no AWS identity in validation workflows
no remote Terraform operation in quality workflows
no artifact publication in validation workflows
```

Identity workflows are separate from validation workflows. Only the identity workflows receive `id-token: write`, and that permission only allows requesting a GitHub OIDC token. AWS trust and role policies decide AWS access.

Dependabot opens weekly GitHub Actions update pull requests. When reviewing those changes:

```text
review publisher
review release notes
review action source
review Node runtime changes
review inputs
review permissions
run workflow contract tests
do not auto-merge blindly
```

When the update touches `aws-actions/configure-aws-credentials`, apply the same review bar with particular attention to publisher, release notes, action source, Node runtime changes, inputs, and permissions.

Workflow contract tests:

```powershell
python -m pytest tests/unit/ci/test_github_actions_workflows.py -q
```

Full CI architecture is documented in [Infrastructure CI Validation](docs/architecture/infrastructure-ci-validation.md). Identity federation is documented in [GitHub OIDC Trust Bootstrap](docs/architecture/github-oidc-trust-bootstrap.md).

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

When environment files under `infra/terraform/environments/` change, update [Terraform State and Environment Workflow](docs/architecture/terraform-state-and-environment-workflow.md) or related architecture docs if the contract changes.

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

```powershell
make check
make lambda-package-check
python scripts/terraform_workflow.py offline-check
```

Equivalent direct Python quality commands:

```bash
python -m ruff format . --check
python -m ruff check .
python -m pytest
```

When editing workflow files or Dependabot configuration, also run:

```powershell
python -m pytest tests/unit/ci/test_github_actions_workflows.py -q
```

When editing the GitHub OIDC bootstrap root, also run:

```powershell
terraform -chdir=infra/bootstrap/github-oidc fmt -check -recursive
terraform -chdir=infra/bootstrap/github-oidc validate
terraform -chdir=infra/bootstrap/github-oidc test
python -m pytest tests/unit/infrastructure/test_github_oidc_bootstrap.py -q
```

Focused root-level checks remain useful when editing HCL directly:

```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

Pull requests should expect all three intended checks to pass once the workflows are available:

```text
Python Quality / Format, lint, and test
Infrastructure Quality / Lambda package
Infrastructure Quality / Terraform offline
```

Do not assume GitHub currently enforces these through branch protection.

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
* Python Quality, Lambda package, and Terraform offline checks pass when available

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

Explicit non-secret environment tfvars and backend files under `infra/terraform/environments/` are committed. State, local `terraform.tfvars`, backend metadata, plans, generated artifacts, and credentials remain outside Git.

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
