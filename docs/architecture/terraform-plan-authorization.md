# Terraform Plan Identity and State Authorization

## Status

- **Decision state:** Approved
- **Repository implementation:** Implemented
- **AWS activation:** Pending
- **Live plan verification:** Pending
- **Environment:** `dev`
- **Last updated:** 2026-07-28


## Implementation Status

The approved architecture is now implemented in repository source through:

- authorization bootstrap in `infra/bootstrap/terraform-authorization/`;
- application provider and backend role wiring in `infra/terraform/` and `scripts/terraform_workflow.py`;
- sanitized plan-summary utility in `scripts/summarize_terraform_plan.py`;
- value-free plan attestation utility in `scripts/terraform_plan_attestation.py`;
- GitHub OIDC exact two-workflow allowlist source in `infra/bootstrap/github-oidc/`;
- caller workflow in `.github/workflows/terraform-plan.yml`;
- reusable workflow in `.github/workflows/reusable-terraform-plan.yml`;
- offline and static tests covering IAM, workflow, summary, and attestation contracts;
- operations runbook in [Terraform Plan Workflow Runbook](../operations/terraform-plan-workflow.md).

These artifacts are implemented in source only. AWS activation and live operational proof remain pending. Controlled deployment regenerates rather than downloading a binary plan; see [Terraform Deployment Authorization](terraform-deployment-authorization.md), [Terraform Deploy Workflow Runbook](../operations/terraform-deploy-workflow.md), and [ADR-027](../adr/ADR-027-separate-terraform-state-plan-and-apply-authorization.md).

## Purpose

This document defines how GitHub Actions will execute a real Terraform plan
against the CloudDoc `dev` environment without receiving deployment
authorization and without combining Terraform state access with application
infrastructure access.

The design extends the existing GitHub OIDC authentication boundary. It does
not replace it.

## Business Context

CloudDoc AI Pipeline provisions its AWS infrastructure through Terraform. The
application Terraform root uses an S3 remote backend and manages event-driven
document-processing resources across S3, SQS, Lambda, DynamoDB, API Gateway,
CloudWatch, and IAM.

The repository already proves GitHub-to-AWS authentication through an exact
OIDC trust contract and a permissionless identity role. The next engineering
requirement is to let a controlled GitHub Actions workflow inspect the real
`dev` infrastructure and produce a speculative Terraform plan.

A plan workflow needs two fundamentally different capabilities:

1. Access to the exact Terraform state and lock objects.
2. Read-only access to the AWS resources refreshed by the Terraform provider.

Combining those capabilities in one role would make the state boundary harder
to reason about and would create an unnecessarily broad credential. This design
separates them.

## Current Repository Facts

The design is grounded in the current repository:

- Application Terraform root: `infra/terraform/`
- Backend type: partial S3 backend
- Dev backend file:
  `infra/terraform/environments/dev.s3.tfbackend`
- Dev state key: `clouddoc/dev/terraform.tfstate`
- Dev lock object:
  `clouddoc/dev/terraform.tfstate.tflock`
- Native S3 locking: enabled through `use_lockfile = true`
- DynamoDB locking: absent
- Backend encryption: S3-managed AES256
- State bucket input: runtime value in
  `CLOUDDOC_TERRAFORM_STATE_BUCKET`
- AWS provider role assumption: implemented through `terraform_plan_role_arn`
- Backend role assumption: implemented through runtime backend role assumption
- Lambda package build: `make lambda-package`
- Lambda package verification: `make lambda-package-check`
- Current OIDC identity role:
  `clouddoc-dev-github-identity`
- Current identity-role permission policies: none
- Trusted reusable workflows in source:
  `reusable-aws-identity.yml@refs/heads/main`
  `reusable-terraform-plan.yml@refs/heads/main`

## Goals

The slice must:

- preserve the permissionless GitHub identity role;
- introduce separate state and plan authorization roles;
- restrict state access to the exact `dev` state and lock objects;
- restrict provider access to read operations required by the real Terraform
  resource graph;
