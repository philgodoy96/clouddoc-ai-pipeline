# Terraform Deployment Authorization

## Status

```text
Decision:
    approved

Source implementation:
    implemented

AWS activation:
    deployed and verified for dev

GitHub environment activation:
    deployed and verified

Live deployment verification:
    operationally verified
```

- **Environment:** `dev`
- **Operating model:** Single authorized operator
- **Last updated:** 2026-07-29

## Purpose

This document defines the controlled Terraform deployment architecture for the
CloudDoc `dev` environment.

The design extends the existing GitHub OIDC authentication and Terraform plan
authorization boundaries without promoting the plan identity or plan role into
deployment authorization.

The deployment path is intentionally designed for a single authorized operator.
It does not simulate independent approval through an artificial second GitHub
account.

Operational procedure lives in
[Terraform Deploy Workflow Runbook](../operations/terraform-deploy-workflow.md).

Evidence: [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

## Business Context

CloudDoc already has a source implementation for:

- GitHub OIDC workload authentication;
- a permissionless GitHub identity role;
- a permissionless GitHub deployment identity role;
- exact Terraform state authorization;
- read-only Terraform plan authorization;
- dedicated Terraform apply authorization;
- a manual remote Terraform plan workflow;
- value-free Terraform plan summaries;
- value-free plan attestation;
- controlled deploy workflows;
- temporary saved-plan cleanup.

Controlled infrastructure mutation for `dev` is activated and operationally
verified. See [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

A deployment must:

- be explicitly initiated;
- be tied to a successful Terraform plan run;
- be tied to the exact commit deployed;
- use a dedicated deployment identity;
- use a dedicated Terraform apply role;
- reject unauthorized destructive changes;
- regenerate the Terraform plan before apply;
- compare the regenerated change set with the reviewed plan attestation;
- apply the exact regenerated binary plan;
- prevent concurrent deployments;
- preserve audit evidence;
- fail closed when authorization, integrity, or cleanup checks fail.

## Strategic Operating Decision

CloudDoc uses a single-operator deployment model for the current project.

The project intentionally does not create:

- a second GitHub account;
- an artificial independent reviewer;
- a fake segregation-of-duties control;
- a custom approval service;
- a GitHub App solely to approve deployments.

The architecture instead relies on:

- a dedicated permissionless deployment identity;
- a dedicated Terraform apply role;
- an exact reusable-workflow trust boundary;
- a dedicated GitHub deployment Environment;
- main-only deployment;
- manual two-phase plan and deploy execution;
- explicit operator confirmation;
- explicit destructive-change authorization;
- commit and plan-attestation validation;
- non-cancelling deployment concurrency;
- native Terraform state locking;
- complete workflow and AWS audit evidence.

The design keeps room for independent GitHub Environment reviewers when the
project is operated by a team. Adding reviewers later does not require changing
the AWS identity or authorization boundaries.

## Current Repository Facts

The design is grounded in the current repository:

- Application Terraform root: `infra/terraform/`
- Existing plan caller:
  `.github/workflows/terraform-plan.yml`
- Existing reusable plan workflow:
  `.github/workflows/reusable-terraform-plan.yml`
- Existing GitHub identity role:
  `clouddoc-dev-github-identity`
- Existing Terraform state role:
  `clouddoc-dev-terraform-state`
- Existing Terraform plan role:
  `clouddoc-dev-terraform-plan`
- Existing plan summary:
  `scripts/summarize_terraform_plan.py`
- Existing Terraform workflow wrapper:
  `scripts/terraform_workflow.py`
- Existing plan output directory override:
  `--output-directory`
- Existing saved plan:
  `clouddoc.tfplan`
- Existing local plan manifest:
  `clouddoc.tfplan.json`
- Existing state key:
  `clouddoc/dev/terraform.tfstate`
- Existing lock object:
  `clouddoc/dev/terraform.tfstate.tflock`
- Existing S3 lock timeout:
  `5m`
- Existing plan concurrency:
  non-cancelling
- Controlled deploy workflow source:
  `.github/workflows/terraform-deploy.yml`
  and `.github/workflows/reusable-terraform-deploy.yml`
- Existing Terraform apply support:
  local wrapper `apply` remains the saved-plan contract;
  controlled GitHub deployment uses the separate `deploy` contract
- Source implementation status:
  implemented
- AWS and GitHub activation:
  deployed and verified for `dev`
- Live deployment verification:
  operationally verified

Evidence: [Deployed Runtime Evidence](../operations/deployed-runtime-evidence.md).

## Goals

The slice has implemented in source:

- add a dedicated permissionless GitHub deployment identity;
- add a dedicated Terraform apply role;
- keep the existing plan identity unable to assume the apply role;
- keep the existing plan role mutation-free;
- let the state role trust both exact permissionless identities;
- add a value-free Terraform plan attestation;
- bind deployment to a successful plan workflow run;
- bind deployment to the exact `main` commit;
- validate plan-run age;
- require exact operator confirmation;
- reject destructive changes by default;
- regenerate the Terraform plan during deployment;
- compare a canonical value-free change-set fingerprint;
- apply the exact regenerated binary plan;
- skip apply for a verified no-op;
- keep plan files inside runner temporary storage;
- delete all temporary deployment files;
- prevent concurrent `dev` deployments;
- preserve local ambient-credential compatibility;
- produce positive and negative authorization evidence.

## Non-Goals

This slice does not implement:

- production deployment;
- staging deployment;
- cross-account deployment;
- pull-request deployment;
- scheduled deployment;
- automatic deployment;
- independent reviewer approval;
- artificial second-account approval;
- multi-party approval;
- automatic rollback;
- transactional rollback across AWS services;
- HCP Terraform;
- persistent binary plan storage;
- raw Terraform JSON artifact storage;
- encrypted binary-plan promotion;
- policy-as-code platform integration;
- automatic IAM policy generation;
- automatic Terraform state repair;
- blue/green infrastructure deployment.

These concerns are intentionally deferred because they introduce different
operational, organizational, and recovery requirements.

## Actors

### Authorized operator

Runs the plan workflow, reviews its sanitized output, and manually starts the
deployment workflow with the required confirmation.

### Terraform plan workflow

Produces a speculative Terraform plan and a value-free attestation.

### Terraform deploy caller workflow

Accepts manual deployment inputs and calls the exact reusable deployment
workflow.

### Reusable Terraform deploy workflow

Validates the referenced plan run, acquires deployment identity, regenerates
the plan, compares fingerprints, applies the regenerated plan, and verifies
cleanup.

### GitHub `dev-deploy` Environment

Provides a dedicated deployment target and a main-only branch policy.

It has:

- no required reviewer;
- no environment secret;
- no environment variable;
- no self-review configuration.

### GitHub OIDC provider

Issues temporary workload tokens to approved reusable workflows.

### Permissionless deployment identity

Authenticates only the exact deployment reusable workflow.

### Terraform state role

Authorizes exact state and lock access for both approved Terraform identities.

### Terraform apply role

Authorizes explicit AWS control-plane mutations required by the application
Terraform root.

### Terraform S3 backend

Reads and writes the remote state and manages the native S3 lock file.

### Terraform AWS provider

Refreshes and mutates the CloudDoc AWS infrastructure through the apply role.

### GitHub Actions artifact service

Stores the short-lived value-free plan attestation.

### AWS CloudTrail

Records AWS STS and infrastructure control-plane activity.

## Target Architecture

```text
Terraform Plan workflow
    |
    | creates speculative saved plan
    | renders full JSON locally
    | generates value-free attestation
    | deletes saved plan and full JSON
    v
Short-lived GitHub artifact
    |
    | terraform-plan-attestation.json
    | no resource values
    | no binary plan
    v
Terraform Deploy workflow
    |
    | workflow_dispatch
    | exact plan run validation
    | exact main commit validation
    | APPLY-DEV confirmation
    | destructive-change gate
    v
GitHub Environment: dev-deploy
    |
    | main-only branch policy
    | no required reviewer
    | no secrets
    v
clouddoc-dev-github-deploy-identity
    |
    | same-account sts:AssumeRole
    +-------------------------------+
    |                               |
    v                               v
clouddoc-dev-terraform-state   clouddoc-dev-terraform-apply
    |                               |
    | exact state and lock          | explicit mutation boundary
    | no application access         | no state access
    +---------------+---------------+
                    |
                    v
          regenerate Terraform plan
                    |
                    v
       compare canonical fingerprint
                    |
          mismatch -----> fail
                    |
                  match
                    |
                    v
       apply exact regenerated plan
```

## Identity Architecture

### Existing plan identity

```text
clouddoc-dev-github-identity
```

It remains trusted only by:

```text
reusable-aws-identity.yml@refs/heads/main
reusable-terraform-plan.yml@refs/heads/main
```

It must not gain permission to assume:

```text
clouddoc-dev-terraform-apply
```

### Deployment identity

```text
clouddoc-dev-github-deploy-identity
```

Properties:

```text
attached managed policies: 0
inline policies:           0
```

Its OIDC trust requires exact `StringEquals` conditions for:

- `aud`
- `sub`
- `repository`
- `repository_id`
- `repository_owner_id`
- `ref`
- `environment`
- `job_workflow_ref`

The exact trusted deployment workflow is:

```text
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main
```

The exact environment is:

```text
dev-deploy
```

The exact branch is:

```text
refs/heads/main
```

No wildcard, pull-request ref, tag, feature branch, third workflow, or direct
permission policy is allowed.

## Authorization Architecture

### State role

Existing role:

```text
clouddoc-dev-terraform-state
```

Its permission policy remains unchanged.

Its exact trusted AWS principals become:

```text
clouddoc-dev-github-identity
clouddoc-dev-github-deploy-identity
```

The role remains restricted to:

```text
state object:
    s3:GetObject
    s3:PutObject

lock object:
    s3:GetObject
    s3:PutObject
    s3:DeleteObject
```

It continues to exclude:

- application resource access;
- unrelated bucket prefixes;
- state object deletion;
- KMS permissions;
- deployment mutations.

### Apply role

New role:

```text
clouddoc-dev-terraform-apply
```

Trusted principal:

```text
clouddoc-dev-github-deploy-identity
```

It must not trust:

```text
clouddoc-dev-github-identity
GitHub OIDC directly
account root
wildcard principal
service principal
```

Its permissions are derived from the managed resources in `infra/terraform/`.

Current service families:

- API Gateway V2;
- CloudWatch;
- CloudWatch Logs;
- DynamoDB;
- IAM;
- Lambda;
- S3;
- SQS;
- STS caller identity.

The apply policy must:

- enumerate exact AWS actions;
- separate service families into reviewable statements;
- scope resources to exact CloudDoc `dev` names and ARN patterns where
  supported;
- use `Resource = "*"` only when the AWS API does not support resource-level
  permissions or an AWS-assigned identifier is unavailable before creation;
- include the read actions required by provider refresh;
- include only the mutation actions required by current Terraform resources;
- exclude Terraform state access;
- exclude application payload reads;
- exclude Lambda invocation;
- exclude SQS message operations;
- exclude DynamoDB item operations;
- exclude event publication not required by Terraform;
- exclude AWS-managed broad policies.

The initial action matrix is a source-derived least-privilege hypothesis.

Successful live deployment is required to prove sufficiency.

Authorization gaps are corrected only after an evidence-bearing
`AccessDenied` identifies a necessary control-plane action.

## IAM PassRole Boundary

The apply role receives:

```text
iam:PassRole
```

only for the four exact Lambda execution-role ARNs:

```text
aws_iam_role.create_job
aws_iam_role.get_job
aws_iam_role.processor
aws_iam_role.dead_letter_reconciler
```

Condition:

```text
iam:PassedToService = lambda.amazonaws.com
```

No wildcard execution-role ARN is required.

The apply role does not receive permission to pass:

- the GitHub identity roles;
- the Terraform state role;
- the Terraform plan role;
- the Terraform apply role;
- unrelated application roles;
- account-root roles.

## Deployment Caller Contract

Caller workflow:

```text
.github/workflows/terraform-deploy.yml
```

Trigger:

```text
workflow_dispatch only
```

Inputs:

### `plan_run_id`

```text
type: string
required: true
```

Identifies the successful Terraform Plan workflow run.

### `confirmation`

```text
type: string
required: true
exact value: APPLY-DEV
```

Makes operator intent explicit.

### `allow_destructive_changes`

```text
type: boolean
required: true
default: false
```

Allows a plan containing `delete` or `replace` only when explicitly enabled.

The caller does not:

- execute Terraform;
- access AWS;
- download artifacts;
- validate GitHub APIs;
- hold secrets;
- contain shell steps.

## Reusable Deployment Workflow Contract

Reusable workflow:

```text
.github/workflows/reusable-terraform-deploy.yml
```

Trigger:

```text
workflow_call only
```

Required permissions:

```yaml
permissions:
  actions: read
  contents: read
  id-token: write
```

Environment:

```text
dev-deploy
```

Runner:

```text
ubuntu-latest
```

Concurrency:

```text
group: clouddoc-terraform-deploy-dev
cancel-in-progress: false
```

Required step sequence:

```text
Validate trusted workflow context
Validate deployment request inputs
Validate referenced Terraform Plan run
Download Terraform plan attestation
Validate Terraform plan attestation
Validate destructive-change authorization
Validate GitHub OIDC token claims
Configure deployment identity credentials
Verify deployment identity
Check out attested commit
Verify repository checkout
Set up Python
Install project
Set up Terraform
Build Lambda package
Verify Lambda package
Regenerate Terraform plan
Render regenerated plan JSON
Generate regenerated attestation
Compare change-set fingerprint
Apply exact regenerated plan or complete no-op
Verify deployment convergence
Delete temporary deployment files
Verify cleanup
```

Security-sensitive validation must happen before AWS credentials are requested.

## GitHub Environment Contract

Environment:

```text
dev-deploy
```

Configuration:

```text
deployment branch:
    main only

required reviewers:
    none

prevent self-review:
    disabled

environment secrets:
    none

environment variables:
    none
```

The Environment provides:

- a dedicated OIDC environment claim;
- a dedicated deployment target;
- main-only deployment policy;
- future compatibility with independent reviewers.

The Environment is not represented as an independent approval boundary in the
current single-operator model.

## Repository Variables

Existing reusable values:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
```

New deployment variables:

```text
CLOUDDOC_DEV_DEPLOY_IDENTITY_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN
```

No new state-key variable is introduced.

The committed backend file remains authoritative for:

```text
clouddoc/dev/terraform.tfstate
```

No AWS access-key secret is introduced.

## Plan Attestation

Artifact name:

```text
clouddoc-terraform-plan-attestation
```

Artifact file:

```text
terraform-plan-attestation.json
```

Retention:

```text
1 day
```

The plan workflow creates the attestation after rendering the full Terraform
plan JSON and before deleting temporary plan files.

The attestation is uploaded only after:

- the Terraform plan succeeds;
- the full JSON is rendered;
- the value-free projection is generated;
- the attestation passes local schema validation.

## Attestation Schema

The attestation contains:

```text
schema_version
repository
plan_run_id
commit_sha
environment
resource_changes
action_counts
destructive_changes
no_changes
change_set_fingerprint
```

Each resource change contains only approved value-free fields:

```text
address
module_address
mode
resource_type
resource_name
provider_name
action
action_reason
previous_address
replace_paths
```

Addresses and address-like fields use the existing sanitization model.

Replacement paths are represented without values.

The attestation must not contain:

- `before`;
- `after`;
- `after_unknown`;
- resource attribute values;
- state contents;
- state bucket;
- state key;
- role ARN;
- account ID;
- provider configuration;
- backend configuration;
- policy documents;
- Lambda environment variables;
- credentials;
- OIDC tokens.

Unknown fields in an attestation fail validation.

## Canonical Change-Set Fingerprint

The attestation fingerprint is:

```text
SHA-256(canonical JSON value-free change-set projection)
```

Canonicalization requires:

- a fixed schema version;
- a strict field allowlist;
- lexicographic object-key ordering;
- deterministic resource ordering;
- normalized Terraform actions;
- normalized replacement action ordering;
- deterministic replacement-path ordering;
- UTF-8 encoding;
- no insignificant whitespace.

The fingerprint is intentionally called:

```text
canonical value-free change-set fingerprint
```

It does not claim binary-plan identity.

It detects meaningful change-set differences preserved by the selected
value-free projection.

## Plan Workflow Extension

The existing plan workflow will:

1. create the saved plan;
2. render full Terraform plan JSON locally;
3. create the human-readable sanitized summary;
4. create the value-free deployment attestation;
5. upload only the attestation;
6. delete the saved plan;
7. delete the local wrapper manifest;
8. delete the full Terraform JSON;
9. verify cleanup.

It will not upload:

```text
clouddoc.tfplan
clouddoc.tfplan.json
terraform-show.json
Terraform state
```

## Deployment Request Validation

A repository-owned Python script validates the referenced plan run using the
temporary `GITHUB_TOKEN`.

It validates:

- repository;
- workflow path;
- event;
- branch;
- head SHA;
- status;
- conclusion;
- creation time;
- maximum age of 24 hours.

The deployment commit must equal the referenced plan run's `head_sha`.

The deployment ref must be:

```text
refs/heads/main
```

The request validator must not print:

- token;
- complete API headers;
- numeric GitHub IDs;
- account IDs;
- role ARNs;
- bucket names;
- artifact contents.

## Destructive-Change Policy

Destructive normalized actions:

```text
delete
replace
```

Both Terraform replacement orderings normalize to:

```text
replace
```

Default:

```text
allow_destructive_changes = false
```

When the attestation contains destructive changes:

```text
false:
    deployment fails before AWS credentials

true:
    deployment may continue
```

The exact confirmation:

```text
APPLY-DEV
```

is always required.

Unknown action combinations fail closed.

## Deployment Plan Lifecycle

The deployment workflow does not consume a binary plan from the plan workflow.

It performs:

```text
1. initialize the backend through the state role;
2. configure the AWS provider through the apply role;
3. regenerate a saved plan under runner temporary storage;
4. render the regenerated full Terraform JSON locally;
5. create a regenerated value-free attestation;
6. compare the regenerated fingerprint with the referenced attestation;
7. fail before apply when the fingerprints differ;
8. skip apply when the regenerated plan is no-op;
9. apply the exact regenerated binary plan when the fingerprint matches;
10. verify post-apply convergence;
11. delete all temporary files.
```

The exact regenerated binary plan is applied in the same workflow run that
created it.

## No-Op Behavior

When the referenced and regenerated attestations both indicate no changes:

```text
deployment authorization:
    verified

terraform apply:
    not executed

workflow result:
    success

cleanup:
    required
```

No-op is a valid deployment outcome.

## Concurrency

Deployment concurrency:

```text
group: clouddoc-terraform-deploy-dev
cancel-in-progress: false
```

The deployment workflow blocks another deployment workflow for the same
environment.

The plan and deploy workflows may run concurrently.

Terraform native S3 locking remains the correctness boundary between backend
operations.

Plan/deploy lock contention may cause a bounded wait or a failed operation.

The project does not disable locking to increase throughput.

## Cleanup Contract

Temporary deployment files exist only under:

```text
$RUNNER_TEMP/clouddoc-terraform-deploy
```

Expected transient files include:

```text
downloaded attestation
regenerated saved plan
local wrapper manifest
full regenerated Terraform JSON
regenerated attestation
ephemeral backend override
```

Cleanup must:

1. run whether deployment succeeds or fails;
2. remove the complete temporary directory;
3. preserve the original command status when cleanup succeeds;
4. fail when cleanup fails;
5. verify the directory is absent in a separate always-running step.

No temporary deployment file is:

- committed;
- cached;
- uploaded after deployment;
- attached to a release;
- copied to another job;
- retained for rollback.

## Failure Modes

### Invalid manual confirmation

The workflow fails before GitHub API access and AWS credentials.

### Referenced plan run not found

The workflow fails before artifact download.

### Referenced plan run unsuccessful

The workflow fails before artifact download.

### Referenced plan run expired

A plan run older than 24 hours is rejected.

### Referenced commit is stale

The workflow fails when the plan run commit does not equal the deployment
commit.

### Attestation artifact missing

The workflow fails before AWS credentials.

### Artifact digest validation failure

The workflow fails before attestation use.

### Attestation schema failure

Unknown, missing, or malformed fields fail closed.

### Destructive changes not authorized

The workflow fails before AWS credentials.

### OIDC context or claim mismatch

The workflow fails before AWS role assumption.

### Deployment identity federation denied

The workflow fails before checkout and Terraform execution.

### State-role assumption denied

Terraform backend initialization fails closed.

### Apply-role assumption denied

Provider initialization or refresh fails closed.

### Missing apply permission

Terraform fails with an evidence-bearing `AccessDenied`.

No broad policy is attached as a shortcut.

### Fingerprint mismatch

The workflow fails before `terraform apply`.

### No-op regenerated plan

The workflow succeeds without `terraform apply`.

### Terraform partial apply

The workflow fails and preserves workflow and CloudTrail evidence.

No automatic rollback is claimed.

### Post-apply non-convergence

A post-apply verification plan that still contains changes fails the deployment.

### Cleanup failure

The workflow fails even when apply succeeds.

## Partial-Apply Recovery

Terraform apply is not transactional across arbitrary AWS resources.

When a partial apply occurs:

1. preserve the failed workflow run;
2. preserve CloudTrail evidence;
3. do not blindly rerun apply;
4. inspect current Terraform state;
5. inspect current AWS resource state;
6. execute a new speculative plan;
7. classify completed and incomplete transitions;
8. repair through a new reviewed deployment;
9. use manual Terraform state repair only through an incident procedure.

The system does not claim automatic rollback.

## Security Invariants

- The existing GitHub identity cannot assume the apply role.
- The existing plan role cannot mutate infrastructure.
- The deployment identity is permissionless.
- Only the exact reusable deploy workflow may obtain deployment identity.
- Deployment requires `refs/heads/main`.
- Deployment requires the `dev-deploy` Environment.
- Deployment requires exact `APPLY-DEV` confirmation.
- A referenced plan run must be successful and recent.
- A referenced plan run must target the deployed commit.
- Destructive changes are rejected by default.
- The state role keeps its exact object boundary.
- The apply role cannot access Terraform state.
- `iam:PassRole` is restricted to exact Lambda execution roles.
- `iam:PassedToService` is restricted to `lambda.amazonaws.com`.
- Static AWS credentials are forbidden.
- Saved Terraform plans are never uploaded.
- Full Terraform JSON plans are never uploaded.
- A fingerprint mismatch prevents apply.
- Concurrent deployments are prohibited.
- Cleanup failure makes deployment fail.
- No automatic rollback is claimed.
- Authorization expansion requires concrete evidence.

## Testing Strategy

### OIDC Terraform tests

Must verify:

- two permissionless identity roles;
- exact role names;
- exact deploy workflow ref;
- exact `dev-deploy` environment;
- exact eight-claim trust;
- `StringEquals` only;
- no wildcard;
- no policy attachment;
- existing plan identity unchanged.

### OIDC static tests

Must verify:

- exact bootstrap file set;
- exact resource count;
- no permission policy resource;
- no managed policy attachment;
- exact trusted workflow ownership;
- exact environment separation;
- no cross-trust between plan and deploy identities.

### Authorization Terraform tests

Must verify:

- exact state, plan, and apply role resources;
- state role trusts exactly two identity principals;
- plan role trusts only the existing identity;
- apply role trusts only the deployment identity;
- state policy unchanged;
- apply role has no state access;
- exact PassRole resources;
- exact `iam:PassedToService` condition;
- no broad managed policy;
- no wildcard actions.

### Authorization static tests

Must verify:

- exact resource set;
- no state-object references in apply policy;
- no application mutations in plan policy;
- no application reads in state policy;
- no broad managed policy names;
- no static credentials;
- no direct OIDC trust in authorization roles.

### Summary tests

The existing summary test file must be converted into real pytest coverage
before attestation logic relies on it.

Tests must cover:

- create;
- update;
- delete;
- replace;
- no-op;
- data-source exclusion;
- deterministic ordering;
- malformed JSON;
- unknown actions;
- address sanitization;
- value non-rendering.

### Attestation tests

Must cover:

- exact schema;
- canonical serialization;
- deterministic fingerprint;
- resource ordering;
- replacement normalization;
- replacement-path ordering;
- destructive classification;
- no-op classification;
- strict unknown-field rejection;
- before/after value exclusion;
- sanitized identifiers;
- malformed attestation rejection;
- fingerprint mismatch.

### Deployment request tests

Must cover:

- valid run;
- invalid run ID;
- wrong workflow path;
- wrong event;
- wrong branch;
- wrong commit;
- incomplete run;
- failed run;
- expired run;
- malformed API response;
- token non-disclosure;
- HTTP errors;
- timeout;
- repository mismatch.

### Terraform workflow tests

Must cover:

- apply-role input;
- ambient local mode;
- plan-role mode;
- apply-role mode;
- partial configuration rejection;
- exact role-name validation;
- exact account matching;
- regenerate/compare/apply lifecycle;
- no-op behavior;
- destructive gate handoff;
- cleanup;
- post-apply convergence;
- partial-apply failure propagation.

### Workflow contract tests

Must verify:

- manual-only caller;
- exact typed inputs;
- main-only reusable workflow;
- exact `dev-deploy` environment;
- exact permissions;
- exact OIDC claim contract;
- immutable action pins;
- exact artifact names;
- one-day retention;
- no binary plan upload;
- no full JSON upload;
- request validation before AWS;
- destructive validation before AWS;
- exact deployment identity;
- exact state/apply role inputs;
- non-cancelling deployment concurrency;
- no apply of downloaded artifact;
- no automatic approval;
- cleanup on all paths.

## Operational Activation

Activation occurs after merge and after the plan path is operationally proven.

### Phase 1 — Activate the existing plan path

1. Apply the current OIDC trust extension.
2. Apply the state and plan authorization bootstrap.
3. Configure the existing plan repository variables.
4. Run the Terraform Plan workflow.
5. Verify the real remote-state-backed plan.
6. Correct only evidence-bearing read authorization gaps.

### Phase 2 — Activate deployment identity and apply authorization

1. Apply the deployment identity bootstrap.
2. Apply the apply authorization bootstrap.
3. Create `dev-deploy`.
4. Add the main-only branch policy.
5. Keep required reviewers disabled.
6. Keep environment secrets empty.
7. Configure deployment repository variables.

### Phase 3 — Prove controlled deployment

1. Run a fresh Terraform Plan workflow.
2. Verify the plan attestation artifact.
3. Start Terraform Deploy with:
   - exact plan run ID;
   - exact `APPLY-DEV` confirmation;
   - destructive changes disabled unless required.
4. Verify deployment OIDC claims.
5. Verify deployment identity.
6. Verify state-role assumption.
7. Verify apply-role assumption.
8. Verify fingerprint comparison.
9. Verify exact regenerated-plan apply or no-op handling.
10. Verify post-apply convergence.
11. Verify cleanup.
12. Collect positive and negative authorization evidence.

## Acceptance Criteria

The slice is complete only when:

- the plan identity remains unable to assume the apply role;
- the deployment identity is permissionless;
- the deployment identity trusts one exact reusable workflow;
- the deployment identity requires `dev-deploy`;
- the state role trusts exactly two approved identity roles;
- the apply role trusts only the deployment identity;
- the apply role has no Terraform state access;
- PassRole is exact to the four Lambda execution roles;
- plan attestation is value-free;
- plan attestation retention is one day;
- the deployment request validates a successful, recent plan run;
- the deployed commit matches the referenced plan commit;
- destructive changes are rejected by default;
- regenerated fingerprint must match;
- no-op succeeds without apply;
- exact regenerated binary plan is applied when changes exist;
- temporary deployment files are deleted;
- concurrent `dev` deployments are blocked;
- post-apply convergence is verified;
- positive and negative authorization evidence is recorded;
- documentation distinguishes repository implementation, deployed `dev` activation, and live operational proof.

## Scaling and Evolution

A future environment receives separate:

- GitHub deployment Environment;
- permissionless deployment identity;
- state-role trust entry;
- Terraform apply role;
- repository variables;
- concurrency group;
- artifact namespace;
- deployment runbook;
- operational evidence.

Production will not reuse the `dev` deployment identity or apply role.

When a team operates the project, independent required reviewers can be added
to the GitHub Environment without redesigning the AWS identity and
authorization boundaries.

## References

- ADR-028:
  `../adr/ADR-028-controlled-single-operator-terraform-deployment.md`
- Terraform plan authorization:
  `terraform-plan-authorization.md`
- GitHub OIDC trust bootstrap:
  `github-oidc-trust-bootstrap.md`
- Terraform state and environment workflow:
  `terraform-state-and-environment-workflow.md`
- Terraform deployment runbook:
  `../operations/terraform-deploy-workflow.md`