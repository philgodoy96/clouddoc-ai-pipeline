# Terraform State and Environment Workflow

## Status

Implemented in the repository as an offline-testable infrastructure and operator-workflow slice, and operationally verified for the `dev` environment.

The repository now contains:

```text
account-scoped Terraform state bootstrap root
private versioned S3 state bucket declaration
partial S3 backend declaration
S3-native lockfile configuration
explicit dev, staging, and prod variable files
explicit dev, staging, and prod backend files
environment-specific Terraform metadata directories
optional AWS provider account allowlist
guarded init, plan, show-plan, apply, deploy, and offline-check commands
saved-plan integrity manifests
controlled regenerate/compare/apply deploy contract
local-state migration guard
offline Terraform bootstrap tests
offline Python workflow tests
credential-free Terraform offline CI
```

Credential-free Terraform offline CI is implemented. CI invokes the same `python scripts/terraform_workflow.py offline-check` command used by local operators. CI pins Terraform to `1.15.8`, disables the wrapper (`terraform_wrapper: false`), and validates the application and state-bootstrap roots independently from AWS.

CI does not:

```text
initialize the remote backend
supply state bucket or account values
run plan
run apply
run deploy
validate live AWS authorization
```

Verified operational baseline for `dev`:

```text
state bucket created
dev backend initialized
GitHub OIDC identities deployed
state / plan / apply roles deployed
repository variables configured
dev and dev-deploy Environments configured
live Plan verified
live controlled Deploy verified
value-free attestation verified
post-apply convergence verified
```