- execute only from `main`;
- use the GitHub `dev` Environment;
- use temporary OIDC credentials only;
- execute a real remote-state-backed Terraform plan;
- publish a deterministic summary containing actions and counts only;
- keep binary and JSON plan files inside the runner temporary directory;
- delete temporary plan files before the job finishes;
- fail closed on missing authorization;
- produce positive and negative authorization evidence.

## Non-Goals

This slice does not implement:

- `terraform apply` in the plan workflow;
- promotion of the plan identity into deployment authorization;
- promotion of the plan role into mutation authorization;
- production authorization;
- pull-request AWS access;
- feature-branch AWS access;
- automatic IAM permission expansion;
- binary plan artifact upload;
- full plan JSON artifact upload;
- persistent binary plan storage;
- cross-account deployment;
- HCP Terraform;
- AWS-managed `ReadOnlyAccess`;
- administrator access;
- static AWS credentials;
- automatic rollback.

Controlled deployment is a separate source-implemented boundary documented in
[Terraform Deployment Authorization](terraform-deployment-authorization.md) and
[ADR-028](../adr/ADR-028-controlled-single-operator-terraform-deployment.md).
Live plan activation remains pending before that path may be proven.

## Actors

### Human reviewer

Reviews architecture, IAM policies, Terraform plans, workflow summaries, and
operational evidence.

### GitHub Actions caller workflow

Provides the manual entry point and restricts execution to the approved
repository and `main` branch.

### Reusable Terraform plan workflow

Owns workload-context validation, OIDC claim validation, temporary credential
acquisition, checkout, packaging, Terraform execution, summary generation, and
cleanup.

### GitHub OIDC provider

Issues the short-lived workload identity token consumed by AWS STS.

### Permissionless identity role

Authenticates the approved GitHub workload. It grants no application, state,
or deployment permissions.

### Terraform state role

Authorizes access only to the exact `dev` state and lock objects in the remote
state bucket.

### Terraform plan role

Authorizes the AWS provider to inspect the current `dev` infrastructure. It
does not authorize state access or resource mutation.

### Terraform S3 backend

Reads and writes remote state and manages the native S3 lock file through the
state role.

### Terraform AWS provider

Refreshes managed resources and evaluates the speculative plan through the
plan role.

## Authorization Model

```text
GitHub Actions
    |
    | OIDC: AssumeRoleWithWebIdentity
    v
clouddoc-dev-github-identity
    |
    | same-account sts:AssumeRole
    +-------------------------------+
    |                               |
    v                               v
clouddoc-dev-terraform-state   clouddoc-dev-terraform-plan
    |                               |
    | exact S3 state access         | provider read operations
    | exact S3 lock access          | no state access
    | no application reads          | no application mutation
    +---------------+---------------+
                    |
                    v
            speculative plan only
```

The target roles name the exact identity-role ARN in their trust policies.

The design intentionally relies on a same-account resource-based trust grant
instead of attaching an `sts:AssumeRole` permission policy to the identity
role. AWS authorization rules still allow explicit denies, permission
boundaries, session policies, and service control policies to restrict the
session. Operational activation must prove the assumption chain before this
slice is considered complete.

Role-chained sessions use a 900-second duration. This remains below the AWS
one-hour role-chaining limit and reduces the lifetime of temporary
authorization credentials.

## Authentication Boundary

The identity role remains responsible only for proving which GitHub workload
is running.

Its OIDC trust continues to require exact `StringEquals` conditions for:

- `aud`
- `sub`
- `repository`
- `repository_id`
- `repository_owner_id`
- `ref`
- `environment`
- `job_workflow_ref`

The allowed `job_workflow_ref` values will become exactly:

```text
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main
```

No wildcard, pull-request ref, feature branch, or third reusable workflow is
allowed.

The identity role must continue to have:

```text
attached managed policies: 0
inline policies:           0
```

## State Authorization Boundary

The state role is:

```text
clouddoc-dev-terraform-state
```

It may be assumed only by:

```text
clouddoc-dev-github-identity
```

