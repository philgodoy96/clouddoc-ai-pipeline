# Terraform Authorization Bootstrap

## Purpose

This Terraform root provisions the AWS authorization boundary used by the
CloudDoc `dev` Terraform plan workflow.

It owns two IAM roles:

```text
clouddoc-dev-terraform-state
clouddoc-dev-terraform-plan
```

The root does not own the GitHub OIDC provider, the permissionless GitHub
identity role, the Terraform state bucket, the application infrastructure, or
future deployment authorization.

## Architecture

```text
GitHub Actions
    |
    | GitHub OIDC
    v
clouddoc-dev-github-identity
    |
    | same-account sts:AssumeRole
    +-------------------------------+
    |                               |
    v                               v
clouddoc-dev-terraform-state   clouddoc-dev-terraform-plan
    |                               |
    | exact S3 state access         | AWS provider refresh reads
    | exact S3 lock access          | no state access
    | no application reads          | no resource mutation
```

The GitHub identity role remains permissionless. The target-role trust policies
name the exact identity-role ARN as their only AWS principal.

## Ownership Boundary

This root owns:

- the Terraform state-access IAM role;
- the Terraform plan-only IAM role;
- the trust policy for each role;
- the inline permission policy for each role;
- non-sensitive operational outputs for role and state identifiers.

This root does not own:

- the GitHub OIDC provider;
- the permissionless GitHub identity role;
- the S3 remote-state bucket;
- the CloudDoc application Terraform root;
- GitHub repository variables;
- GitHub Environments;
- the Terraform plan workflow;
- a Terraform apply role;
- deployment approval gates.

Related roots:

```text
infra/bootstrap/github-oidc/
    GitHub OIDC provider and permissionless identity role

infra/bootstrap/terraform-state/
    S3 remote-state bucket

infra/terraform/
    CloudDoc application infrastructure
```

## State Authorization Contract

The state role is:

```text
clouddoc-dev-terraform-state
```

It can be assumed only by:

```text
clouddoc-dev-github-identity
```

The role is restricted to the committed `dev` state contract:

```text
state object:
    clouddoc/dev/terraform.tfstate

lock object:
    clouddoc/dev/terraform.tfstate.tflock
```

### Bucket listing

The role receives:

```text
s3:ListBucket
```

on the exact remote-state bucket, restricted through `s3:prefix` to the exact
state and lock keys.

### State object

The role receives:

```text
s3:GetObject
s3:PutObject
```

on the exact state object.

It does not receive:

```text
s3:DeleteObject
```

on the state object.

### Lock object

The role receives:

```text
s3:GetObject
s3:PutObject
s3:DeleteObject
```

on the exact `.tflock` object.

The delete permission exists only for native S3 lock lifecycle management.

### Explicit exclusions

The state role cannot:

- access another environment state;
- list unrelated bucket prefixes;
- manage the state bucket;
- inspect application Lambda functions;
- inspect application DynamoDB tables;
- inspect application SQS queues;
- inspect application IAM roles;
- invoke application APIs.

The current state bucket uses S3-managed AES256 encryption. This root grants no
KMS permissions.

## Plan Authorization Contract

The plan role is:

```text
clouddoc-dev-terraform-plan
```

It can be assumed only by:

```text
clouddoc-dev-github-identity
```

The role contains an explicit read-only allowlist derived from the resource
types managed by:

```text
infra/terraform/
```

The current service families are:

- API Gateway V2;
- CloudWatch;
- CloudWatch Logs;
- DynamoDB;
- IAM;
- Lambda;
- S3 application-bucket configuration;
- SQS;
- STS caller identity.

The policy intentionally avoids:

- `AdministratorAccess`;
- `PowerUserAccess`;
- AWS-managed `ReadOnlyAccess`;
- wildcard action families;
- `iam:PassRole`;
- Lambda invocation;
- SQS message operations;
- DynamoDB item reads;
- Terraform state object access;
- resource mutation.

Some AWS control-plane read operations do not support resource-level
permissions. Those actions are isolated in service-specific statements with
explicit action names.

The policy is an initial least-privilege hypothesis. A real Terraform plan is
the operational proof. Any missing permission must be justified by a concrete
`AccessDenied` from provider refresh before the policy is expanded.

## Prerequisites

Required local tools:

```text
Terraform >= 1.10.0 and < 2.0.0
AWS provider ~> 5.0
AWS CLI
PowerShell
```

The operator must have temporary AWS credentials with permission to:

- create and update the two IAM roles;
- create and update their inline policies;
- read the existing identity role;
- call `sts:GetCallerIdentity`.

Long-lived AWS access keys are not required and should not be used.

The following infrastructure must already exist:

```text
GitHub OIDC provider
clouddoc-dev-github-identity
CloudDoc Terraform state bucket
```

## Configuration

Create a local ignored file:

```text
infra/bootstrap/terraform-authorization/terraform.tfvars
```

Use the example as the starting point:

```powershell
Copy-Item `
  "infra/bootstrap/terraform-authorization/terraform.tfvars.example" `
  "infra/bootstrap/terraform-authorization/terraform.tfvars"
```

Required values:

```hcl
aws_account_id = "REPLACE_WITH_12_DIGIT_AWS_ACCOUNT_ID"

terraform_state_bucket_name = "clouddoc-REPLACE_WITH_12_DIGIT_AWS_ACCOUNT_ID-terraform-state"
```

The remaining approved values have defaults:

```text
region:
    us-east-1

environment:
    dev

project:
    clouddoc

state key:
    clouddoc/dev/terraform.tfstate

identity role:
    clouddoc-dev-github-identity
```

Do not commit:

```text
terraform.tfvars
terraform.tfstate
terraform.tfstate.backup
saved Terraform plans
AWS credentials
```

## Initialize

From the repository root:

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  init `
  -backend=false `
  -input=false `
  -lockfile=readonly
```

This bootstrap intentionally uses local state and has no remote backend.

## Validate

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  fmt `
  -check `
  -recursive

terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  validate

terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  test
```

Repository contract tests:

```powershell
python -m pytest `
  "tests/unit/infrastructure/test_terraform_authorization_bootstrap.py" `
  -q
```

Full offline validation:

```powershell
python scripts/terraform_workflow.py offline-check
```

## Plan

Create a saved plan outside the repository:

```powershell
$PlanDirectory = Join-Path `
  $env:TEMP `
  "clouddoc-terraform-authorization"

$PlanPath = Join-Path `
  $PlanDirectory `
  "terraform-authorization.tfplan"

New-Item `
  -Path $PlanDirectory `
  -ItemType Directory `
  -Force |
  Out-Null
```

Generate the plan:

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  plan `
  -input=false `
  -out="$PlanPath"
```

Review the human-readable plan:

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  show `
  -no-color `
  "$PlanPath"
```

Expected initial resource shape:

```text
2 IAM roles
2 inline IAM role policies
4 managed resources total
```

No OIDC provider, identity role, managed IAM policy, policy attachment, or
deployment role should appear.

## Verify the Saved Plan

Record a SHA-256 digest next to the plan:

```powershell
$PlanHashPath = "$PlanPath.sha256"

$PlanHash = (
  Get-FileHash `
    $PlanPath `
    -Algorithm SHA256
).Hash.ToUpperInvariant()

Set-Content `
  -Path $PlanHashPath `
  -Value $PlanHash `
  -Encoding ascii
```

Before apply, recompute and compare the digest:

```powershell
$ReviewedHash = (
  Get-Content `
    $PlanHashPath `
    -Raw
).Trim().ToUpperInvariant()

$CurrentHash = (
  Get-FileHash `
    $PlanPath `
    -Algorithm SHA256
).Hash.ToUpperInvariant()

if ($ReviewedHash -ne $CurrentHash) {
  throw "The saved Terraform plan changed after review."
}
```

Do not regenerate the plan after approval. Apply the exact reviewed binary
plan.

## Apply

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  apply `
  -input=false `
  "$PlanPath"
```

Expected initial result:

```text
Resources: 4 added, 0 changed, 0 destroyed.
```

A saved-plan apply does not prompt for interactive approval because the plan
was reviewed and fixed before execution.

## Effective AWS Verification

Read the Terraform outputs:

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  output
```

Verify both roles exist:

```powershell
$StateRoleName = terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  output `
  -raw `
  terraform_state_role_name

$PlanRoleName = terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  output `
  -raw `
  terraform_plan_role_name
```

Inspect role metadata without exposing complete ARNs in shared logs:

```powershell
aws iam get-role `
  --role-name $StateRoleName

aws iam get-role `
  --role-name $PlanRoleName
```

Verify each role has exactly one inline policy:

```powershell
aws iam list-role-policies `
  --role-name $StateRoleName

aws iam list-role-policies `
  --role-name $PlanRoleName
```

Verify no managed policy is attached:

```powershell
aws iam list-attached-role-policies `
  --role-name $StateRoleName

aws iam list-attached-role-policies `
  --role-name $PlanRoleName
```

Expected attached-policy count:

```text
0
```

## State Backup

The bootstrap state contains AWS infrastructure identifiers and must remain
outside Git.

After every successful apply, create a protected backup:

```powershell
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

$BackupDirectory = Join-Path `
  $env:USERPROFILE `
  ".clouddoc\bootstrap-backups\terraform-authorization\$Timestamp"