Evidence: [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

Staging and production infrastructure are not claimed as deployed.

## Purpose

Terraform state is not a disposable build artifact.

It records the binding between Terraform resource addresses and real infrastructure objects.

CloudDoc requires a state design that prevents:

```text
state loss
concurrent state writers
cross-environment state reuse
planning against one environment and applying against another
planning against one AWS account and applying against another
silent local-to-remote state migration
committing state or credentials
direct unreviewed apply from configuration
```

The implemented workflow introduces explicit ownership and execution boundaries before remote plan, apply, and real AWS deployment.

Operational ordering for foundation work:

```text
state substrate
OIDC trust
identity proof
separate authorization boundary
remote plan
controlled deploy
```

State substrate and OIDC trust are separate bootstrap roots. Identity proof verifies authentication only. The authorization bootstrap owns the dedicated state, plan, and apply roles. For `dev`, those roles are deployed and live remote Plan/Deploy have been operationally verified. Staging and production remain undeployed.

## Architecture Overview

```text
Bootstrap Operator
        │
        │ reviewed saved plan
        ▼
infra/bootstrap/terraform-state
        │
        │ creates once per AWS account
        ▼
Account-scoped S3 state bucket
        │
        ├── clouddoc/dev/terraform.tfstate
        │       └── clouddoc/dev/terraform.tfstate.tflock
        │
        ├── clouddoc/staging/terraform.tfstate
        │       └── clouddoc/staging/terraform.tfstate.tflock
        │
        └── clouddoc/prod/terraform.tfstate
                └── clouddoc/prod/terraform.tfstate.tflock

Infrastructure Operator
        │
        ▼
scripts/terraform_workflow.py
        │
        ├── validates environment files
        ├── validates state key
        ├── validates bucket/account binding
        ├── blocks local-state migration
        ├── verifies Lambda artifact
        ├── isolates TF_DATA_DIR
        ├── creates saved plan
        ├── creates plan integrity manifest
        └── applies only the bound saved plan
```

## Repository Structure

```text
infra/
├── bootstrap/
│   ├── github-oidc/
│   └── terraform-state/
│       ├── .terraform.lock.hcl
│       ├── README.md
│       ├── data.tf
│       ├── locals.tf
│       ├── outputs.tf
│       ├── providers.tf
│       ├── s3.tf
│       ├── terraform.tfvars.example
│       ├── variables.tf
│       ├── versions.tf
│       └── tests/
│           └── terraform_state.tftest.hcl
│
└── terraform/
    ├── backend.tf
    ├── environments/
    │   ├── dev.s3.tfbackend
    │   ├── dev.tfvars
    │   ├── staging.s3.tfbackend
    │   ├── staging.tfvars
    │   ├── prod.s3.tfbackend
    │   └── prod.tfvars
    ├── providers.tf
    ├── variables.tf
    └── versions.tf

scripts/
└── terraform_workflow.py

tests/
└── unit/
    ├── infrastructure/
    │   ├── test_github_oidc_bootstrap.py
    │   └── test_terraform_state_bootstrap.py
    └── scripts/
        └── test_terraform_workflow.py
```

## Terraform Root Boundaries

CloudDoc has three Terraform roots with distinct ownership.

```text
infra/bootstrap/github-oidc owns trust
infra/bootstrap/terraform-state owns state substrate
infra/terraform owns application resources
```

### State bootstrap root

Path:

```text
infra/bootstrap/terraform-state
```

Responsibilities:

```text
create the account-scoped state bucket
block public access
enforce bucket-owner object ownership
enable default encryption
enable versioning
retain noncurrent state versions
deny insecure transport
protect the bucket from routine destruction
expose bucket outputs
```

Non-responsibilities:

```text
manage CloudDoc application resources
manage environment state objects directly
create deployment identities
create GitHub OIDC roles
grant state access to future CI roles
perform application plans or applies
```

### GitHub OIDC bootstrap root

Path:

```text
infra/bootstrap/github-oidc
```

Responsibilities:

```text
declare the GitHub Actions IAM OIDC provider
declare the permissionless development identity role
declare the permissionless deployment identity role
declare the exact AssumeRoleWithWebIdentity trust policies
expose identity-bootstrap outputs
```

Non-responsibilities:

```text
manage the Terraform state bucket
grant state object or lockfile access
declare application infrastructure
attach state, plan, or apply authorization policies
run remote plan or apply
```

The OIDC identity roles currently have no state access and remain permissionless. Downstream state, plan, and apply authorization roles are owned by the separate Terraform authorization bootstrap and are deployed for `dev`. Authentication remains distinct from authorization. See [GitHub OIDC Trust Bootstrap](github-oidc-trust-bootstrap.md), [Terraform Deployment Authorization](terraform-deployment-authorization.md), and [ADR-026](../adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md).

### Application root

Path:

```text
infra/terraform
```

Responsibilities:

```text
declare CloudDoc application infrastructure
declare a partial S3 backend
consume explicit environment variable files
consume explicit environment backend files
enforce the optional expected-account guard
run through the guarded operator workflow
```

Non-responsibilities:

```text
create its own backend bucket
manage bootstrap local state
select an environment through workspaces
store credentials
perform automatic state migration
```

## Bootstrap State Boundary

Both bootstrap roots intentionally retain local state.

This is a narrow bootstrap exception.

```text
state bootstrap root
    → creates the shared state substrate
    → cannot depend on that substrate before it exists
    → is operated rarely

OIDC bootstrap root
    → creates the GitHub-to-AWS trust substrate
    → remains independent from application remote state
    → is operated rarely

application root
    → uses durable remote state
    → is operated repeatedly
    → supports environment-specific plans and applies
```

Bootstrap local state must:

```text
remain outside Git
be backed up securely after a real apply
be treated as an account-foundation artifact
be recovered through reviewed import if lost
```

The project does not claim that bootstrap local state is collaborative remote state.

## State Bucket Contract

Bucket name:

```text
${project_name}-${aws_account_id}-terraform-state
```

Default project example:

```text
clouddoc-123456789012-terraform-state
```

The bucket is account-scoped rather than environment-scoped.

Environment isolation occurs through state keys.

### Security controls

```text
force_destroy = false
lifecycle.prevent_destroy = true
all public-access controls enabled
BucketOwnerEnforced object ownership
AES256 default server-side encryption
HTTPS-only bucket policy
```

### Recovery controls

```text
versioning enabled
365-day default noncurrent-version retention
configurable retention from 30 through 3650 days
one-day incomplete multipart-upload cleanup
```

S3 versioning preserves previous object versions, supporting recovery from accidental overwrite or deletion.

### Tags

```text
Project   = clouddoc
ManagedBy = terraform
Component = terraform-state
Scope     = account
```

## S3 Backend Contract

The application root declares:

```hcl
terraform {
  backend "s3" {}
}
```

This is a partial backend declaration.

The shared root does not commit:

```text
bucket
backend Region
credentials
AWS profile
role ARN
```

The committed backend key remains authoritative. No duplicate GitHub variable exists for the state key, and `CLOUDDOC_DEV_TERRAFORM_STATE_KEY` must not be introduced.

Environment backend files provide:

```text
state key
Region
encryption flag
S3-native lockfile flag
```

The bucket is supplied during initialization.

## S3-Native State Locking

Each environment backend file declares:

```hcl
use_lockfile = true
```

Terraform uses an S3 lock object associated with the state object.

Examples:

```text
clouddoc/dev/terraform.tfstate.tflock
clouddoc/staging/terraform.tfstate.tflock
clouddoc/prod/terraform.tfstate.tflock
```

The workflow never supplies:

```text
-lock=false
```

DynamoDB locking is not used.

The project intentionally follows the S3-native locking path rather than introducing a separate lock table.

## Terraform Version Contract

Both Terraform roots require:

```text
Terraform >= 1.10.0
Terraform < 2.0.0
```

The lower bound makes the selected lockfile workflow explicit.

The upper bound prevents an unreviewed major-version transition.

Both roots use:

```text
hashicorp/aws
version constraint = ~> 5.0
```

The bootstrap and application roots share the same reviewed provider dependency lock file.

## Environment Model

Approved environments:

```text
dev
staging
prod
```

Environment selection is explicit.

It does not depend on Terraform workspaces.

### Variable files

```text
infra/terraform/environments/dev.tfvars
infra/terraform/environments/staging.tfvars
infra/terraform/environments/prod.tfvars
```

Each file declares:

```text
aws_region
project_name
environment
```

Current values:

| Environment | Project | Region |
| --- | --- | --- |
| dev | clouddoc | us-east-1 |
| staging | clouddoc | us-east-1 |
| prod | clouddoc | us-east-1 |

The files contain no credentials or expected account ID.

### Backend files

```text
infra/terraform/environments/dev.s3.tfbackend
infra/terraform/environments/staging.s3.tfbackend
infra/terraform/environments/prod.s3.tfbackend
```

Each file declares exactly:

```text
key
region
encrypt
use_lockfile
```

### State keys

```text
dev     → clouddoc/dev/terraform.tfstate
staging → clouddoc/staging/terraform.tfstate
prod    → clouddoc/prod/terraform.tfstate
```

The workflow rejects a backend key that does not match:

```text
{project_name}/{environment}/terraform.tfstate
```

### Environment schema protection

The workflow rejects committed fields such as:

```text
bucket
profile
role_arn
dynamodb_table
expected_aws_account_id
```

This keeps deployment identity and backend ownership as execution inputs rather than repository configuration.

## AWS Account Guard

The application Terraform root exposes:

```hcl
variable "expected_aws_account_id" {
  type      = string
  default   = null
  nullable  = true
}
```

When supplied, the AWS provider uses:

```hcl
allowed_account_ids = [var.expected_aws_account_id]
```

Offline tests omit the value.

Authenticated operations require:

```text
CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID
```

The workflow propagates this value as:

```text
TF_VAR_expected_aws_account_id
```

The provider then rejects an unexpected AWS account.

The workflow masks the account in operator-facing output:

```text
Expected AWS account: ********9012
```

## State Bucket and Account Binding

Authenticated operations require:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID
```

The workflow requires the bucket name to match:

```text
{project_name}-{expected_account_id}-terraform-state
```

Example:

```text
project              = clouddoc
expected account     = 123456789012
required state bucket = clouddoc-123456789012-terraform-state
```

A syntactically valid bucket for another account is rejected before Terraform starts.

This creates two independent safeguards:

```text
workflow bucket/account binding
+
AWS provider allowed_account_ids
```

## Authentication Boundary

The workflow does not manage AWS credentials.

It does not read or print:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
```

Authentication remains external.

Supported authenticated modes now divide into three execution patterns:

```text
ambient
    local approved operation with plan and apply role ARNs absent

plan
    backend assumes clouddoc-dev-terraform-state
    provider assumes clouddoc-dev-terraform-plan
    apply role must be absent

deploy
    backend assumes clouddoc-dev-terraform-state
    provider assumes clouddoc-dev-terraform-apply
    plan role must be absent
```

Repository source already implements the runtime contracts for separate backend and provider role assumption. The permissionless identity roles remain authentication only; they do not hold plan, state, or apply permissions directly.

In source, the state role trusts exactly two approved identity principals:

```text
clouddoc-dev-github-identity
clouddoc-dev-github-deploy-identity
```

State permissions remain unchanged. State and provider roles remain independent. Plan uses state + plan roles. Deploy uses state + apply roles. `dev-deploy` is separate from `dev`. Environment reviewers remain future-compatible. The dual-identity state-role trust is deployed and operationally verified for `dev`.

The repository does not commit credential values.

The AWS CLI is not required for the workflow implementation or automated tests.

It may later be used as an operator convenience for identity inspection.

## Terraform Metadata Isolation

Terraform retains backend and provider metadata between commands.

CloudDoc stores this metadata separately per environment:

```text
infra/terraform/.terraform-data/dev
infra/terraform/.terraform-data/staging
infra/terraform/.terraform-data/prod
infra/terraform/.terraform-data/offline
```

The bootstrap offline path uses:

```text
infra/bootstrap/terraform-state/.terraform-data/offline
```

`TF_DATA_DIR` points Terraform to the selected directory.

The same environment directory is used consistently across:

```text
init
plan
show
apply
output
```

This prevents one environment initialization from overwriting another environment's backend metadata.

All `.terraform-data` directories are ignored by Git.

## Operator Workflow

Entry point:

```text
scripts/terraform_workflow.py
```

The script uses only the Python standard library.

Supported commands:

```text
offline-check
init
plan
show-plan
apply
output
```

Unsupported commands:

```text
destroy
force-unlock
state migration
workspace selection
direct apply from configuration
```

## Offline Check

Command:

```powershell
python scripts/terraform_workflow.py offline-check
```

Application root operations:

```text
terraform init -backend=false -lockfile=readonly -input=false
terraform fmt -check -recursive
terraform validate
terraform test
```

Bootstrap root operations:

```text
terraform init -backend=false -lockfile=readonly -input=false
terraform fmt -check -recursive
terraform validate
terraform test
```

Expected Terraform tests:

```text
application root → 29 passed
bootstrap root   → 4 passed
```

No AWS credentials or backend bucket are required.

## Remote Initialization

Command:

```powershell
python scripts/terraform_workflow.py init --environment dev
```

Required runtime inputs:

```powershell
$env:CLOUDDOC_TERRAFORM_STATE_BUCKET = "clouddoc-123456789012-terraform-state"
$env:CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID = "123456789012"
```

Conceptual Terraform command:

```text
terraform init
    -input=false
    -reconfigure
    -lockfile=readonly
    -backend-config=environments/dev.s3.tfbackend
    -backend-config=bucket=clouddoc-123456789012-terraform-state
```

The workflow blocks initialization when nonempty local application state is detected.

## Plan Workflow

Command:

```powershell
python scripts/terraform_workflow.py plan --environment dev
python scripts/terraform_workflow.py plan --environment dev --output-directory <approved-path>
```

The optional `--output-directory` flag allows plan output to be redirected outside the repository, including runner-temporary locations for the manual GitHub workflow.

Before planning, the workflow validates:

```text
selected environment
tfvars schema
backend schema
environment value
project name
Region consistency
canonical state key
encrypt = true
use_lockfile = true
state bucket syntax
state bucket/account binding
expected account ID
absence of local application state
Lambda ZIP presence
Lambda checksum presence
Lambda artifact SHA-256
```

The workflow then initializes the backend and runs a saved plan.

Conceptual command:

```text
terraform plan
    -input=false
    -lock-timeout=5m
    -detailed-exitcode
    -var-file=environments/dev.tfvars
    -out=artifacts/terraform/dev/clouddoc.tfplan
```

Approved detailed exit codes:

```text
0 → plan completed with no proposed changes
2 → plan completed with proposed changes
```

Other exit codes fail the workflow.

## Saved-Plan Directory

Plans are environment-scoped:

```text
artifacts/terraform/dev/clouddoc.tfplan
artifacts/terraform/staging/clouddoc.tfplan
artifacts/terraform/prod/clouddoc.tfplan
```

The entire `artifacts/` directory is ignored by Git.

Plans are not portable approval documents.

They remain local operational artifacts bound to:

```text
Terraform version
provider selections
backend initialization
configuration
variable inputs
environment
account
state bucket
state key
```

## Plan Integrity Manifest

Each saved plan receives a JSON manifest:

```text
artifacts/terraform/{environment}/clouddoc.tfplan.json
```

The manifest contains:

```text
environment
project_name
aws_region
state_bucket
state_key
expected_aws_account_id
terraform_data_dir
tfvars_file
backend_file
plan_file
plan_sha256
terraform_exit_code
```

The manifest is written atomically.

Its schema is strict.

The manifest is not a cryptographic signature or external attestation.

It is a local integrity and binding guard.

## Show Plan

Command:

```powershell
python scripts/terraform_workflow.py show-plan --environment dev
```

The workflow requires:

```text
saved plan exists
manifest exists
manifest environment matches
plan SHA-256 matches
```

The backend is not reinitialized merely to display the saved plan.

## Apply Workflow

Command:

```powershell
python scripts/terraform_workflow.py apply `
  --environment dev `
  --confirm-environment dev
```

The repeated environment confirmation is mandatory.

Before applying, the workflow validates:

```text
confirmation matches selection
environment files remain valid
runtime bucket/account inputs remain valid
Lambda artifact remains valid
saved plan exists
manifest exists
manifest schema is valid
manifest environment matches
manifest project matches
manifest Region matches
manifest bucket matches
manifest state key matches
manifest account matches
manifest file paths match
plan SHA-256 matches
```

The workflow reinitializes the selected backend and applies only:

```text
artifacts/terraform/{environment}/clouddoc.tfplan
```

Conceptual command:

```text
terraform apply
    -input=false
    -lock-timeout=5m
    artifacts/terraform/dev/clouddoc.tfplan
```

The workflow does not add:

```text
-auto-approve
-lock=false
```

Terraform does not ask for a second configuration approval when a saved plan is supplied.

Review occurs before the apply command.

## Output Workflow

Command:

```powershell
python scripts/terraform_workflow.py output --environment dev
```

JSON form:

```powershell
python scripts/terraform_workflow.py output `
  --environment dev `
  --json
```

The workflow initializes the selected environment backend and applies the expected-account guard before reading outputs.

## Local-State Migration Guard

The workflow inspects:

```text
infra/terraform/terraform.tfstate
infra/terraform/terraform.tfstate.backup
infra/terraform/terraform.tfstate.d/
```

A nonempty local state or workspace-state directory blocks remote initialization.

The script never executes:

```text
terraform init -migrate-state
```

A future migration requires:

```text
state backup
resource inventory
target bucket verification
target key verification
AWS account verification
manual approval
migration execution
post-migration state comparison
```

The current project has not approved an authoritative real AWS application deployment from local state.

## Lock Contention

Remote plan and apply use:

```text
-lock-timeout=5m
```

Terraform waits for the selected state lock.

If the lock remains unavailable, the command fails.

The workflow does not automatically execute:

```text
terraform force-unlock
```

A stale lock requires operator investigation and explicit handling.

## Lambda Artifact Guard

Real planning and applying require:

```text
artifacts/lambda/clouddoc-app.zip
artifacts/lambda/clouddoc-app.sha256
```

The workflow validates:

```text
ZIP exists
checksum exists
checksum file references the expected ZIP
digest is a lowercase 64-character SHA-256
actual ZIP digest matches
```

The workflow does not build the artifact.

Packaging remains owned by:

```text
make lambda-package-check
```

This separates:

```text
artifact creation
from
infrastructure planning
```

## Failure Modes

### Missing runtime inputs

Behavior:

```text
workflow exits with code 1
Terraform is not executed
```

### Unsupported environment

Behavior:

```text
argument parser rejects the value
```

### Environment mismatch

Example:

```text
selected environment = dev
tfvars environment   = prod
```

Behavior:

```text
workflow rejects before Terraform
```

### Region mismatch

Example:

```text
tfvars Region  = us-east-1
backend Region = eu-west-1
```

Behavior:

```text
workflow rejects
```

### State-key mismatch

Example:

```text
selected environment = prod
state key             = clouddoc/dev/terraform.tfstate
```

Behavior:

```text
workflow rejects
```

### Encryption disabled

Behavior:

```text
workflow rejects
```

### Lockfile disabled

Behavior:

```text
workflow rejects
```

### Bucket/account mismatch

Behavior:

```text
workflow rejects before Terraform
```

### Wrong authenticated AWS account

Behavior:

```text
AWS provider allowed_account_ids rejects provider operation
```

### Local state detected

Behavior:

```text
workflow rejects automatic migration
```

### Lambda artifact missing

Behavior:

```text
plan and apply are rejected
```

### Checksum mismatch

Behavior:

```text
plan and apply are rejected
```

### Terraform plan failure

Behavior:

```text
no valid manifest is retained
workflow exits with code 1
```

### Plan altered after planning

Behavior:

```text
SHA-256 validation fails
apply is rejected
```

### Manifest altered

Behavior:

```text
strict schema or binding validation fails
apply is rejected
```

### Wrong apply confirmation

Behavior:

```text
workflow rejects before reading environment or AWS inputs
```

### State lock unavailable

Behavior:

```text
Terraform waits up to five minutes
command fails without bypassing locking
```

### State bucket missing

Behavior:

```text
terraform init fails
no application plan is created
```

## Security Boundaries

```text
state and plan files remain outside Git
credentials remain outside committed files
backend files contain no credentials
tfvars files contain no credentials
expected account ID is supplied at execution time
account ID is masked in summaries
subprocess commands use argument arrays
shell interpolation is not used
automatic state migration is forbidden
direct apply from configuration is unavailable
locking cannot be disabled by the workflow
destroy is not exposed
```

State may contain sensitive infrastructure values.

Access to the state bucket must be treated as privileged.

## State Access IAM

State authorization exists through `clouddoc-dev-terraform-state`, which trusts exactly the plan identity and deployment identity. State permissions remain exact to the `dev` state and lock objects. The role is deployed and used by live Plan and Deploy.

Conceptual state-file permissions:

```text
s3:ListBucket
    → restricted state-key prefix

s3:GetObject
s3:PutObject
    → exact terraform.tfstate object
```

Conceptual lockfile permissions:

```text
s3:GetObject
s3:PutObject
s3:DeleteObject
    → exact terraform.tfstate.tflock object
```

These permissions are provisioned by the authorization bootstrap and operationally verified for `dev` remote Plan and Deploy. Authentication for identity proof remains separate from state authorization for remote plan or deploy.

## Cost Position

The state design uses:

```text
one account-scoped S3 bucket
small state objects
small lock objects
S3-managed encryption
version retention lifecycle
no DynamoDB lock table
no customer-managed KMS key
no cross-region replication
```

Cost drivers include:

```text
S3 object storage
retained noncurrent versions
S3 API requests
future audit logging
future replication if adopted
```

The state bucket lifecycle bounds noncurrent-version retention.

It does not remove the current state object.

## Automated Testing

### Bootstrap Terraform tests

Path:

```text
infra/bootstrap/terraform-state/tests/terraform_state.tftest.hcl
```

Runs:

```text
terraform_state_bucket_contract
terraform_state_security_controls
terraform_state_recovery_controls
terraform_state_destroy_protection
```

They validate:

```text
account-scoped naming
tags
public-access controls
ownership
encryption
versioning
lifecycle retention
multipart cleanup
outputs
force_destroy = false
```

Tests use:

```text
mock_provider "aws"
command = plan
```

They do not access AWS.

### Bootstrap static tests

Path:

```text
tests/unit/infrastructure/test_terraform_state_bootstrap.py
```

They validate:

```text
reviewed bootstrap file set
shared provider lock file
prevent_destroy
force_destroy = false
HTTPS-only policy
absence of remote backend in bootstrap
absence of DynamoDB locking
absence of static credentials
safe example variables
```

### Workflow unit tests

Path:

```text
tests/unit/scripts/test_terraform_workflow.py
```

The suite covers:

```text
real committed environment configurations
scalar configuration parser
schema rejection
state-key validation
Region validation
locking and encryption requirements
bucket validation
account validation
local-state detection
Lambda artifact validation
subprocess contract
TF_DATA_DIR isolation
backend initialization
bucket/account binding
plan manifest schema
plan integrity
plan command construction
apply confirmation
saved-plan-only apply
offline checks
approved CLI surface
forbidden-operation absence
concise CLI error handling
```

Subprocess calls are replaced with local test doubles.

The tests do not:

```text
invoke AWS
run a real plan
run a real apply
create state
create infrastructure
```

## Operational Commands

### Offline validation

```powershell
python scripts/terraform_workflow.py offline-check
```

### Bootstrap root formatting and validation

```powershell
terraform -chdir=infra/bootstrap/terraform-state fmt -check -recursive
terraform -chdir=infra/bootstrap/terraform-state validate
terraform -chdir=infra/bootstrap/terraform-state test
```

### Python workflow tests

```powershell
python -m pytest `
  tests/unit/infrastructure/test_terraform_state_bootstrap.py `
  tests/unit/scripts/test_terraform_workflow.py `
  -q
```

### Build the deployment artifact

```powershell
make lambda-package-check
```

### Initialize one real environment

```powershell
python scripts/terraform_workflow.py init --environment dev
```

### Plan one real environment

```powershell
python scripts/terraform_workflow.py plan --environment dev
```

### Review the plan

```powershell
python scripts/terraform_workflow.py show-plan --environment dev
```

### Apply the reviewed plan

```powershell
python scripts/terraform_workflow.py apply `
  --environment dev `
  --confirm-environment dev
```

## Real AWS Bootstrap Procedure

This procedure documents the one-time bootstrap sequence. For the current project account it has already been executed for the state substrate and `dev` backend initialization. Re-running it is not routine day-2 operation; prefer the controlled Plan and Deploy workflows for application mutations.

1. Choose and configure an approved AWS authentication method.
2. Verify the intended AWS account.
3. Copy the bootstrap example variables to ignored `terraform.tfvars`.
4. Initialize the bootstrap root.
5. Run formatting and validation.
6. Create a saved bootstrap plan.
7. Review the state bucket resources.
8. Apply only the reviewed plan.
9. Record the state bucket output.
10. Back up the bootstrap local state securely.
11. Wait for S3 versioning propagation before the first application-state write when applicable.
12. Configure the workflow runtime inputs.
13. Initialize the `dev` application backend.
14. Plan and review the `dev` environment.
15. Apply only after explicit approval.

Evidence of the resulting `dev` convergence and runtime proof:
[Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

## Intentionally Deferred

```text
staging infrastructure deployment
production infrastructure deployment
state migration
production authorization
cross-account deployment
team-based reviewers
multi-party approval
automatic rollback
pull-request plan publication
automatic destroy
automatic force-unlock
scheduled drift detection
automatic drift remediation
customer-managed KMS
cross-region replication
S3 Object Lock
CloudTrail S3 data events
state bucket access logging
HCP Terraform
Terraform Enterprise
Sentinel
persistent binary plans
policy-as-code platforms
multi-account platform foundation
centralized state-account model
```

These require explicit identity, approval, recovery, cost, and deployment contracts. The `dev` state substrate, remote backend, OIDC identities, authorization roles, and controlled Plan/Deploy path are already operationally verified.

## Reliability Invariants

```text
One AWS account has one CloudDoc state bucket.

One environment has one explicit state key.

One environment has one Terraform metadata directory.

Environment selection does not depend on workspaces.

Backend configuration contains no credentials.

Environment variable files contain no credentials.

Authenticated operations require an expected AWS account.

The state bucket must match the expected account.

The provider rejects an unexpected account.

Real plans require a verified Lambda artifact.

Plans are saved under environment-specific ignored paths.

Every saved plan receives a strict integrity manifest.

Apply accepts only the selected environment's saved plan.

Apply requires repeated environment confirmation.

The workflow does not disable state locking.

The workflow does not expose destroy.

The workflow does not migrate state automatically.

The application root does not manage its own backend bucket.

The bootstrap root does not manage application resources.

Automated tests remain independent from AWS.

Repository implementation remains distinct from real AWS deployment.
```

## Related Documentation

- [GitHub OIDC Trust Bootstrap](github-oidc-trust-bootstrap.md)
- [Terraform Plan Authorization](terraform-plan-authorization.md)
- [Terraform Deployment Authorization](terraform-deployment-authorization.md)
- [Terraform Plan Workflow Runbook](../operations/terraform-plan-workflow.md)
- [Terraform Deploy Workflow Runbook](../operations/terraform-deploy-workflow.md)
- [Terraform Authorization Bootstrap](../../infra/bootstrap/terraform-authorization/README.md)
- [ADR-026: Separate OIDC Authentication from Deployment Authorization](../adr/ADR-026-separate-oidc-authentication-from-deployment-authorization.md)
- [ADR-027: Separate Terraform State, Plan, and Apply Authorization](../adr/ADR-027-separate-terraform-state-plan-and-apply-authorization.md)
- [ADR-028: Controlled Single-Operator Terraform Deployment](../adr/ADR-028-controlled-single-operator-terraform-deployment.md)
- [Infrastructure CI Validation](infrastructure-ci-validation.md)
- [Terraform Infrastructure](../../infra/terraform/README.md)
- [Terraform State Bootstrap](../../infra/bootstrap/terraform-state/README.md)
- [Lambda Runtime Infrastructure](lambda-runtime-infrastructure.md)
- [Engineering Principles](engineering-principles.md)
- [ADR-025: Use S3-Native Locking and Explicit Environment State](../adr/ADR-025-use-s3-native-locking-and-explicit-environment-state.md)

## References

- [Terraform S3 backend](https://developer.hashicorp.com/terraform/language/backend/s3)
- [Terraform backend configuration](https://developer.hashicorp.com/terraform/language/backend)
- [Terraform state locking](https://developer.hashicorp.com/terraform/language/state/locking)
- [Terraform CLI environment variables](https://developer.hashicorp.com/terraform/cli/config/environment-variables)
- [Terraform init](https://developer.hashicorp.com/terraform/cli/commands/init)
- [Terraform plan](https://developer.hashicorp.com/terraform/cli/commands/plan)
- [Terraform apply](https://developer.hashicorp.com/terraform/cli/commands/apply)
- [AWS provider configuration](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [Amazon S3 Versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html)