### Bucket permission

The role receives `s3:ListBucket` on the exact backend bucket with an
`s3:prefix` condition scoped to the committed `dev` state and lock paths.

### State-object permission

The role receives only:

```text
s3:GetObject
s3:PutObject
```

on:

```text
clouddoc/dev/terraform.tfstate
```

It does not receive `s3:DeleteObject` on the state object.

### Lock-object permission

The role receives only:

```text
s3:GetObject
s3:PutObject
s3:DeleteObject
```

on:

```text
clouddoc/dev/terraform.tfstate.tflock
```

Deleting the lock object is required by native S3 state locking. It does not
authorize deletion of the state object.

### Explicit exclusions

The state role cannot:

- list unrelated bucket prefixes;
- access another environment state;
- inspect application Lambda functions;
- inspect DynamoDB application tables;
- inspect SQS application queues;
- inspect application IAM roles;
- invoke application APIs;
- manage the backend bucket;
- change bucket encryption, versioning, or public-access settings.

The current backend uses S3-managed AES256 encryption and does not use a
customer-managed KMS key. No KMS permission is included in this slice.

## Plan Authorization Boundary

The plan role is:

```text
clouddoc-dev-terraform-plan
```

It may be assumed only by:

```text
clouddoc-dev-github-identity
```

The role receives an explicit service-by-service read allowlist derived from
the resource types currently managed in `infra/terraform/`.

The current service families are:

- API Gateway V2
- CloudWatch dashboards, alarms, and log groups
- DynamoDB
- IAM roles and inline role policies
- Lambda functions, permissions, and event-source mappings
- S3 bucket configuration and policy resources
- SQS queues, policies, and redrive configuration
- STS caller identity

### Policy rules

The policy must:

- list concrete AWS actions;
- avoid AWS-managed broad policies;
- avoid wildcard action families such as `Get*`, `List*`, or `Describe*`;
- use resource-level scoping where the AWS API supports it;
- isolate actions requiring `Resource = "*"` in service-specific statements;
- document why each unscoped read action is technically required;
- exclude all known mutation actions;
- exclude `iam:PassRole`;
- exclude Lambda invocation;
- exclude SQS message operations;
- exclude event publishing;
- exclude Terraform-state S3 object access.

The source-derived action matrix is an initial authorization hypothesis.
The live plan is the operational proof. A denied action may be added only
after evidence identifies the exact API operation and confirms that it is
read-only and necessary for provider refresh.

## Terraform Credential Separation

The GitHub workflow first assumes the permissionless identity role through
OIDC. Terraform then uses those credentials as its base credential chain.

The S3 backend assumes:

```text
clouddoc-dev-terraform-state
```

The AWS provider assumes:

```text
clouddoc-dev-terraform-plan
```

The backend and provider roles are configured independently.

The committed state key remains the source of truth:

```text
infra/terraform/environments/dev.s3.tfbackend
```

The workflow does not introduce a second state-key variable.