New-Item `
  -Path $BackupDirectory `
  -ItemType Directory `
  -Force |
  Out-Null

$StatePath = Join-Path `
  "infra/bootstrap/terraform-authorization" `
  "terraform.tfstate"

$BackupStatePath = Join-Path `
  $BackupDirectory `
  "terraform.tfstate"

Copy-Item `
  $StatePath `
  $BackupStatePath `
  -Force
```

Verify the backup:

```powershell
$SourceHash = (
  Get-FileHash `
    $StatePath `
    -Algorithm SHA256
).Hash

$BackupHash = (
  Get-FileHash `
    $BackupStatePath `
    -Algorithm SHA256
).Hash

if ($SourceHash -ne $BackupHash) {
  throw "The Terraform authorization state backup is invalid."
}

Set-Content `
  -Path "$BackupStatePath.sha256" `
  -Value $BackupHash `
  -Encoding ascii
```

Do not place the backup inside the repository.

## GitHub Repository Variables

After the roles are provisioned, configure these repository variables:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN
```

These values are identifiers, not credentials.

The repository already uses:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
```

Do not create:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
CLOUDDOC_DEV_TERRAFORM_STATE_KEY
```

The state key remains versioned in:

```text
infra/terraform/environments/dev.s3.tfbackend
```

## Operational Verification

After the OIDC trust source is applied and the repository variables are
configured, run:

```text
Terraform Plan
```

from GitHub Actions on `main`.

The workflow must prove:

- exact GitHub workload context;
- exact eight-claim OIDC preflight;
- identity-role federation;
- state-role assumption by the S3 backend;
- plan-role assumption by the AWS provider;
- native S3 state locking;
- Lambda package integrity;
- real provider refresh;
- sanitized plan summary;
- deletion of temporary plan files;
- absence of any apply command.

## Authorization Failure Procedure

When the live plan fails with `AccessDenied`:

1. capture the exact AWS action;
2. confirm the action belongs to provider refresh;
3. confirm the action is read-only control-plane metadata;
4. determine whether resource-level scoping is supported;
5. update only the relevant service statement;
6. add a regression test;
7. repeat offline validation;
8. review and merge the correction;
9. apply the exact authorization-bootstrap change;
10. rerun the live plan.

Do not respond to a denied action by attaching:

```text
ReadOnlyAccess
PowerUserAccess
AdministratorAccess
service-wide wildcard actions
```

## Negative Authorization Evidence

The slice must also prove that:

- the identity role has no direct application or state permissions;
- the state role cannot inspect application resources;
- the plan role cannot read or write Terraform state;
- the plan role cannot mutate application resources.

Use safe IAM policy simulation or read-only denied calls. Do not intentionally
perform application mutations merely to prove denial.

## Recovery

### Lost local state

Do not import or recreate roles immediately.

Restore the latest verified backup:

```powershell
Copy-Item `
  "<verified-backup-path>\terraform.tfstate" `
  "infra/bootstrap/terraform-authorization/terraform.tfstate" `
  -Force
```

Recompute the hash and run:

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  plan `
  -input=false
```

Review the result before any apply.

### Unexpected drift

Do not apply automatically.

Inspect:

```powershell
terraform `
  -chdir=infra/bootstrap/terraform-authorization `
  plan `
  -input=false
```

Classify the drift as:

- approved infrastructure change;
- unauthorized manual change;
- stale local state;
- intentional external control.

Resolve ownership before applying.

### Stale lock or plan artifact

This root uses local state and does not use the application S3 lock.

Delete only temporary saved plans after review is complete. Never delete the
application state lock as part of this bootstrap procedure.

## Cleanup

After successful apply, effective-policy verification, and state backup:

```powershell
Remove-Item `
  $PlanPath, `
  $PlanHashPath `
  -Force
```

Confirm Git remains clean:

```powershell
git status --short
```

Local ignored files may remain, but no tracked file should change during
operational activation.

## Security Invariants

- The GitHub identity role remains permissionless.
- Each target role trusts only the exact identity-role ARN.
- No target role trusts GitHub OIDC directly.
- The state role is restricted to the exact state and lock objects.
- The state object cannot be deleted by the state role.
- The plan role cannot access Terraform state.
- The plan role contains no mutation permission.
- No AWS-managed broad policy is attached.
- No static AWS credential is stored in the repository or GitHub.
- No customer-managed KMS permission is included.
- Authorization expansion requires concrete evidence.

## Intentionally Deferred

The following are not owned by this bootstrap:

- Terraform apply authorization;
- deployment role;
- production roles;
- cross-account deployment;
- protected deployment approvals;
- plan artifact promotion;
- HCP Terraform;
- policy generation from CloudTrail.

These items require separate architecture and operational controls.