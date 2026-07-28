# ADR-027: Separate Terraform State, Plan, and Apply Authorization

## Status

Accepted

## Date

2026-07-28

## Context

CloudDoc AI Pipeline uses Terraform to manage its AWS `dev` infrastructure.

The repository already implements GitHub Actions authentication through
GitHub OIDC and the permissionless IAM role:

```text
clouddoc-dev-github-identity
```

The role proves the workload identity through an exact trust policy but has no
attached or inline permission policies.

The next requirement is to run a real Terraform plan from GitHub Actions
against:

```text
infra/terraform/
```

Terraform planning requires access to two distinct security domains:

1. The remote Terraform state and native S3 lock object.
2. The AWS resources refreshed by the Terraform provider.

A future Terraform apply will require a third and more privileged domain:
resource mutation.

The current S3 backend uses:

```text
state:
    clouddoc/dev/terraform.tfstate

lock:
    clouddoc/dev/terraform.tfstate.tflock

locking:
    native S3 use_lockfile

encryption:
    S3-managed AES256
```

The application AWS provider currently uses ambient credentials and does not
assume a dedicated plan role.

The existing OIDC trust authorizes one reusable workflow. Slice 32 introduces
a second exact reusable workflow for Terraform plan orchestration.

## Decision

CloudDoc will separate authentication, state authorization, plan
authorization, and future apply authorization.

### Authentication role

GitHub OIDC will continue to assume:

```text
clouddoc-dev-github-identity
```

This role remains permissionless.

Its exact `job_workflow_ref` allowlist will contain only:

```text
reusable-aws-identity.yml@refs/heads/main
reusable-terraform-plan.yml@refs/heads/main
```

The other exact OIDC claim conditions remain unchanged.

### State role

Terraform's S3 backend will assume:

```text
clouddoc-dev-terraform-state
```

This role will authorize only:

- `s3:ListBucket` for the exact state and lock prefix;
- `s3:GetObject` and `s3:PutObject` for the exact `dev` state object;
- `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` for the exact
  `.tflock` object.

It will not authorize deletion of the state object or inspection of
application resources.

### Plan role

The Terraform AWS provider will assume:

```text
clouddoc-dev-terraform-plan
```

This role will contain an explicit service-by-service read allowlist derived
from the resources managed by the current application root.

It will not receive:

- Terraform state access;
- AWS-managed `ReadOnlyAccess`;
- wildcard action families;
- create, update, delete, invoke, publish, send, or pass-role permissions;
- deployment authorization.

Actions that technically require `Resource = "*"` will be isolated and
documented individually.

### Future apply role

Terraform apply authorization will use a separate role and protected
deployment workflow in a later slice.

No plan credential will be promoted into deployment authorization.

### Role-assumption chain

The state and plan roles will trust the exact same-account identity-role ARN.

The design uses target-role trust as the same-account resource-based grant and
does not attach `sts:AssumeRole` permission policies to the identity role.

Role-chain sessions use a 900-second duration.

Operational activation must prove the chain. If account guardrails or AWS
authorization behavior require an identity policy, that change requires an
explicit architecture review rather than a silent permission expansion.

### Backend and provider separation

The S3 backend and AWS provider will assume their target roles independently.

```text
S3 backend
    → state role

AWS provider
    → plan role
```

The committed backend key remains authoritative. No duplicate GitHub variable
will be created for the state key.

### Plan lifecycle

The plan workflow will:

- run manually from `main`;
- use the GitHub `dev` Environment;
- validate workload context and OIDC claims;
- assume the permissionless identity role;
- build and verify the deterministic Lambda package;
- initialize the remote backend through the state role;
- refresh AWS resources through the plan role;
- create a speculative saved plan under `$RUNNER_TEMP`;
- render a JSON representation under `$RUNNER_TEMP`;
- publish a deterministic summary containing actions and counts only;
- delete the binary and JSON files;
- verify cleanup.

The plan and JSON files will not be uploaded, cached, committed, or promoted
to an apply workflow.

## Rationale

### State is a separate security domain

Terraform state can contain detailed infrastructure attributes and sensitive
values. A role that only needs to refresh application resources should not
also read or modify state.

### Plan and apply have different risks

A plan requires broad control-plane visibility but should not mutate
infrastructure. Apply authorization is more privileged and requires separate
approval, integrity, recovery, and concurrency decisions.

### Permissionless identity preserves a clean trust boundary

The OIDC role answers:

```text
Who is this workload?
```

The target-role trust policy answers:

```text
Which authorization boundary may this workload enter?
```

The target-role permission policy answers:

```text
What may the resulting session do?
```

Keeping these questions separate makes the system easier to review and defend.

### Exact reusable-workflow trust reduces workload ambiguity

The AWS identity role will trust only two named reusable workflows on
`refs/heads/main`. This prevents a feature branch or unrelated workflow from
reusing the same OIDC identity boundary.

### Saved plans are potentially sensitive

Terraform saved plans can contain configuration and resource values even when
terminal output redacts sensitive fields. Keeping the files ephemeral avoids
turning GitHub artifacts into a new sensitive-data storage system.

### Read authorization must be evidence-driven

AWS provider refresh behavior is service-specific. The initial policy is
derived from the committed resource inventory, but only the real plan can prove
the complete action set. Authorization gaps are corrected one exact read
action at a time.