Repository variables required by the workflow are:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN
```

The workflow maps the repository account variable into the existing local
contracts:

```text
CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID
TF_VAR_expected_aws_account_id
```

The role ARNs and bucket name are identifiers, not long-lived credentials.

## Terraform Root Changes

The application AWS provider will receive a validated plan-role ARN input and
an `assume_role` block.

The guarded Terraform workflow script will receive the state-role ARN and
configure the S3 backend assumption separately from the provider.

The implementation must preserve:

- partial S3 backend configuration;
- committed environment backend files;
- explicit environment selection;
- `allowed_account_ids`;
- existing common tags;
- local developer compatibility;
- absence of static credentials.

The implementation must not persist runtime credentials in backend files,
plan files, repository files, or logs.

## Workflow Design

### Caller workflow

```text
.github/workflows/terraform-plan.yml
```

Properties:

- trigger: `workflow_dispatch` only;
- approved branch: `main`;
- permissions: minimum required to call the reusable workflow;
- inputs: approved repository variables only;
- no Terraform commands;
- no AWS commands.

### Reusable workflow

```text
.github/workflows/reusable-terraform-plan.yml
```

Properties:

- trigger: `workflow_call`;
- environment: `dev`;
- permissions:
  - `id-token: write`
  - `contents: read`
  - `actions: read` only where required for attestation publication support
- runner: `ubuntu-latest`;
- exact immutable action pins;
- 900-second AWS sessions;
- no static AWS credential secret;
- value-free plan attestation upload only;
- no binary plan artifact upload;
- no full plan JSON artifact upload;
- no apply command.

### Concurrency

The workflow uses one environment-specific concurrency group:

```text
clouddoc-terraform-plan-dev
```

`cancel-in-progress` is disabled. A running plan is not interrupted merely
because another plan is requested. Native S3 locking remains enabled as the
state-level concurrency guard.

### Planned step order

```text
Validate trusted workflow context
Validate GitHub OIDC token claims
Configure permissionless AWS identity credentials
Checkout exact workflow commit
Verify repository state
Set up Python
Set up Terraform
Build Lambda package
Verify Lambda package
Initialize Terraform remote backend
Validate Terraform configuration
Create speculative Terraform plan
Render Terraform plan JSON
Generate sanitized plan summary
Generate value-free plan attestation
Publish sanitized GitHub step summary
Upload value-free plan attestation artifact
Delete temporary plan and JSON files
Verify temporary artifact cleanup
```

Security-sensitive validation must occur before Terraform accesses AWS.

## OIDC Claim Preflight

The reusable plan workflow validates the same eight claims enforced by IAM.

The preflight:

- requests a token with audience `sts.amazonaws.com`;
- decodes only the JWT payload in process memory;
- compares exact claim values;
- logs sanitized match or mismatch results;
- never prints the complete JWT;
- never stores the JWT;
- never prints the GitHub runtime request token.

AWS STS and IAM remain authoritative for signature, issuer, provider, and
trust-policy evaluation.

## Checkout and Build Contract

The workflow checks out the exact commit associated with the trusted `main`
workflow execution.

Checkout must use:

```text
persist-credentials: false
```

Before planning, the workflow executes:

```text
make lambda-package
make lambda-package-check
```

The plan requires:

```text
artifacts/lambda/clouddoc-app.zip
artifacts/lambda/clouddoc-app.sha256
```

These generated files remain ignored and are not uploaded as workflow
artifacts.

## Plan Lifecycle

Temporary files exist only under:

```text
$RUNNER_TEMP/clouddoc-terraform-plan/
```

Expected files:

```text
terraform.tfplan
terraform-plan.json
terraform-plan-attestation.json
```

Terraform plan exit semantics are handled explicitly:

- exit `0`: successful plan with no changes;
- exit `2`: successful plan with changes;
- exit `1`: plan failure.

A plan with changes is not treated as a workflow failure.

The binary plan and full JSON remain temporary runner files. They are never
uploaded. Controlled deployment regenerates a fresh plan rather than
downloading a binary plan. The uploaded attestation is value-free and is not
the local saved-plan manifest used by the wrapper `apply` command.

Live plan activation remains pending.

## Plan Summary Contract

`scripts/summarize_terraform_plan.py` converts Terraform JSON plan output into
a deterministic, value-free summary.

The human summary and machine attestation are both value-free.

The summary may contain only:

- resource address;
- resource type;
- planned action;
- create count;
- update count;
- delete count;
- replacement count;
- no-op count;
- overall plan result.

The summary must not contain:

- `before` values;
- `after` values;
- `after_unknown` values;
- sensitive values;
- provider configuration;
- backend configuration;
- environment variables;
- account IDs;
- role ARNs;
- state contents;
- Lambda environment values;
- resource policy documents.

Unknown action combinations fail closed.

The binary plan and JSON representation are treated as potentially sensitive
because saved Terraform plans may contain full configuration and resource
values even when terminal output redacts them.

## Plan Attestation Contract

`scripts/terraform_plan_attestation.py` publishes a value-free machine
attestation for later controlled deployment comparison.

The attestation:

- is value-free;
- carries the canonical value-free change-set fingerprint;
- is not the local saved-plan manifest used by wrapper `apply`;
- may be uploaded as a GitHub Actions artifact;
- does not include binary plan bytes or full plan JSON.

Binary plan files and full plan JSON remain temporary and are deleted before
the job finishes. Controlled deployment regenerates a fresh plan and compares
attestations rather than downloading a binary plan.

The plan role remains read-only. Live plan activation remains pending.

## Cleanup Contract

Cleanup runs even when plan or summary generation fails.

The workflow must:

1. remove the binary plan;
2. remove the JSON plan;
3. verify that temporary plan files are absent from the workspace;
4. fail when cleanup verification fails.

The binary plan and full plan JSON are never:

- committed;
- cached;
- uploaded;
- copied to another job;
- included in a release;
- used as the GitHub deployment apply artifact.

Only the value-free attestation artifact is uploaded for controlled deployment.

## Failure Modes

### OIDC context mismatch

The workflow fails before requesting AWS credentials.

### OIDC claim mismatch

The workflow fails before AWS STS role assumption.

### Identity-role assumption denied

The workflow fails before checkout and Terraform execution.

### State-role assumption denied

Terraform backend initialization fails closed.

### State object denied

Terraform cannot load the remote state and the workflow fails.

### State lock held

Terraform waits only for the configured lock timeout and then fails. Locking
is never disabled to bypass contention.

### Plan-role assumption denied

AWS provider initialization or refresh fails.

### Missing provider read action

The plan fails with an evidence-bearing authorization error. No broad policy is
attached as a shortcut.

### Lambda package missing or non-deterministic

The workflow fails before Terraform initialization.

### Plan contains changes

The workflow succeeds and publishes a sanitized change summary.

### Plan contains no changes

The workflow succeeds and publishes a no-op summary.

### Plan command error

The workflow fails after cleanup.

### Summary parser encounters an unknown action

The workflow fails closed after cleanup.

### Temporary-file cleanup fails

The workflow fails even when the Terraform plan itself succeeded.

## Security Invariants

- The GitHub identity role remains permissionless.
- Exactly two reusable workflows may request the identity role.
- Both reusable workflow references are pinned to `refs/heads/main`.
- State and plan roles trust only the exact identity-role ARN.
- State access is restricted to the exact `dev` state and lock objects.
- State-object deletion is not authorized.
- The plan role cannot access Terraform state.
- The state role cannot inspect application resources.
- The plan role cannot mutate application resources.
- No apply command exists in the workflow.
- No plan file leaves the runner.
- No static AWS credential is stored in GitHub.
- Missing authorization fails closed.
- IAM expansion requires concrete live-plan evidence.
- Explicit denies and account-level guardrails remain authoritative.

## Testing Strategy

### Terraform tests

The authorization bootstrap tests must verify:

- exactly two target roles;
- exact role names;
- exact same-account identity-role principal;
- 900-second session duration;
- exact state object and lock object permissions;
- no state-object deletion;
- no state access in the plan policy;
- no application permissions in the state policy;
- no mutation actions in the plan policy;
- no AWS-managed broad policy attachments;
- expected outputs;
- no remote backend in the bootstrap root.

### Python infrastructure contract tests

Static tests must verify:

- exact file set;
- provider and Terraform version constraints;
- lock-file equality;
- no static credentials;
- no wildcard trust principals;
- no broad managed policies;
- no forbidden action patterns;
- exact role and state paths;
- local-state bootstrap safety.

### Plan summary tests

Tests must cover:

- no-op;
- create;
- update;
- delete;
- replacement;
- mixed actions;
- malformed JSON;
- missing `resource_changes`;
- unknown actions;
- deterministic ordering;
- values resembling secrets never appearing in output.

### Workflow contract tests

Tests must verify:

- manual-only caller;
- `main`-only execution;
- `dev` Environment;
- exact OIDC claim preflight;
- immutable action pins;
- checkout with persisted credentials disabled;
- Lambda package order;
- separate state and plan role inputs;
- plan-only commands;
- detailed exit-code handling;
- runner-temporary plan location;
- value-free summary;
- value-free attestation upload;
- cleanup on all paths;
- no binary plan artifact upload;
- no full plan JSON artifact upload;
- no apply command;
- concurrency without cancellation.

### Operational tests

Post-merge activation must prove:

- OIDC trust accepts the plan reusable workflow;
- identity role remains permissionless;
- state role can access only the exact state and lock objects;
- plan role can refresh the real `dev` resources;
- a real remote plan completes;
- the summary contains no resource values;
- temporary files are deleted;
- plan role state access is denied;
- state role application reads are denied;
- selected mutation actions are denied through IAM policy simulation.

## Operational Activation

Activation occurs only after merge.

### A. Extend OIDC trust

Expected Terraform change:

```text
aws_iam_role.github_dev_identity
    update in place
