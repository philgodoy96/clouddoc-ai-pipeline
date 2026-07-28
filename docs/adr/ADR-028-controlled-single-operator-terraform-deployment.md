# ADR-028: Controlled Single-Operator Terraform Deployment

## Status

Accepted

## Date

2026-07-28

## Context

CloudDoc uses Terraform to manage its AWS infrastructure.

The repository already separates:

```text
GitHub workload authentication
Terraform state authorization
Terraform plan authorization
```

The existing authentication role is:

```text
clouddoc-dev-github-identity
```

It is permissionless and trusted by two exact reusable workflows:

```text
reusable-aws-identity.yml@refs/heads/main
reusable-terraform-plan.yml@refs/heads/main
```

The existing authorization roles are:

```text
clouddoc-dev-terraform-state
clouddoc-dev-terraform-plan
```

The state role owns the exact remote-state and lock boundary.

The plan role owns read-only provider refresh access.

The next requirement is controlled Terraform deployment.

The project currently has one authorized operator and no independent GitHub
reviewer or team.

Creating a second GitHub account solely to approve the same operator's
deployment would simulate segregation of duties without creating a meaningful
security boundary.

The deployment design must therefore be:

- honest about the operating model;
- resistant to accidental deployment;
- isolated from the plan identity;
- auditable;
- compatible with future team approval;
- small enough to complete and operate confidently.

## Decision

CloudDoc will implement a controlled single-operator Terraform deployment
model.

The design will not simulate independent approval through an artificial second
GitHub account.

The deployment path will use:

```text
dedicated permissionless deployment identity
dedicated Terraform apply role
dedicated GitHub deployment Environment
manual plan and deploy phases
exact plan-run validation
exact commit validation
value-free plan attestation
canonical change-set fingerprint
explicit APPLY-DEV confirmation
explicit destructive-change opt-in
non-cancelling deployment concurrency
native Terraform state locking
temporary saved plans only
```

## Dedicated Deployment Identity

Create:

```text
clouddoc-dev-github-deploy-identity
```

The role remains permissionless.

Its exact GitHub OIDC trust requires:

```text
repository:
    philgodoy96/clouddoc-ai-pipeline

ref:
    refs/heads/main

environment:
    dev-deploy

job_workflow_ref:
    philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main
```

It uses the same exact eight-claim `StringEquals` model already established by
the project:

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

The existing plan identity remains unchanged.

## Dedicated Terraform Apply Role

Create:

```text
clouddoc-dev-terraform-apply
```

The role trusts only:

```text
clouddoc-dev-github-deploy-identity
```

It does not trust:

- the existing plan identity;
- GitHub OIDC directly;
- the AWS account root;
- a wildcard principal;
- an AWS service principal.

The role receives:

- provider refresh reads;
- explicit mutation actions required by `infra/terraform/`;
- exact PassRole permission for four Lambda execution roles.

The role does not receive:

- Terraform state access;
- application payload reads;
- Lambda invocation;
- SQS message operations;
- DynamoDB item operations;
- AWS-managed broad policies;
- wildcard action families.

## State Role Trust

The existing state role keeps its current S3 permissions.

Its trusted principals expand from one exact identity role to two:

```text
clouddoc-dev-github-identity
clouddoc-dev-github-deploy-identity
```

This allows both plan and deployment workflows to initialize the same backend
without giving either identity direct state permissions.

## GitHub Environment

