# Terraform Plan Workflow Runbook

## Purpose

This runbook describes how to prepare, execute, verify, and troubleshoot the
CloudDoc `dev` Terraform plan workflow.

The workflow performs a speculative plan only. It does not deploy
infrastructure.

## Verified operational baseline

For the current `dev` environment:

```text
GitHub OIDC authentication = deployed and verified
state and plan roles = deployed and verified
remote state = active
live Plan = operationally verified
value-free attestation = operationally verified
```

Evidence: [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

This runbook remains the actionable procedure for subsequent speculative plans.
Staging and production are not claimed as deployed.

## Workflow Files

Caller workflow:

```text
.github/workflows/terraform-plan.yml
```

Reusable workflow:

```text
.github/workflows/reusable-terraform-plan.yml
```

Manual workflow name:

```text
Terraform Plan
```

## Security Model

```text
GitHub Actions
    |
    | exact GitHub OIDC trust
    v
clouddoc-dev-github-identity
    |
    | temporary same-account role chaining
    +-------------------------------+
    |                               |
    v                               v
clouddoc-dev-terraform-state   clouddoc-dev-terraform-plan
    |                               |
    | S3 backend access             | provider refresh access
    | state and lock only           | read-only infrastructure
```

The GitHub identity role is permissionless.

The S3 backend assumes the state role.

The AWS provider assumes the plan role.

The workflow never receives long-lived AWS credentials.

## Preconditions

The workflow is ready only when all of the following are true:

- the source branch has been merged into `main`;
- GitHub OIDC trust includes the reusable Terraform plan workflow;
- the identity role remains permissionless;
- the state and plan roles exist in AWS;
- both target roles trust the exact identity-role ARN;
- the Terraform remote-state bucket exists;
- the `dev` GitHub Environment exists;
- the `dev` Environment allows only `main`;
- required repository variables exist;
- no AWS static credential secret exists;
- CI is green on `main`.

## Required Repository Variables

Existing identity variables:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
```

Terraform plan variables:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN
```

Do not create:

```text
CLOUDDOC_DEV_TERRAFORM_STATE_KEY
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
```

The state key remains committed in:

```text
infra/terraform/environments/dev.s3.tfbackend
```

## Source Contracts

Environment:

```text
dev
```

Allowed repository:

```text
philgodoy96/clouddoc-ai-pipeline
```

Allowed ref:

```text
refs/heads/main
```

Allowed event:

```text
workflow_dispatch
```

Region:

```text
us-east-1
```

Reusable workflow trust:

```text
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main
```

State key:

```text
clouddoc/dev/terraform.tfstate
```

Lock object:

```text
clouddoc/dev/terraform.tfstate.tflock
```

## Pre-Run Verification

Confirm the repository default branch:

```powershell
gh repo view `
  --json nameWithOwner,defaultBranchRef
```

Confirm the workflow exists:

```powershell
gh workflow list
```

Confirm repository-variable names without printing values:

```powershell
gh variable list `
  --json name,updatedAt
```

Confirm there are no repository secrets containing static AWS credentials:

```powershell
gh secret list `
  --json name,updatedAt
```

Confirm the `dev` Environment exists:

```powershell
gh api `
  "repos/philgodoy96/clouddoc-ai-pipeline/environments/dev"
```

Do not paste account IDs, complete ARNs, bucket names, or numeric GitHub IDs
into public logs or documentation.

## Dispatch

From a clean local checkout of `main`:

```powershell
git switch main
git pull --ff-only origin main
git status --short
```

Dispatch:

```powershell
$Repository = "philgodoy96/clouddoc-ai-pipeline"
$Workflow = "terraform-plan.yml"
$DispatchStartedAt = [DateTime]::UtcNow

gh workflow run `
  $Workflow `
  --ref main `
  --repo $Repository
```

Wait briefly for GitHub to register the run:

```powershell
Start-Sleep -Seconds 5
```

Locate the new run:

```powershell
$Run = @(
  gh run list `
    --repo $Repository `
    --workflow $Workflow `
    --branch main `
    --event workflow_dispatch `
    --limit 10 `
    --json "databaseId,status,conclusion,createdAt,url" |
  ConvertFrom-Json |
  Where-Object {
    ([DateTime]$_.createdAt) -ge `
      $DispatchStartedAt.AddMinutes(-1)
  } |
  Sort-Object createdAt -Descending |
  Select-Object -First 1
)

if ($Run.Count -ne 1) {
  throw "Could not identify the Terraform Plan workflow run."
}

$RunId = [string]$Run.databaseId
```

Watch the run:

```powershell
gh run watch `
  $RunId `
  --repo $Repository `
  --compact `
  --exit-status
```

When the run fails, retrieve only failed-step logs:

```powershell
gh run view `
  $RunId `
  --repo $Repository `
  --log-failed
```

Do not copy complete logs into public issues without reviewing them for
identifiers.

## Expected Step Order

```text
Validate trusted workflow context
Validate GitHub OIDC token claims
Configure temporary AWS credentials
Verify assumed AWS identity
Check out repository
Verify repository checkout
Set up Python
Install project
Set up Terraform
Build Lambda package
Verify Lambda package
Create and summarize Terraform plan
Verify Terraform plan cleanup
```

## Expected Success Markers

The run should contain:

```text
GitHub OIDC token claim contract verified.
AWS OIDC identity federation verified.
Repository checkout verified.
Sanitized Terraform plan summary published.
Temporary Terraform plan cleanup verified.
```

A successful plan may report either:

```text
No managed-resource changes
```

or:

```text
Changes detected
```

Both are valid plan outcomes.

A change-bearing plan is not a deployment.

## Step Summary Contract

The GitHub step summary may contain only:

- overall plan result;
- create count;
- update count;
- delete count;
- replacement count;
- no-op count;
- managed resource type;
- sanitized Terraform resource address;
- statement that the plan is speculative.

It must not contain:

- resource values;
- policy JSON;
- environment variables;
- state contents;
- account IDs;
- role ARNs;
- bucket names;
- Lambda environment values;
- credentials;
- OIDC tokens.

## Temporary Artifact Contract

The workflow creates temporary plan files only under:

```text
$RUNNER_TEMP/clouddoc-terraform-plan
```

Expected transient files include:

```text
clouddoc.tfplan
clouddoc.tfplan.json
terraform-show.json
```

The workflow must remove the complete directory before the job finishes.

The files are never:

- uploaded as GitHub artifacts;
- cached;
- committed;
- attached to a release;
- passed to another job;
- reused by a future deployment workflow.

## Successful Run Verification

Read structured run metadata:

```powershell
$RunResult = (
  gh run view `
    $RunId `
    --repo $Repository `
    --json "status,conclusion,headBranch,event,url,jobs"
) | ConvertFrom-Json
```

Verify the run boundary:

```powershell
if ($RunResult.status -ne "completed") {
  throw "Terraform Plan is not complete."
}

if ($RunResult.conclusion -ne "success") {
  throw "Terraform Plan did not succeed."
}

if ($RunResult.headBranch -ne "main") {
  throw "Terraform Plan did not run from main."
}

if ($RunResult.event -ne "workflow_dispatch") {
  throw "Terraform Plan was not manually dispatched."
}
```

Validate required step conclusions through structured metadata rather than
brittle raw-log counting.

Required successful steps:

```text
Validate trusted workflow context
Validate GitHub OIDC token claims
Configure temporary AWS credentials
Verify assumed AWS identity
Verify repository checkout
Build Lambda package
Verify Lambda package
Create and summarize Terraform plan
Verify Terraform plan cleanup
```

## Failure Classification

Classify failures before changing code or IAM.

### Trusted context failure

Symptoms:

```text
Unexpected GitHub repository
Terraform plan must run from refs/heads/main
Terraform plan must be started manually
role or bucket input mismatch
```

Response:

- verify caller ref;
- verify repository variables;
- verify exact role names;
- verify exact bucket naming;
- do not weaken the context validation.

### OIDC claim preflight failure

Symptoms:

```text
OIDC claim <name>: mismatch
GitHub OIDC token claim contract failed
```

Response:

- inspect sanitized expected and actual claim shapes;
- verify `job.workflow_ref`;
- verify repository and owner numeric-ID claim behavior;
- compare the source contract with the effective GitHub token;
- do not add wildcards;
- do not bypass the preflight.

AWS IAM remains authoritative for cryptographic token and trust validation.

### Identity-role federation failure

Symptoms:

```text
Not authorized to perform sts:AssumeRoleWithWebIdentity
```

Response:

- confirm the OIDC trust source has been applied;
- inspect the effective AWS trust policy;
- verify all eight exact claims;
- verify the plan reusable workflow is one of exactly two values;
- verify no source-only change remains unapplied;
- verify the GitHub `dev` Environment is active;
- do not attach an authorization policy to the identity role.

### State-role assumption failure

Symptoms:

```text
sts:AssumeRole denied
backend initialization failed
```

Response:

- inspect the state role trust policy;
- confirm the exact identity-role ARN principal;
- confirm both roles are in the same AWS account;
- verify session duration;
- verify account-level explicit denies, permission boundaries, or SCPs;
- do not grant state access to the identity role as a shortcut.

### State bucket or state object denial

Symptoms:

```text
s3:ListBucket denied
s3:GetObject denied
s3:PutObject denied
lock file access denied
```

Response:

- verify the runtime bucket matches the bootstrap bucket;
- verify the committed state key;
- verify `s3:prefix` contains the exact state and lock keys;
- verify state-object and lock-object resources are not reversed;
- verify `DeleteObject` exists only for the lock object;
- do not broaden access to the whole bucket.

### State lock contention

Symptoms:

```text
Error acquiring the state lock
```

Response:

- identify the active Terraform operation;
- wait for the active operation to complete;
- confirm no abandoned workflow remains;
- inspect lock ownership before any manual action;
- never disable locking;
- never delete the lock merely to make the workflow pass.

Manual lock recovery requires separate evidence that no writer is active.

### Plan-role assumption failure

Symptoms:

```text
sts:AssumeRole denied
provider configuration failed
```

Response:

- inspect the plan role trust;
- verify the exact identity-role ARN principal;
- verify the provider received the exact plan-role ARN;
- verify account matching;
- do not give the state role application access.

### Missing provider read permission

Symptoms:

```text
AccessDenied
not authorized to perform <read-action>
```

Response:

1. record the exact action;
2. identify the Terraform resource refresh that requires it;
3. confirm the action is read-only control-plane metadata;
4. consult the AWS service authorization reference;
5. determine whether resource-level scoping is supported;
6. add one exact action to one service-specific statement;
7. add regression tests;
8. rerun offline validation;
9. review and merge;
10. apply the exact authorization-bootstrap update;
11. rerun the live plan.

Never respond by attaching:

```text
ReadOnlyAccess
PowerUserAccess
AdministratorAccess
Get*
List*
Describe*
service:*
```

### Lambda package failure

Symptoms:

```text
package missing
checksum mismatch
non-deterministic package
```

Response:

- inspect `make lambda-package`;
- inspect `make lambda-package-check`;
- verify the locked Lambda requirements;
- reproduce locally;
- do not bypass package verification.

### Terraform plan failure

Symptoms:

```text
terraform plan returned an error
```

Response:

- distinguish configuration failure from authorization failure;
- verify application Terraform validation;
- verify the real state is readable;
- verify provider role access;
- inspect only failed-step logs;
- do not run apply.

### Summary failure

Symptoms:

```text
Terraform plan summary failed
unsupported actions
malformed JSON
```

Response:

- preserve fail-closed behavior;
- inspect the Terraform JSON schema shape locally with sanitized test data;
- add a focused unit test;
- do not print raw plan JSON into logs.

### Cleanup failure

Symptoms:

```text
Terraform plan cleanup failed
Temporary Terraform plan files remain on the runner
```

Response:

- treat the run as failed even if the plan succeeded;
- inspect shell cleanup logic;
- preserve the original plan status when cleanup succeeds;
- never upload the files for debugging;
- add a regression test before rerunning.

## IAM Expansion Review Template

Every proposed plan-policy expansion must answer:

```text
Denied AWS action:
Terraform resource requiring it:
Provider refresh reason:
Read-only control-plane confirmation:
Resource-level scoping supported:
Proposed resource scope:
Why existing actions are insufficient:
Regression test:
```

An incomplete review is not approval.

## Negative Authorization Verification

After a successful live plan, collect safe evidence for these boundaries:

```text
identity role:
    cannot access application APIs directly

state role:
    cannot inspect application resources

plan role:
    cannot access the Terraform state object

plan role:
    cannot mutate application resources
```

Preferred mechanisms:

- IAM policy simulation;
- read-only calls expected to fail;
- effective-policy inspection.

Do not intentionally mutate application infrastructure merely to prove denial.

## Evidence Record

Record:

```text
workflow run ID
workflow conclusion
branch
event
environment
claim preflight conclusion
identity federation conclusion
state backend initialization conclusion
provider refresh conclusion
plan result
summary publication conclusion
cleanup conclusion
negative authorization results
```

Do not record:

```text
complete account ID
complete role ARN
complete bucket name
numeric GitHub IDs
state contents
saved plan hash
OIDC token
AWS credentials
```

## Rerun Policy

A failed run may be rerun only after:

- the failure is classified;
- the source or AWS configuration change is identified;
- the corrective change is reviewed;
- required Terraform bootstrap changes are applied;
- repository variables are verified;
- eventual-consistency delay is considered for IAM updates.

Do not repeatedly rerun an unchanged authorization failure.

## Concurrency

The caller uses a non-cancelling concurrency group derived from the branch.

A new plan does not cancel a running plan.

Native S3 lock-file handling remains the state-level concurrency mechanism.

Do not disable either guard to increase throughput.

## Rollback

This workflow does not deploy infrastructure, so it has no application
rollback.

When a source change breaks planning:

1. revert the source change through Git;
2. restore the previous tested workflow contract;
3. apply a trust-policy rollback only when the trusted workflow set changed;
4. apply an authorization-policy rollback only through a reviewed Terraform
   saved plan;
5. rerun the plan from `main`.

Do not edit IAM manually as the default rollback mechanism.

## Intentionally Deferred

This runbook does not cover:

- Terraform apply;
- deployment approvals;
- production planning;
- cross-account deployment;
- saved-plan promotion;
- HCP Terraform;
- automated pull-request plans;
- rollback of application resources.

Those capabilities require separate design and operational runbooks.