## Consequences

### Positive

- GitHub OIDC authentication remains independent from infrastructure access.
- The identity role remains permissionless.
- State compromise does not follow automatically from plan-role compromise.
- Plan-role compromise does not grant state access or deployment capability.
- State access is scoped to one environment and two exact objects.
- Deployment authorization can evolve independently.
- Permission gaps become explicit operational evidence.
- The GitHub workflow can report plan changes without retaining a sensitive
  plan artifact.
- The architecture maps cleanly to future staging and production boundaries.

### Negative

- Terraform must manage two separate role assumptions.
- The workflow and local tooling require additional configuration.
- IAM policy development requires iterative live-plan verification.
- Some AWS read operations may require `Resource = "*"`.
- The same-account role chain must be proven operationally.
- The OIDC trust allowlist and its tests become multi-value contracts.
- The plan workflow contains additional cleanup and exit-code logic.
- Each environment requires additional IAM roles and operational variables.

### Operational

- A denied read action fails the plan until reviewed.
- State locking remains mandatory.
- A queued plan is not allowed to cancel a running plan.
- Role and bucket ARNs are repository variables, not secrets.
- Authorization bootstrap state is local, ignored, backed up, and managed
  separately from application infrastructure state.
- Negative authorization checks use safe read denials and IAM policy
  simulation rather than intentionally mutating resources.

## Alternatives Considered

### One role for state and plan

Rejected.

It would combine sensitive state access with broad infrastructure visibility,
making least privilege and incident analysis weaker.

### Direct GitHub OIDC trust on the state and plan roles

Rejected.

It would duplicate the complete OIDC claim contract across multiple roles and
couple workload authentication directly to every authorization role. The
permissionless identity role provides one reviewed authentication boundary.

### Attach `sts:AssumeRole` permissions to the identity role

Not selected for the initial implementation.

The target roles are in the same account and will grant the exact identity-role
principal through their trust policies. The resulting chain must be proven
during activation. Any identity-policy fallback requires explicit review.

### AWS-managed `ReadOnlyAccess`

Rejected.

It is broader than the CloudDoc Terraform resource graph and would obscure the
actual provider refresh requirements.

### One policy using `Get*`, `List*`, and `Describe*`

Rejected.

Wildcard action families can authorize unrelated APIs and make policy review
less meaningful.

### Direct OIDC web-identity assumption by the Terraform backend and provider

Rejected.

The workflow already establishes a reviewed identity role through
`aws-actions/configure-aws-credentials`. Chaining from that role keeps OIDC
authentication centralized and allows backend and provider authorization to
remain independent.

### Upload the binary plan as a GitHub artifact

Rejected.

Saved plans are potentially sensitive and plan-only output does not need
cross-job promotion.

### Parse Terraform JSON directly in workflow YAML

Rejected.

A tested Python utility provides deterministic behavior, clearer failure
handling, and stronger protection against accidentally rendering resource
values.

### Create a GitHub variable for the state key

Rejected.

The state key is already committed in the environment backend file. A second
source would create configuration drift.

### Disable locking to avoid plan contention

Rejected.

Locking protects state consistency. Contention must fail closed or wait for a
bounded timeout.

### Implement apply authorization in the same slice

Rejected.

Apply requires separate permissions, review gates, plan-integrity decisions,
recovery procedures, and failure analysis.

## Security Invariants

- The identity role has no attached or inline permission policy.
- Only two exact reusable workflows may obtain the identity role.
- Target roles trust only the exact identity-role ARN.
- State access is restricted to the exact `dev` state and lock objects.
- `s3:DeleteObject` is absent from the state object.
- The state role cannot inspect application resources.
- The plan role cannot access Terraform state.
- The plan role cannot mutate application resources.
- The workflow contains no apply command.
- Plan files never leave the runner.
- No long-lived AWS credential is stored in GitHub.
- IAM expansion requires evidence from a failed real plan.
- Account-level explicit denies remain authoritative.

## Validation

The decision is validated through:

1. Terraform tests for role, trust, and policy contracts.
2. Python static tests for prohibited permissions and file structure.
3. Workflow contract tests for OIDC, ordering, plan-only execution, and
   cleanup.
4. Unit tests for value-free plan summary generation.
5. A real remote-state-backed Terraform plan from GitHub Actions.
6. Effective AWS role and policy inspection.
7. Safe negative checks proving cross-boundary access is denied.
8. IAM policy simulation for selected mutation actions.
9. Evidence that binary and JSON plan files are deleted.

## Follow-Up Decisions

A future ADR must define:

- apply-role permissions;
- protected deployment workflow;
- review and approval gates;
- plan-to-apply integrity;
- deployment concurrency;
- rollback and recovery;
- production environment isolation.

## References

- AWS IAM policies and permissions:
  https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies.html
- AWS STS `AssumeRole`:
  https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html
- AWS IAM roles:
  https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html
- Terraform S3 backend:
  https://developer.hashicorp.com/terraform/language/backend/s3
- Terraform AWS provider:
  https://registry.terraform.io/providers/hashicorp/aws/latest/docs
- Terraform plan:
  https://developer.hashicorp.com/terraform/cli/commands/plan
- GitHub reusable-workflow OIDC:
  https://docs.github.com/actions/deployment/security-hardening-your-deployments/using-openid-connect-with-reusable-workflows