```

The only semantic change is the second exact reusable workflow reference.

### B. Provision authorization roles

Create the state and plan roles through the local-state authorization
bootstrap. Preserve and back up its state outside Git.

### C. Configure repository variables

Create:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN
```

Do not create AWS access-key secrets.

### D. Run the live plan

Dispatch the plan workflow from `main`, inspect the claim preflight, validate
both role assumptions, and review the sanitized plan summary.

### E. Handle authorization gaps

For each `AccessDenied`:

1. identify the exact AWS action;
2. confirm the action is required for provider refresh;
3. confirm it is read-only;
4. determine whether resource-level scoping is supported;
5. update the policy narrowly;
6. add a regression test;
7. rerun the live plan.

### F. Record positive and negative evidence

Record successful plan execution and denied cross-boundary actions without
exposing account identifiers, role ARNs, state contents, or plan values.

## Scaling and Evolution

The design is environment-oriented.

A future environment receives separate:

- state object;
- lock object;
- state role;
- plan role;
- GitHub Environment;
- repository or environment variables;
- concurrency group;
- deployment authorization.

The current design does not use Terraform workspaces. Explicit environment
files and role boundaries remain the isolation mechanism.

The workflow cost is limited to GitHub runner time, AWS control-plane read
requests, STS sessions, and normal S3 state operations. There is no persistent
compute introduced by this slice.