Create:

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
```

The Environment provides:

- a dedicated deployment target;
- a deployment-specific OIDC claim;
- a main-only deployment branch policy;
- a future integration point for independent reviewers.

The Environment is not represented as an independent approval boundary in the
current operating model.

## Manual Deployment Inputs

The deploy caller accepts:

```text
plan_run_id
confirmation
allow_destructive_changes
```

Confirmation must equal:

```text
APPLY-DEV
```

Destructive changes are disabled by default.

The design intentionally omits a separate `expected_commit_sha` input because
the deployment validates the referenced plan run's `head_sha` against the exact
deployment commit.

## Plan Attestation

The plan workflow will upload only:

```text
terraform-plan-attestation.json
```

Artifact name:

```text
clouddoc-terraform-plan-attestation
```

Retention:

```text
1 day
```

The attestation is value-free.

It contains:

```text
schema version
repository
plan run ID
commit SHA
environment
normalized resource changes
action counts
destructive-change indicator
no-op indicator
canonical change-set fingerprint
```

It excludes:

```text
binary Terraform plan
full Terraform JSON plan
Terraform state
resource before values
resource after values
unknown values
provider configuration
backend configuration
account IDs
role ARNs
bucket names
credentials
policy documents
```

## Plan-to-Apply Integrity

The deployment workflow does not apply a downloaded binary plan.

It:

1. validates the referenced plan run;
2. downloads the value-free attestation;
3. validates operator confirmation;
4. validates destructive-change authorization;
5. obtains deployment identity;
6. regenerates the Terraform plan;
7. generates a new value-free attestation;
8. compares canonical fingerprints;
9. applies the exact regenerated binary plan when fingerprints match.

A mismatch fails before `terraform apply`.

The fingerprint is not represented as binary-plan equality.

It is represented as:

```text
canonical value-free change-set fingerprint
```

## Canonical Projection

The fingerprint covers a strict, value-free semantic projection.

It uses approved fields such as:

```text
resource address
module address
resource mode
resource type
resource name
provider name
normalized action
action reason
previous address
replacement paths
```

It excludes resource values.

The projection is serialized deterministically and hashed with SHA-256.

## Destructive Changes

Destructive actions are:

```text
delete
replace
```

Both Terraform replacement orderings normalize to:

```text
replace
```

A destructive attestation fails unless:

```text
allow_destructive_changes = true
```

The exact `APPLY-DEV` confirmation is still required.

## No-Op Deployment

A verified no-op is a successful deployment outcome.

The workflow:

- verifies the referenced plan;
- verifies deployment authorization;
- regenerates the plan;
- confirms the fingerprint;
- skips `terraform apply`;
- verifies cleanup;
- succeeds.

## Concurrency

Deployment concurrency:

```text
clouddoc-terraform-deploy-dev
```

```text
cancel-in-progress:
    false
