# GitHub OIDC Trust Bootstrap

## Status

```text
OIDC identity proof:
    operationally verified

Terraform plan OIDC workflow trust:
    deployed and verified

Deployment identity:
    deployed and verified

Controlled deploy workflow trust:
    deployed and verified

Terraform plan federation:
    operationally verified

Controlled deploy federation:
    operationally verified
```

Preserve the distinction between:

```text
source implementation
AWS provisioning
end-to-end operational evidence
authorization
```

The repository now contains:

```text
GitHub OIDC Terraform bootstrap root
strict GitHub-to-AWS role trust policy with exact subject condition
permissionless development identity role
permissionless Terraform deployment identity role
mocked Terraform trust tests
static bootstrap security tests
manual AWS identity-check caller workflow
reusable AWS identity workflow
exact workflow ownership for plan and deploy identities
environment separation between dev and dev-deploy
static GitHub Actions identity, plan, and deploy workflow contracts
```

Verified operational baseline for `dev`:

```text
GitHub OIDC identities deployed
dev and dev-deploy Environments configured
repository variables configured
live Plan verified
live controlled Deploy verified
```

Evidence: [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

Staging and production identities remain intentionally undeployed.

## Purpose

CloudDoc needs a production-minded mechanism for GitHub Actions to authenticate to AWS without storing long-lived AWS access keys in GitHub.

This architecture establishes the identity trust boundary first.

It does not grant Terraform plan authorization, Terraform apply authorization, or deployment authorization. Those remain separate authorization-role boundaries.

The central engineering decision is:

```text
Authentication first
Authorization second
Deployment last
```

This creates a reviewable progression:

```text
GitHub workload identity
        ↓
AWS trust decision
        ↓
temporary permissionless session
        ↓
identity verification
        ↓
separate least-privilege authorization roles
```

## Identity Architecture

CloudDoc uses two permissionless identity roles:

```text
clouddoc-dev-github-identity
    plan/identity permissionless role
    environment: dev
    workflows:
        reusable-aws-identity.yml
        reusable-terraform-plan.yml

clouddoc-dev-github-deploy-identity
    deployment permissionless role
    environment: dev-deploy
    workflow:
        reusable-terraform-deploy.yml
```

Exact workflow ownership and environment separation keep plan and deploy authentication distinct. Downstream authorization then separates further:

```text
state role
    plan identity + deployment identity

plan role
    plan identity only

apply role
    deployment identity only
```

The existing identity role is not reused for apply authorization. Reusing it would allow plan-trusted workflows to reach the Terraform apply role.

See [Terraform Deployment Authorization](terraform-deployment-authorization.md) and [ADR-028](../adr/ADR-028-controlled-single-operator-terraform-deployment.md).

## Architecture Overview

```text
Human bootstrap operator
        │
        │ temporary AWS session
        ▼
infra/bootstrap/github-oidc
        │
        ├── aws_iam_openid_connect_provider
        ├── strict trust policies
        ├── permissionless plan/identity role
        └── permissionless deployment identity role
                     │
                     ▼
           AWS IAM trust substrate


Manual workflow dispatch from main
        │
        ▼
AWS Identity Check / Terraform Plan / Terraform Deploy
        │
        ▼
Reusable identity, plan, or deploy workflow
        │
        ├── environment: dev or dev-deploy
        ├── contents: read
        ├── id-token: write
        ├── exact eight-claim OIDC preflight
        └── temporary permissionless session only
```

## Component Boundaries

### Terraform state bootstrap

Root:

```text
infra/bootstrap/terraform-state
```

Owns:

```text
account-scoped Terraform state bucket
S3-native lockfile substrate
state-bucket protection
state-bucket encryption
state-bucket versioning
```

### GitHub OIDC bootstrap

Root:

```text
infra/bootstrap/github-oidc
```

Owns:

```text
GitHub Actions IAM OIDC provider
permissionless GitHub identity role
AssumeRoleWithWebIdentity trust policy
identity-bootstrap outputs
```

### Application infrastructure

Root:

```text
infra/terraform
```

Owns:

```text
CloudDoc runtime infrastructure
environment-specific application state
Lambda runtime topology
queues
tables
buckets
API resources
observability resources
```

The three roots are intentionally separate.

They have different:

```text
recovery procedures
security boundaries
operators
change frequencies
failure modes
state lifecycles
```

## Authentication Versus Authorization

Authentication answers:

```text
Which GitHub workload is calling AWS?
```

Authorization answers:

```text
What may that authenticated workload do?
```

This slice implements authentication only.

The role created by the OIDC bootstrap root has:

```text
no inline policies
no managed policies
no state access
no application access
no IAM PassRole
no Terraform plan permissions
no Terraform apply permissions
```

A successful role assumption proves the workload identity and trust-policy contract.

It does not make the workflow a deployment workflow.

## Terraform Root Structure

```text
infra/bootstrap/github-oidc/
├── .terraform.lock.hcl
├── README.md
├── data.tf
├── locals.tf
├── oidc.tf
├── outputs.tf
├── providers.tf
├── roles.tf
├── terraform.tfvars.example
├── variables.tf
├── versions.tf
└── tests/
    └── github_oidc.tftest.hcl
```

Static source contracts:

```text
tests/unit/infrastructure/test_github_oidc_bootstrap.py
```

## Terraform Version Contract

```text
Terraform >= 1.10.0 and < 2.0.0
AWS provider ~> 5.0
reviewed provider version 5.100.0
```

The OIDC root shares the reviewed cross-platform provider lock with:

```text
infra/terraform
infra/bootstrap/terraform-state
```

The lock includes package hashes for:

```text
windows_amd64
linux_amd64
```

## Local State Boundary

The GitHub OIDC root intentionally uses local Terraform state.

It cannot rely on GitHub OIDC to create the trust relationship that GitHub OIDC itself requires.

This is a bootstrap dependency:

```text
GitHub OIDC cannot create its own initial AWS trust.
```

The first apply therefore requires a pre-existing human AWS identity with temporary administrative permissions appropriate for the two reviewed IAM resources.

After apply:

```text
protect the local state
create a secure backup outside Git
never commit the state
operate the root rarely
use reviewed import for recovery
```

The state must not contain static AWS credentials.

## AWS IAM OIDC Provider

Terraform resource:

```text
aws_iam_openid_connect_provider.github_actions
```

Issuer:

```text
https://token.actions.githubusercontent.com
```

Audience:

```text
sts.amazonaws.com
```

The root does not add a TLS provider or manually maintained GitHub certificate fingerprint.

The OIDC provider exists only to let AWS validate GitHub-issued workload tokens.

It grants no permission by itself.

## Permissionless Identity Role

Terraform resource:

```text
aws_iam_role.github_dev_identity
```

Default name:

```text
clouddoc-dev-github-identity
```

Role purpose:

```text
verify GitHub Actions OIDC federation
```

Maximum role session duration:

```text
3600 seconds
```

Identity-check session duration:

```text
900 seconds
```

Attached authorization policies:

```text
none
```

The role remains unable to:

```text
read Terraform state
write Terraform state
inspect CloudDoc resources
create CloudDoc resources
modify CloudDoc resources
delete CloudDoc resources
pass execution roles
publish artifacts
deploy Lambda functions
```

## Trust Policy

The role trust policy permits only:

```text
sts:AssumeRoleWithWebIdentity
```

Federated principal:

```text
the GitHub Actions IAM OIDC provider created by this root
```

All trust conditions use:

```text
StringEquals
```

Eight exact claims. The policy contains no wildcard claim values.

### Required claims

```text
aud
sub
repository
repository_id
repository_owner_id
ref
environment
job_workflow_ref
```

### Audience

```text
token.actions.githubusercontent.com:aud
    = sts.amazonaws.com
```

This binds the GitHub token to the AWS STS audience.

### Subject

```text
token.actions.githubusercontent.com:sub
    =
repo:philgodoy96@<github_repository_owner_id>/clouddoc-ai-pipeline@<github_repository_id>:environment:dev
```

The ID-qualified subject is constructed from reviewed Terraform variables:

```text
repo:${github_repository_owner}@${github_repository_owner_id}/${github_repository_name}@${github_repository_id}:environment:${github_environment}
```

The exact subject condition is environment-scoped and embeds the immutable repository ID and immutable repository-owner ID.

Why the subject uses immutable IDs in addition to the separate ID claims:

```text
the subject itself must match the token exactly
separate ID claims provide independently reviewable defense in depth
repository and owner names preserve human-readable review context
```

AWS evaluates the subject through `token.actions.githubusercontent.com:sub`.

The subject contains no wildcard.

### Repository name

```text
token.actions.githubusercontent.com:repository
    = philgodoy96/clouddoc-ai-pipeline
```

This keeps the trust policy human-readable and provides defense in depth.

### Immutable repository ID

```text
token.actions.githubusercontent.com:repository_id
    = <approved numeric repository ID>
```

The numeric repository ID survives repository renames.

### Immutable repository-owner ID

```text
token.actions.githubusercontent.com:repository_owner_id
    = <approved numeric owner ID>
```

The owner ID avoids relying only on a mutable login string.

### Git ref

```text
token.actions.githubusercontent.com:ref
    = refs/heads/main
```

The role cannot be assumed from:

```text
feature branches
tags
pull-request refs
fork refs
```

### GitHub Environment

```text
token.actions.githubusercontent.com:environment
    = dev
```

The reusable identity job must run through the `dev` GitHub Environment.

### Reusable workflow identity

```text
token.actions.githubusercontent.com:job_workflow_ref
    = one of two exact values:
      philgodoy96/clouddoc-ai-pipeline/.github/workflows/
      reusable-aws-identity.yml@refs/heads/main
      philgodoy96/clouddoc-ai-pipeline/.github/workflows/
      reusable-terraform-plan.yml@refs/heads/main
```

`job_workflow_ref` remains:

```text
...reusable-aws-identity.yml@refs/heads/main
```

`job_workflow_sha` is a separate claim and is intentionally not part of this
hotfix.

This restricts role assumption to exactly two reviewed reusable workflows on `main`: the identity proof workflow and the Terraform plan workflow.

A different workflow file cannot assume the role merely because it belongs to the same repository.

## Why No Broad `sub` Pattern

The trust policy does not use a broad pattern such as:

```text
repo:philgodoy96/clouddoc-ai-pipeline:*
```

It also does not use:

```text
StringLike
repo:philgodoy96/*
refs/heads/*
environment:*
```

CloudDoc instead uses eight exact workload claims, including the exact ID-qualified subject.

This makes trust-policy changes visible and reviewable when:

```text
repository ownership changes
workflow path changes
trusted branch changes
trusted environment changes
immutable IDs embedded in the subject change
```

## Terraform Inputs

Defaulted inputs:

```text
aws_region
project_name
github_repository_owner
github_repository_name
github_environment
github_ref
github_identity_workflow_ref
role_max_session_duration
```

Required runtime inputs:

```text
github_repository_id
github_repository_owner_id
```

The numeric IDs are identifiers, not secrets.

They are intentionally absent from defaults.

Do not invent them.

## Terraform Outputs

```text
github_oidc_provider_arn
github_dev_identity_role_name
github_dev_identity_role_arn
github_dev_identity_role_max_session_duration
github_repository_identity
github_identity_workflow_ref
```

The root does not output:

```text
access keys
secret keys
session tokens
OIDC tokens
temporary credentials
```

## GitHub Workflows

### Caller

File:

```text
.github/workflows/aws-identity-check.yml
```

Workflow:

```text
AWS Identity Check
```

Job:

```text
Verify AWS identity
```

Trigger:

```text
workflow_dispatch only
```

The caller does not contain:

```text
runner selection
checkout
steps
AWS commands
Terraform commands
deployment commands
```

It delegates to the reviewed local reusable workflow.

### Reusable identity workflow

File:

```text
.github/workflows/reusable-aws-identity.yml
```

Workflow:

```text
Reusable AWS Identity
```

Job:

```text
Assume permissionless role
```

Trigger:

```text
workflow_call only
```

Runtime:

```text
ubuntu-latest
5-minute timeout
GitHub Environment: dev
```

Permissions:

```yaml
permissions:
  contents: read
  id-token: write
```

The reusable workflow performs no repository checkout.

## Why `id-token: write` Is Isolated

Existing validation workflows retain:

```yaml
permissions:
  contents: read
```

Only the identity workflows receive:

```yaml
id-token: write
```

The permission allows GitHub Actions to request an OIDC token for the job.

It does not grant AWS authorization by itself.

AWS accepts or rejects the token through:

```text
OIDC provider
role trust policy
token claims
AWS account boundary
```

The separation is:

```text
Python Quality
    → no OIDC

Infrastructure Quality
    → no OIDC

AWS Identity Check
    → OIDC enabled
```

## Caller Inputs

The caller passes:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
us-east-1
```

The account ID and role ARN are non-secret identifiers.

The workflow does not use:

```text
AWS access-key secret
AWS secret-key secret
AWS session-token secret
```

## GitHub Environment

Required environment:

```text
dev
```

Recommended environment configuration:

```text
deployment branches: main only
no AWS credentials
no required deployment secret
```

The environment participates in two controls:

```text
GitHub workflow authorization
OIDC environment claim
```

It is repository configuration, not Terraform-managed infrastructure in this slice.

## Repository Variables

Required variables:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
```

Expected role ARN shape:

```text
arn:aws:iam::<12-digit-account-id>:role/clouddoc-dev-github-identity
```

The reusable workflow validates that:

```text
account ID contains exactly 12 digits
role ARN uses the expected account
role ARN uses the approved role name
region is us-east-1
```

## Temporary AWS Credential Action

Approved action:

```text
aws-actions/configure-aws-credentials
```

Pinned release context:

```text
v6.2.3
```

Pinned immutable commit:

```text
e6de054238d6b7531b4efff3b6587d9aade6a06c
```

Configured controls:

```text
role-to-assume
aws-region
allowed-account-ids
role-duration-seconds
role-session-name
mask-aws-account-id
unset-current-credentials
```

Session name:

```text
clouddoc-identity-${github.run_id}
```

This links the AWS STS session to the GitHub Actions run for audit correlation.

## Context Preflight

Before requesting AWS credentials, the reusable workflow validates:

```text
repository = philgodoy96/clouddoc-ai-pipeline
ref = refs/heads/main
event = workflow_dispatch
account ID = exactly 12 digits
role ARN = expected account and role
region = us-east-1
```

These checks provide early and understandable failures.

The AWS trust policy remains the authoritative security boundary.

The preflight checks are defense in depth, not a replacement for IAM trust conditions.

## Runtime OIDC claim preflight

The reusable AWS identity workflow includes a permanent OIDC claim preflight
between trusted-context validation and AWS credential configuration.

Why it exists:

```text
generic AWS assume-role errors do not identify the mismatched claim
fail-fast identity contract reduces unsafe trial-and-error trust changes
exact claim comparison supports least privilege
sanitized claim diagnostics improve operability without exposing the JWT
```

Where it runs:

```text
.github/workflows/reusable-aws-identity.yml
step: Validate GitHub OIDC token claims
before: Configure temporary AWS credentials
```

Exact runtime step order:

```text
Validate trusted workflow context
Validate GitHub OIDC token claims
Configure temporary AWS credentials
Verify assumed AWS identity
```

Inputs:

```text
ACTIONS_ID_TOKEN_REQUEST_URL
ACTIONS_ID_TOKEN_REQUEST_TOKEN
audience sts.amazonaws.com
GitHub repository, repository_id, repository_owner_id
GitHub ref
GitHub Environment: dev
job.workflow_ref
canonical reusable workflow ref on main
```

Validated claims:

```text
aud
sub
repository
repository_id
repository_owner_id
ref
environment
job_workflow_ref
```

`job_workflow_ref` remains ref-based. `job_workflow_sha` is unused.

Implementation constraints:

```text
Python standard library only
no package installation
no repository checkout
no third-party OIDC debug action
no AWS mutation
process-memory-only token handling
JWT never printed or persisted
GitHub runtime request token never printed
```

The preflight decodes only the JWT payload and compares claims. It does not
perform signature and issuer verification. AWS remains authoritative for
cryptographic token validation and IAM trust-policy evaluation.

### Control boundary

```text
Control:
    Workflow-context validation

Responsibility:
    Verify repository, branch, event, account input, and canonical role input

Control:
    OIDC claim preflight

Responsibility:
    Compare the issued token payload with the expected workload identity contract

Control:
    AWS STS and IAM

Responsibility:
    Validate token signature, issuer, audience, provider trust, and IAM role trust

Control:
    GetCallerIdentity

Responsibility:
    Prove which AWS principal was actually assumed
```

### Observability

Logs contain only sanitized claim diagnostics:

```text
OIDC claim <claim>: match
OIDC claim <claim>: mismatch
sanitized expected / actual values
```

Raw numeric IDs are masked. The JWT is never printed. The GitHub runtime
request token is never printed.

## Identity Proof

After role assumption, the workflow runs:

```bash
aws sts get-caller-identity
```

It extracts the caller ARN and verifies the expected assumed-role suffix:

```text
:assumed-role/clouddoc-dev-github-identity/
clouddoc-identity-<GitHub run ID>
```

Successful output:

```text
AWS OIDC identity federation verified.
```

The verification does not require an identity policy attached to the role.

## No Checkout Boundary

The reusable identity workflow intentionally performs no checkout.

Therefore, during the AWS session it does not execute:

```text
repository source
Python
Terraform
Make targets
Lambda packaging
project scripts
generated artifacts
```

The session can only:

```text
establish temporary credentials
call STS GetCallerIdentity
validate the resulting ARN
```

This keeps the identity proof small and auditable.

## Testing Strategy

### Terraform mocked tests

File:

```text
infra/bootstrap/github-oidc/tests/github_oidc.tftest.hcl
```

Runs:

```text
github_oidc_provider_contract
github_identity_trust_contract
github_identity_role_safety_contract
github_identity_outputs_contract
```

The provider is mocked.

No AWS resource is created.

The tests validate:

```text
canonical issuer
STS audience
provider tags
single trust statement
AssumeRoleWithWebIdentity only
federated principal
eight exact StringEquals conditions
ID-qualified subject construction
exact sub condition
no wildcard claim values
job_workflow_ref remains ref-based
job_workflow_sha absent
canonical role name
maximum session duration
verification tags
identity outputs
```

### Static bootstrap tests

File:

```text
tests/unit/infrastructure/test_github_oidc_bootstrap.py
```

The tests protect:

```text
approved root file set
single mocked Terraform test file
shared provider lock
Terraform version contract
exact resource ownership
local-state boundary
eight exact trust claims
ID-qualified subject construction
exact sub condition
absence of wildcard trust
job_workflow_ref remains ref-based
job_workflow_sha absent
absence of authorization policies
absence of static credentials
placeholder repository IDs
narrow role and workflow defaults
```

### GitHub Actions contracts

File:

```text
tests/unit/ci/test_github_actions_workflows.py
```

The tests distinguish:

```text
validation workflows
identity workflows
```

They protect:

```text
manual-only caller
workflow-call-only reusable workflow
exact identity permissions
no OIDC in validation workflows
approved AWS action SHA
unchanged credential-action pin
unchanged 900-second session duration
no checkout in identity workflows
OIDC claim preflight step existence
OIDC claim preflight step ordering
eight-claim coverage
runtime-token handling
no JWT logging
no job_workflow_sha
job_workflow_ref remains ref-based
no project execution
no static AWS credentials
approved repository variables
account validation
account masking
session naming
STS identity proof
no plan
no apply
no artifact publication
```

## Offline Validation

Format and validate the root:

```powershell
terraform -chdir=infra/bootstrap/github-oidc fmt -check -recursive
terraform -chdir=infra/bootstrap/github-oidc validate
```

Run Terraform tests:

```powershell
terraform -chdir=infra/bootstrap/github-oidc test
```

Run static bootstrap tests:

```powershell
python -m pytest `
  tests/unit/infrastructure/test_github_oidc_bootstrap.py `
  -q
```

Run GitHub Actions contracts:

```powershell
python -m pytest `
  tests/unit/ci/test_github_actions_workflows.py `
  -q
```

Run repository quality gates:

```powershell
make check
make lambda-package-check
python scripts/terraform_workflow.py offline-check
terraform -chdir=infra/bootstrap/github-oidc test
git diff --check
```

No AWS authentication is required for offline validation.

## Real Bootstrap Procedure

Real provisioning begins only after:

```text
implementation complete
offline tests passing
pull request reviewed
trust policy reviewed
target AWS account confirmed
GitHub repository IDs confirmed
temporary human AWS authentication configured
```

### Prepare local variables

Copy:

```powershell
Copy-Item `
  "infra/bootstrap/github-oidc/terraform.tfvars.example" `
  "infra/bootstrap/github-oidc/terraform.tfvars"
```

Replace:

```text
REPLACE_WITH_GITHUB_REPOSITORY_ID
REPLACE_WITH_GITHUB_REPOSITORY_OWNER_ID
```

### Initialize

```powershell
terraform -chdir=infra/bootstrap/github-oidc init
```

### Plan

```powershell
terraform -chdir=infra/bootstrap/github-oidc plan `
  -input=false `
  -out="github-oidc-bootstrap.tfplan"
```

### Review

```powershell
terraform -chdir=infra/bootstrap/github-oidc show `
  "github-oidc-bootstrap.tfplan"
```

The reviewed plan must contain only:

```text
one GitHub IAM OIDC provider
one permissionless IAM role
one strict trust policy
```

### Apply

```powershell
terraform -chdir=infra/bootstrap/github-oidc apply `
  "github-oidc-bootstrap.tfplan"
```

Do not use:

```text
-auto-approve
```

### Preserve bootstrap state

After apply:

```text
protect terraform.tfstate
create a secure external backup
record the operator and time
record the applied commit SHA
record the target AWS account
record the created provider ARN
record the created role ARN
```

## GitHub Configuration Procedure

After the Terraform apply:

1. Create the GitHub Environment:

```text
dev
```

2. Restrict environment deployment branches to:

```text
main
```

3. Add repository or environment variables:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
```

4. Do not add AWS credentials.

5. Merge the workflow files to `main`.

6. Start:

```text
AWS Identity Check
```

through manual workflow dispatch on `main`.

## Initial Federation Incident

An initial AWS Identity Check run was dispatched manually on `main`.

Observed sequence:

```text
manual dispatch on main
preflight passed
AWS credential action reached STS
AssumeRoleWithWebIdentity was denied
CloudTrail recorded the ID-qualified environment subject
trust lacked sub
SHA hypothesis rejected
```

CloudTrail showed that this repository receives an ID-qualified environment-scoped subject.

The previous trust policy evaluated seven exact claims but did not evaluate:

```text
token.actions.githubusercontent.com:sub
```

The source hotfix adds an eighth exact `StringEquals` condition for `sub`, constructed from the existing immutable repository and owner ID variables.

`job_workflow_ref` was not changed.

`job_workflow_sha` was not introduced.

The corrected trust contract is implemented in repository source and has been applied and re-verified against AWS for the approved `dev` workloads.

## Corrective Operational Sequence

Next reviewed steps:

```text
merge claim-preflight hotfix
dispatch AWS Identity Check
inspect claim matrix
correct only proven trust mismatches
generate saved Terraform plan
apply reviewed role-trust update
rerun AWS Identity Check
record successful identity evidence
```

These corrective steps were completed for the approved `dev` identity path. End-to-end identity federation for the identity-check, plan, and deploy workloads is operationally verified.
The roles remain permissionless identity roles.

## End-to-End Verification

Expected flow after the corrective trust is applied:

```text
manual workflow dispatch
        ↓
local reusable workflow
        ↓
dev environment
        ↓
GitHub OIDC token
        ↓
AWS trust-policy validation including exact sub
        ↓
15-minute permissionless role session
        ↓
GetCallerIdentity
        ↓
expected assumed-role ARN
```

Expected successful message:

```text
AWS OIDC identity federation verified.
```

A successful identity check proves:

```text
GitHub can issue the expected workload token
AWS trusts the exact reviewed workload
the workflow reaches the expected AWS account
the workflow assumes the expected role
temporary credentials work
```

It does not prove:

```text
Terraform state access
Terraform plan authorization
Terraform apply authorization
application deployment
runtime correctness
rollback readiness
```

End-to-end federation for the approved `dev` identity, plan, and deploy workloads has been re-verified.

## Failure Modes

### OIDC provider absent

Result:

```text
AssumeRoleWithWebIdentity fails
```

### OIDC claim preflight mismatch

Result:

```text
workflow fails before AWS credential configuration
```

### OIDC token request unavailable

Result:

```text
workflow fails before AWS credential configuration
```

### Malformed JWT payload

Result:

```text
workflow fails before AWS credential configuration
```

### All preflight claims match but AWS denies assume-role

Result:

```text
investigate provider trust, effective IAM trust, or AWS-side validation
```

### Wrong AWS account variable

Result:

```text
preflight or allowed-account-ids check fails
```

### Wrong role ARN

Result:

```text
preflight fails before credential exchange
```

### `sub` absent from trust

Result:

```text
AWS denies AssumeRoleWithWebIdentity
```

### Classic subject configured for an ID-qualified token

Result:

```text
AWS denies role assumption
```

### Wrong immutable IDs embedded in `sub`

Result:

```text
AWS denies role assumption
```

### Wrong environment embedded in `sub`

Result:

```text
AWS denies role assumption
```

### Wrong repository ID

Result:

```text
AWS trust policy denies role assumption
```

### Wrong repository-owner ID

Result:

```text
AWS trust policy denies role assumption
```

### Workflow executed outside `main`

Result:

```text
preflight and ref claim reject the run
```

### Wrong caller event

Result:

```text
preflight rejects non-manual execution
```

### Wrong reusable workflow

Result:

```text
job_workflow_ref claim mismatch
AWS denies role assumption
```

### Missing `dev` environment

Result:

```text
workflow cannot satisfy the reviewed environment contract
```

### Environment excludes `main`

Result:

```text
GitHub prevents environment access
```

### Role receives application permissions accidentally

Result:

```text
source-level bootstrap contract is violated
review must block the change
```

### Static credentials added to a workflow

Result:

```text
GitHub Actions contract tests fail
```

### Action SHA changed without review

Result:

```text
GitHub Actions contract tests fail
```

### Bootstrap local state lost

Result:

```text
reviewed recovery or Terraform import required
```

## Security Invariants

```text
No AWS access key is stored in GitHub.

No AWS credential is committed.

Validation workflows have no OIDC permission.

Only identity workflows request OIDC tokens.

The caller is manual-only.

The reusable workflow is workflow-call-only.

The role trust names one repository.

The trust evaluates the exact ID-qualified subject.

The subject is scoped to the dev environment.

The subject contains no wildcard.

The trust uses immutable repository and owner IDs.

The trust requires main.

The trust requires the dev environment.

The trust requires exactly two reusable workflows on main.

All trust claim values are exact.

The role has no authorization policies.

The identity workflow performs no checkout.

The identity workflow executes no project source.

OIDC claim preflight runs before AWS credential configuration.

Process-memory-only token handling keeps the JWT out of logs and storage.

AWS remains authoritative for signature, issuer, and IAM trust.

The target AWS account is validated.

The account ID is masked.

The temporary session lasts 15 minutes.

The session name carries the GitHub run ID.

Bootstrap state remains outside Git.
```

## Reliability Considerations

```text
workflow-context validation before OIDC claim preflight
OIDC claim preflight before AWS exchange
sanitized claim diagnostics
process-memory-only token handling
exact account validation
exact role ARN validation
exact region validation
exact assumed-role ARN validation
manual trigger
bounded timeout
bounded session
immutable action SHA
static contract tests
mocked Terraform tests
independent bootstrap state
```

The workflow is intentionally small.

A small identity workflow is easier to audit and troubleshoot than a combined identity-and-deployment workflow.

## Audit Considerations

The STS session name includes:

```text
github.run_id
```

This creates a direct correlation point between:

```text
GitHub workflow run
AWS STS assumed-role session
```

Future CloudTrail review can use this session name when Terraform plan authorization and controlled deployment authorization are activated.

CloudTrail alerting and formal audit dashboards remain deferred.

## Cost Considerations

The identity verification workflow:

```text
runs manually
uses one short GitHub-hosted runner job
has a 5-minute timeout
uses a 15-minute AWS session
creates no application resources
stores no workflow artifact
```

The AWS IAM OIDC provider and IAM role do not introduce material recurring compute cost.

## Implemented Versus Provisioned

### Implemented in source

```text
OIDC Terraform root
strict trust policy with exact ID-qualified subject
permissionless plan/identity role
permissionless deployment identity role
exact workflow ownership for plan and deploy
environment separation between dev and dev-deploy
Terraform mocked tests
static bootstrap tests
manual caller workflow
reusable identity workflow
permanent OIDC claim preflight
workflow contract tests
documentation
```

### Operationally verified already

```text
AWS IAM OIDC provider
AWS IAM identity role
AWS IAM deployment identity role
GitHub dev Environment
GitHub dev-deploy Environment
GitHub repository variables
original AWS identity proof
Terraform plan federation
controlled deploy federation
```

### Not authorized by this root

```text
Terraform state read
Terraform state write
Terraform plan
Terraform apply
application resource management
```

Authorization roles are owned by the separate Terraform authorization bootstrap. Live plan activation and live controlled deployment for `dev` are operationally verified; see [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

## Intentionally Deferred

```text
staging identity
production identity
cross-account deployment
permissions boundary
inline session policy
managed session policy
CloudTrail alerting
team-based reviewers
multi-party approval
automatic rollback
HCP Terraform
persistent binary plans
policy-as-code platforms
```

These capabilities require distinct authorization, review, and operational contracts.

## Related Documentation

- [Infrastructure CI Validation](infrastructure-ci-validation.md)
- [Terraform State and Environment Workflow](terraform-state-and-environment-workflow.md)
- [GitHub OIDC Bootstrap Root](../../infra/bootstrap/github-oidc/README.md)
- [Terraform State Bootstrap](../../infra/bootstrap/terraform-state/README.md)
- [Contributing](../../CONTRIBUTING.md)
- [Terraform Plan Authorization](terraform-plan-authorization.md)
- [Terraform Deployment Authorization](terraform-deployment-authorization.md)
- [Terraform Plan Workflow Runbook](../operations/terraform-plan-workflow.md)
- [Terraform Deploy Workflow Runbook](../operations/terraform-deploy-workflow.md)
- [ADR-026: Separate OIDC Authentication from Deployment Authorization](../adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md)
- [ADR-027: Separate Terraform State, Plan, and Apply Authorization](../adr/ADR-027-separate-terraform-state-plan-and-apply-authorization.md)
- [ADR-028: Controlled Single-Operator Terraform Deployment](../adr/ADR-028-controlled-single-operator-terraform-deployment.md)

## References

- [GitHub OpenID Connect](https://docs.github.com/en/actions/concepts/security/openid-connect)
- [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc)
- [OIDC with reusable workflows](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-with-reusable-workflows)
- [Configuring OIDC in AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws)
- [AWS IAM OIDC condition keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_iam-condition-keys.html)
- [AWS IAM OIDC providers](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html)
- [AWS STS GetCallerIdentity](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)
- [Configure AWS Credentials action](https://github.com/aws-actions/configure-aws-credentials)