## Acceptance Criteria

The slice is complete only when:

- the identity role still has zero permission policies;
- exactly two reusable workflows are trusted;
- state and plan roles are provisioned;
- state access is exact to the `dev` state and lock objects;
- the plan role has no state access;
- the state role has no application inspection access;
- a real GitHub Actions Terraform plan completes against remote state;
- the workflow handles both no-op and change-bearing plans;
- the summary contains actions and counts only;
- a value-free attestation is published;
- binary and JSON plan files are deleted;
- no binary plan or full plan JSON artifact is uploaded;
- no apply command exists in the plan workflow;
- positive and negative authorization evidence is recorded;
- architecture, ADR, operations, and contributor documentation are complete.

Live plan activation and operational proof remain pending after source merge.

## References

- Terraform Deployment Authorization:
  `terraform-deployment-authorization.md`
- Terraform Deploy Workflow Runbook:
  `../operations/terraform-deploy-workflow.md`
- Terraform Plan Workflow Runbook:
  `../operations/terraform-plan-workflow.md`
- AWS IAM policies and permissions:
  https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html
- AWS STS `AssumeRole`:
  https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html
- AWS IAM roles and role chaining:
  https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html
- Terraform S3 backend:
  https://developer.hashicorp.com/terraform/language/backend/s3
- Terraform AWS provider role assumption:
  https://registry.terraform.io/providers/hashicorp/aws/latest/docs
- Terraform plan command:
  https://developer.hashicorp.com/terraform/cli/commands/plan
- GitHub OIDC with reusable workflows:
  https://docs.github.com/actions/deployment/security-hardening-your-deployments/using-openid-connect-with-reusable-workflows
- GitHub OIDC reference:
  https://docs.github.com/actions/reference/openid-connect-reference