```

Another deployment cannot replace or cancel a running deployment.

Plan and deploy workflows may run concurrently.

Terraform native S3 locking remains the correctness boundary between backend
operations.

## Saved Plan Handling

Binary saved plans and full plan JSON remain inside runner temporary storage.

They are never:

- uploaded;
- cached;
- committed;
- attached to a release;
- passed between workflows;
- retained for rollback.

The exact regenerated plan is applied in the same workflow run that creates it.

## Partial Apply

Terraform apply is not transactional across arbitrary AWS resources.

CloudDoc will not claim automatic rollback.

A partial apply requires:

1. preserving the failed workflow run;
2. preserving CloudTrail evidence;
3. inspecting Terraform state;
4. inspecting AWS resource state;
5. generating a new speculative plan;
6. classifying completed and incomplete transitions;
7. repairing through a new reviewed deployment;
8. using manual state repair only as an incident procedure.

## Rationale

### A dedicated deployment identity prevents privilege convergence

The existing identity is available to identity-check and plan workflows.

If the apply role trusted that identity, those workloads would gain an
authorization path to deployment.

A separate permissionless deployment identity keeps the OIDC workload boundary
specific to the deploy workflow.

### A dedicated apply role preserves plan read-only semantics

The plan role must remain mutation-free.

Widening the plan role would erase the distinction between inspection and
deployment.

### An artificial reviewer would not create independent control

A second account controlled by the same operator would not provide meaningful
segregation of duties.

The design instead makes the single-operator model explicit and invests in
technical controls that are real and testable.

### Value-free attestation avoids sensitive plan persistence

Terraform plans can contain configuration and resource values.

The project does not persist binary plans or raw full-plan JSON.

The attestation retains only the information required to compare the reviewed
and regenerated change sets.

### Regeneration detects drift without promoting a saved plan

The deployment regenerates a fresh plan against current state.

The value-free fingerprint detects changes in the selected semantic projection.

The exact regenerated binary plan is then applied.

### Main-only Environment preserves future extensibility

The `dev-deploy` Environment provides a deployment-specific OIDC claim and a
main-only policy today.

Independent reviewers can be introduced later without redesigning AWS roles.

## Consequences

### Positive

- The plan identity cannot deploy.
- The plan role remains read-only.
- Deployment has a dedicated workload identity.
- Deployment has a dedicated mutation role.
- State access remains isolated.
- Operator intent is explicit and auditable.
- Destructive changes require a second explicit input.
- Deployments are tied to successful plan runs.
- Deployments are tied to exact commits.
- Binary plans are not persisted.
- Concurrent deployments are prevented.
- No-op behavior is explicit.
- Future independent reviewers remain architecture-compatible.
- The architecture is defensible without pretending team controls exist.

### Negative

- The workflow cannot provide independent human approval.
- The operator both initiates and authorizes deployment.
- Plan and deployment workflows require artifact transfer.
- The change-set fingerprint is not binary-plan identity.
- IAM apply permissions require iterative live proof.
- Some AWS mutation actions may require unscoped resources.
- Terraform partial apply still requires manual incident handling.
- Deployment logic and tests become more complex.
- The deployment Environment must be configured after merge.

### Operational

- The existing plan path must be activated before deployment activation.
- Missing apply permissions fail deployment.
- Authorization gaps require reviewed bootstrap changes.
- A stale plan run must be replaced with a new plan.
- A fingerprint mismatch requires a new reviewed plan.
- A cleanup failure makes the deployment fail.
- A no-op deployment succeeds without apply.
- A partial apply must not be blindly rerun.

## Alternatives Considered

### Reuse the existing GitHub identity role

Rejected.

It would allow existing trusted workflows to reach the apply role.

### Widen the Terraform plan role

Rejected.

It would collapse plan and deployment authorization.

### Create a second GitHub account for approval

Rejected.

An account controlled by the same operator would simulate independence without
creating a meaningful security boundary.

### Require a reviewer that does not exist

Rejected.

The repository must not document an operational control that cannot be
activated honestly.

### Upload the binary Terraform plan

Rejected.

Saved plans may contain sensitive values and would expand the sensitive
artifact boundary.

### Upload the full Terraform JSON plan

Rejected.

The full JSON can contain resource values and configuration details.

### Compare only resource address, type, and action

Rejected.

That projection is too weak for the deployment integrity claim.

### Compare binary plan digests across runs

Rejected.

Regenerated binary plans are not guaranteed to be suitable as a stable
cross-run semantic comparison surface, and the design intentionally avoids
persisting the original binary plan.

### Add state lineage and serial to attestation v1

Deferred.

They add state-history context but are not required for the core commit and
change-set validation model.

### Add Terraform version to attestation v1

Deferred.

The workflows pin the Terraform version. The value can be added later if the
attestation becomes a broader audit format.

### Add Lambda package digest to attestation v1

Deferred.

The package build and checksum are already deterministic and verified in both
plan and deployment workflows.

### Add a separate preflight job

Rejected.

Without an independent approval boundary, a second job adds complexity without
meaningful security separation.

### Implement automatic rollback

Rejected.

Terraform apply is not transactionally reversible across all managed AWS
resources.

## Security Invariants

- The existing GitHub identity cannot assume the apply role.
- The deployment identity is permissionless.
- Only one exact reusable deploy workflow is trusted.
- Deployment requires `refs/heads/main`.
- Deployment requires `dev-deploy`.
- The state role trusts exactly two approved identities.
- The apply role trusts only the deployment identity.
- The apply role cannot access Terraform state.
- The plan role cannot mutate infrastructure.
- PassRole is restricted to four exact Lambda execution roles.
- `iam:PassedToService` is restricted to `lambda.amazonaws.com`.
- Static AWS credentials are forbidden.
- Binary plans are never uploaded.
- Full Terraform plan JSON is never uploaded.
- Destructive changes are denied by default.
- Fingerprint mismatch prevents apply.
- Concurrent deployments are prohibited.
- Cleanup failure fails deployment.
- No automatic rollback is claimed.
- IAM expansion requires concrete evidence.

## Validation

The decision is validated through:

1. Terraform tests for OIDC and authorization bootstraps.
2. Static infrastructure contract tests.
3. Real pytest coverage for the existing plan summary.
4. Focused attestation schema and fingerprint tests.
5. Deployment-request API validation tests.
6. Terraform workflow lifecycle tests.
7. GitHub Actions workflow contract tests.
8. A successful live Terraform Plan workflow.
9. A controlled live Terraform Deploy workflow.
10. Positive and negative IAM authorization evidence.
11. Post-apply convergence verification.
12. Temporary-file cleanup verification.

## Follow-Up Decisions

Future decisions may define:

- production deployment authorization;
- cross-account deployment;
- team-based independent reviewers;
- multi-party approval;
- policy-as-code integration;
- encrypted saved-plan promotion;
- HCP Terraform;
- automatic drift remediation;
- automated incident recovery.

## References

- Terraform deployment architecture:
  `../architecture/terraform-deployment-authorization.md`
- Terraform plan authorization:
  `../architecture/terraform-plan-authorization.md`
- GitHub OIDC trust bootstrap:
  `../architecture/github-oidc-trust-bootstrap.md`
- Terraform deployment runbook:
  `../operations/terraform-deploy-workflow.md`