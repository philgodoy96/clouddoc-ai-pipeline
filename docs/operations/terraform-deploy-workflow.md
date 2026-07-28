# Terraform Deploy Workflow Runbook

## Status

```text
Source implementation:
    implemented

GitHub deployment environment:
    pending

GitHub repository variables:
    pending

AWS deployment identity:
    source implemented, AWS apply pending

AWS Terraform apply role:
    source implemented, AWS apply pending

Live Terraform plan:
    pending operational activation

Live Terraform deployment:
    pending operational proof
```

## Purpose

This runbook defines the controlled Terraform deployment procedure for the
CloudDoc `dev` environment.

The workflow is intentionally designed for a single authorized operator.

It does not simulate independent approval through an artificial second GitHub
account. Instead, it uses separate workload identity, separate apply
authorization, exact workflow trust, manual plan and deploy phases, commit and
attestation validation, explicit destructive-change authorization, deployment
concurrency, native Terraform locking, and auditable workflow evidence.

## Deployment Model

```text
Terraform Plan
    |
    | value-free attestation
    v
Terraform Deploy
    |
    | manual run ID
    | APPLY-DEV confirmation
    | destructive-change opt-in
    v
GitHub Environment: dev-deploy
    |
    | main-only branch policy
    | no required reviewer
    | no environment secrets
    v
clouddoc-dev-github-deploy-identity
    |
    +-------------------------------+
    |                               |
    v                               v
clouddoc-dev-terraform-state   clouddoc-dev-terraform-apply
    |                               |
    | exact backend access          | explicit control-plane mutations
    |                               | no state access
    +---------------+---------------+
                    |
                    v
          regenerate Terraform plan
                    |
                    v
       compare value-free fingerprint
                    |
          mismatch -----> fail
                    |
                  match
                    |
                    v
       apply exact regenerated plan
```

## Operating Assumptions

The procedure assumes:

- the repository default branch is `main`;
- the deployment target is `dev`;
- the AWS region is `us-east-1`;
- the Terraform state key remains committed in source;
- no static AWS credentials exist in GitHub;
- the current operator is authorized to run both plan and deployment;
- the plan workflow has already been activated and proven;
- the deployment Environment and repository variables have been configured;
- the deployment identity and apply role have been applied to AWS;
- all repository quality gates are green on `main`.

## Security Boundaries

### Existing GitHub identity

```text
clouddoc-dev-github-identity
```

Purpose:

```text
identity proof
Terraform plan
```

It cannot assume:

```text
clouddoc-dev-terraform-apply
```

### Deployment identity

```text
clouddoc-dev-github-deploy-identity
```

Purpose:

```text
authenticate only the exact reusable Terraform deploy workflow
```

Properties:

```text
permission policies:
    0

trusted workflow:
    reusable-terraform-deploy.yml@refs/heads/main

trusted environment:
    dev-deploy

trusted ref:
    refs/heads/main
```

### Terraform state role

```text
clouddoc-dev-terraform-state
```

Trusted identities:

```text
clouddoc-dev-github-identity
clouddoc-dev-github-deploy-identity
```

Permissions remain restricted to the exact state and lock objects.

### Terraform plan role

```text
clouddoc-dev-terraform-plan
```

Purpose:

```text
read-only AWS provider refresh
```

It remains mutation-free.

### Terraform apply role

```text
clouddoc-dev-terraform-apply
```

Trusted identity:

```text
clouddoc-dev-github-deploy-identity
```

It receives:

- explicit provider refresh reads;
- explicit control-plane mutations required by the current Terraform root;
- exact `iam:PassRole` for the four CloudDoc Lambda execution roles.

It does not receive:

- Terraform state access;
- Lambda invocation;
- application S3 object access;
- DynamoDB item access;
- SQS message access;
- Bedrock invocation;
- static credentials;
- AWS-managed broad policies.

## Required GitHub Configuration

### Repository variables

Required:

```text
CLOUDDOC_AWS_ACCOUNT_ID
CLOUDDOC_DEV_IDENTITY_ROLE_ARN
CLOUDDOC_TERRAFORM_STATE_BUCKET
CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN
CLOUDDOC_DEV_DEPLOY_IDENTITY_ROLE_ARN
CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN
```

The repository must not define static AWS credential secrets:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
```

### GitHub Environment

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

environment variables:
    none
```

This is an intentional single-operator model.

The Environment provides a deployment-specific OIDC claim, a main-only
deployment target, and a future integration point for independent reviewers.

## Required AWS Configuration

The following source changes must be applied before the first deployment:

```text
GitHub OIDC bootstrap:
    deploy identity role

Terraform authorization bootstrap:
    state-role trust extension
    Terraform apply role
    Terraform apply permission policy
```

Expected roles:

```text
clouddoc-dev-github-deploy-identity
clouddoc-dev-terraform-apply
```

Do not attach a broad temporary policy to make the first deployment pass.

Missing actions must be added only after a concrete `AccessDenied` identifies a
required Terraform control-plane operation.

## Activation Order

Activation must happen in this order.

### Phase 1 — Activate and prove Terraform Plan

1. Apply the existing GitHub OIDC plan-workflow trust.
2. Apply the Terraform state and plan authorization bootstrap.
3. Configure:
   - `CLOUDDOC_TERRAFORM_STATE_BUCKET`;
   - `CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN`;
   - `CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN`.
4. Run the Terraform Plan workflow on `main`.
5. Confirm:
   - OIDC claim preflight succeeds;
   - permissionless identity assumption succeeds;
   - state-role assumption succeeds;
   - plan-role assumption succeeds;
   - remote state initializes;
   - Lambda package builds and verifies;
   - Terraform plan completes;
   - sanitized plan summary is published;
   - value-free attestation is uploaded;
   - cleanup verification succeeds.
6. Correct only evidence-bearing read authorization gaps.
7. Run a second successful plan after any correction.

Do not continue to deployment activation until the plan path is operationally
proven.

### Phase 2 — Activate deployment authorization

1. Apply the OIDC bootstrap containing the deployment identity.
2. Apply the Terraform authorization bootstrap containing:
   - state-role dual trust;
   - Terraform apply role;
   - apply permission policy.
3. Create `dev-deploy`.
4. Add the `main`-only deployment branch policy.
5. Keep required reviewers disabled.
6. Keep environment secrets empty.
7. Configure:
   - `CLOUDDOC_DEV_DEPLOY_IDENTITY_ROLE_ARN`;
   - `CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN`.
8. Verify no static credential secret exists.

### Phase 3 — Prove controlled deployment

1. Run a new Terraform Plan workflow on the current `main`.
2. Review the sanitized plan summary.
3. Record the successful plan workflow run ID.
4. Confirm the plan run is no older than 24 hours.
5. Start Terraform Deploy using:
   - the exact successful plan run ID;
   - confirmation `APPLY-DEV`;
   - destructive changes disabled unless explicitly reviewed.
6. Verify:
   - referenced plan-run validation;
   - attestation artifact download;
   - attestation schema validation;
   - destructive-change validation;
   - deployment OIDC claim validation;
   - permissionless deployment identity assumption;
   - state-role assumption;
   - apply-role assumption;
   - regenerated plan;
   - fingerprint comparison;
   - verified no-op or exact regenerated-plan apply;
   - post-apply convergence;
   - temporary-file cleanup.

## Running Terraform Plan

From GitHub:

```text
Actions
    → Terraform Plan
    → Run workflow
    → Branch: main
```

The workflow is manual only.

Expected outputs:

```text
sanitized GitHub step summary
clouddoc-terraform-plan-attestation artifact
```

Artifact contents:

```text
terraform-plan-attestation.json
```

Retention:

```text
1 day
```

The workflow must not retain:

```text
clouddoc.tfplan
clouddoc.tfplan.json
terraform-show.json
Terraform state
backend override
Lambda package artifact
```

## Reviewing the Plan

Review:

- overall plan result;
- create count;
- update count;
- delete count;
- replacement count;
- no-op count;
- sanitized resource type;
- sanitized resource address;
- whether destructive changes exist.

The summary is intentionally value-free.

Do not expect resource before and after values in the GitHub summary or
attestation.

## Running Terraform Deploy

From GitHub:

```text
Actions
    → Terraform Deploy
    → Run workflow
    → Branch: main
```

Inputs:

### `plan_run_id`

Enter the exact successful Terraform Plan workflow run ID.

Example shape:

```text
123456789
```

### `confirmation`

Enter exactly:

```text
APPLY-DEV
```

Any other value fails before AWS credentials.

### `allow_destructive_changes`

Default:

```text
false
```

Set to `true` only after reviewing every delete and replacement in the plan
summary.

## Deployment Validation Sequence

The reusable deploy workflow validates, in order:

1. repository;
2. branch;
3. event;
4. commit SHA format;
5. region;
6. account identifier format;
7. deployment identity role name;
8. state role name;
9. apply role name;
10. state-bucket naming contract;
11. manual confirmation;
12. referenced plan workflow run;
13. referenced plan age;
14. referenced plan result;
15. referenced plan commit;
16. attestation artifact identity;
17. attestation file set;
18. attestation schema;
19. attestation fingerprint;
20. destructive-change authorization;
21. GitHub OIDC claims;
22. AWS deployment identity;
23. repository checkout;
24. Lambda package;
25. regenerated Terraform plan;
26. regenerated attestation;
27. fingerprint equality;
28. exact regenerated-plan apply;
29. post-apply convergence;
30. cleanup.

Security-sensitive validation occurs before AWS credentials are requested.

## Attestation Contract

Artifact:

```text
clouddoc-terraform-plan-attestation
```

File:

```text
terraform-plan-attestation.json
```

Top-level fields:

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

The attestation is rejected when:

- an expected field is missing;
- an unknown field exists;
- context does not match;
- fingerprint validation fails;
- resource action normalization fails;
- destructive changes are not authorized.

The attestation does not contain Terraform resource values.

## Fingerprint Behavior

The workflow compares:

```text
reviewed attestation fingerprint
regenerated attestation fingerprint
```

The fingerprint represents:

```text
canonical value-free change-set projection
```

It does not represent binary-plan equality.

A mismatch means the reviewed and deployment-time change sets are not
equivalent under the approved projection.

On mismatch:

1. deployment stops before apply;
2. no bypass is available;
3. run a new Terraform Plan workflow;
4. review the new summary;
5. start a new deployment using the new run ID.

## Destructive Changes

Destructive actions:

```text
delete
replace
```

Default behavior:

```text
allow_destructive_changes = false
```

When the reviewed attestation contains a destructive action and the input
remains false, deployment fails before AWS credentials.

To authorize destructive changes:

1. review every destructive resource in the plan summary;
2. confirm the change is intentional;
3. start a new deploy run;
4. enter `APPLY-DEV`;
5. set `allow_destructive_changes` to true.

The input is an explicit operational authorization, not an independent human
approval.

## No-Op Deployment

When the reviewed and regenerated plans both contain no changes:

```text
authorization:
    verified

fingerprint:
    matched

terraform apply:
    skipped

post-apply convergence:
    not required

workflow result:
    success

cleanup:
    required
```

A verified no-op is a valid deployment result.

## Apply Behavior

When changes exist and fingerprints match:

1. the workflow applies the exact saved plan generated in the current deploy
   invocation;
2. no downloaded binary plan is used;
3. no second plan is generated between comparison and apply;
4. the workflow runs a post-apply convergence plan;
5. the workflow succeeds only when convergence produces no changes.

## Concurrency and Locking

Deployment workflow concurrency:

```text
group:
    clouddoc-terraform-deploy-dev

cancel-in-progress:
    false
```

A second deployment waits rather than cancelling the active deployment.

Terraform backend locking:

```text
native S3 lockfile
lock timeout:
    5m
```

Plan and deploy may run concurrently.

Terraform locking remains the correctness mechanism for backend operations.

## Temporary Files

Deployment temporary root:

```text
$RUNNER_TEMP/clouddoc-terraform-deploy
```

Temporary files may include:

```text
downloaded attestation
validated run output
regenerated binary plan
local deployment manifest
regenerated full plan JSON
regenerated attestation
post-apply convergence plan
ephemeral backend override
```

Cleanup:

```text
runs on success
runs on failure
removes the complete temporary root
is verified by a separate always-running step
```

Cleanup failure fails the workflow.

## Expected Successful Evidence

A successful deployment run should show:

```text
trusted context validated
plan workflow run validated
attestation downloaded
attestation validated
destructive authorization validated
eight OIDC claims validated
deployment identity verified
repository checkout verified
Lambda package verified
regenerated plan completed
change-set fingerprint matched
verified no-op or apply completed
post-apply convergence verified
temporary directory removed
```

AWS CloudTrail should show:

```text
AssumeRoleWithWebIdentity:
    clouddoc-dev-github-deploy-identity

AssumeRole:
    clouddoc-dev-terraform-state

AssumeRole:
    clouddoc-dev-terraform-apply
```

## Negative Authorization Proofs

After the positive path works, collect negative evidence.

### Wrong confirmation

Run with:

```text
confirmation:
    anything other than APPLY-DEV
```

Expected:

```text
failure before API artifact use and AWS credentials
```

### Expired plan run

Use a successful plan run older than 24 hours.

Expected:

```text
referenced plan rejected
no AWS credentials
```

### Wrong or stale plan commit

Use a plan run from an earlier `main` commit.

Expected:

```text
commit mismatch
no AWS credentials
```

### Destructive plan without opt-in

Use a plan containing delete or replace with:

```text
allow_destructive_changes:
    false
```

Expected:

```text
failure before AWS credentials
```

### Tampered attestation

This proof should be performed only through a controlled test artifact or unit
test, not by altering production evidence.

Expected:

```text
schema or fingerprint failure
no AWS credentials
```

### Plan identity attempting apply-role assumption

Use an explicit, non-mutating STS authorization check from the plan identity
context when operationally safe.

Expected:

```text
AccessDenied
```

Do not attach temporary permissions to perform this proof.

### Deploy identity attempting plan-role assumption

Expected:

```text
AccessDenied
```

### Apply role attempting Terraform state access

Use IAM policy analysis or an approved non-destructive authorization
verification.

Expected:

```text
denied
```

Do not read or modify production state merely to prove denial.

## Failure Handling

### Referenced plan validation failure

Action:

1. verify the run ID;
2. verify the plan run completed successfully;
3. verify it belongs to `Terraform Plan`;
4. verify it targeted current `main`;
5. run a new plan when stale or expired.

### Artifact missing

Action:

1. confirm the plan workflow completed after attestation support was merged;
2. confirm artifact retention has not expired;
3. run a new plan;
4. do not manually construct an attestation.

### OIDC claim mismatch

Action:

1. stop deployment;
2. compare the workflow context with the exact trust contract;
3. inspect:
   - repository;
   - ref;
   - environment;
   - reusable workflow ref;
4. do not widen the trust policy with wildcards.

### Deployment identity assumption denied

Action:

1. verify the deployment identity bootstrap was applied;
2. verify `dev-deploy` exists;
3. verify the workflow runs from `main`;
4. verify the exact workflow ref;
5. verify the repository variable points to the expected role;
6. do not attach permissions to the identity role.

### State-role assumption denied

Action:

1. verify the state-role trust includes the deployment identity;
2. verify the exact account and role names;
3. verify the authorization bootstrap was applied;
4. do not grant state access directly to the deployment identity.

### Apply-role assumption denied

Action:

1. verify apply-role trust contains only the deployment identity;
2. verify the apply-role repository variable;
3. verify the authorization bootstrap was applied;
4. do not let the existing plan identity assume the apply role.

### Apply permission denied

Action:

1. preserve the workflow failure;
2. identify the exact denied AWS action;
3. verify the action is required by a current managed Terraform resource;
4. determine the narrowest supported resource scope;
5. update authorization source;
6. add tests;
7. review and merge the authorization change;
8. apply the authorization bootstrap;
9. generate a new Terraform Plan;
10. run a new deployment.

Do not attach:

```text
AdministratorAccess
PowerUserAccess
ReadOnlyAccess
service-wide wildcard actions
```

### Fingerprint mismatch

Action:

1. do not rerun deploy with the same plan run;
2. run a new Terraform Plan;
3. review the new summary;
4. start a new deployment using the new run ID.

### Terraform partial apply

Terraform is not transactional across arbitrary AWS services.

Action:

1. preserve workflow evidence;
2. preserve CloudTrail evidence;
3. do not blindly rerun deployment;
4. inspect Terraform state;
5. inspect AWS resources;
6. run a new speculative plan;
7. classify completed and incomplete changes;
8. repair through a new reviewed deployment;
9. use state repair only through an incident procedure.

No automatic rollback is claimed.

### Post-apply non-convergence

Action:

1. preserve workflow evidence;
2. do not execute a second automatic apply;
3. run a new Terraform Plan;
4. inspect remaining drift;
5. correct configuration or authorization;
6. start a new reviewed deployment.

### Cleanup failure

Action:

1. treat the workflow as failed;
2. inspect only filenames and cleanup logs;
3. do not upload temporary plan files;
4. confirm no sensitive files were copied outside runner temp;
5. fix cleanup before the next deployment.

## Rollback Strategy

CloudDoc does not implement automatic Terraform rollback.

A rollback is a new forward deployment:

1. restore or modify Terraform source to the intended state;
2. open and merge a reviewed code change;
3. run Terraform Plan;
4. review the sanitized plan;
5. run Terraform Deploy using the new plan run ID.

Manual AWS console changes are not the default rollback mechanism.

Manual Terraform state changes require an incident procedure.

## Audit Evidence

Retain:

```text
pull request
commit SHA
plan workflow run
plan step summary
plan attestation artifact metadata
deploy workflow run
manual deploy inputs
deployment step summary
GitHub Environment deployment record
CloudTrail STS events
CloudTrail infrastructure API events
test results
authorization correction pull requests
```

Do not retain:

```text
binary Terraform plan
full Terraform JSON plan
Terraform state copy
temporary backend override
OIDC token
GitHub token
AWS credentials
```

## Completion Checklist

### Source

- [ ] Deployment identity source is merged.
- [ ] Apply-role source is merged.
- [ ] Plan attestation source is merged.
- [ ] Deploy request validator is merged.
- [ ] Deploy workflows are merged.
- [ ] Tests are green.
- [ ] Documentation is merged.

### Plan activation

- [ ] Plan OIDC trust is applied.
- [ ] State and plan roles are applied.
- [ ] Plan repository variables are configured.
- [ ] Live plan identity proof succeeds.
- [ ] Live remote-state-backed plan succeeds.
- [ ] Attestation artifact is produced.
- [ ] Plan cleanup succeeds.

### Deploy activation

- [ ] Deployment identity is applied.
- [ ] State-role trust extension is applied.
- [ ] Apply role and policy are applied.
- [ ] `dev-deploy` exists.
- [ ] `dev-deploy` is restricted to `main`.
- [ ] Required reviewers remain intentionally disabled.
- [ ] Environment secrets remain empty.
- [ ] Deployment repository variables are configured.
- [ ] No static AWS credentials exist.

### Operational proof

- [ ] Fresh plan run succeeds.
- [ ] Plan summary is reviewed.
- [ ] Plan attestation validates.
- [ ] Deploy request validation succeeds.
- [ ] Deployment OIDC claims validate.
- [ ] Deployment identity assumption succeeds.
- [ ] State-role assumption succeeds.
- [ ] Apply-role assumption succeeds.
- [ ] Fingerprint comparison succeeds.
- [ ] Verified no-op or exact regenerated-plan apply succeeds.
- [ ] Post-apply convergence succeeds.
- [ ] Cleanup succeeds.
- [ ] Negative authorization proofs are recorded.

## Intentional Deferrals

The current architecture intentionally defers:

- production deployment;
- cross-account deployment;
- team-based required reviewers;
- multi-party approval;
- pull-request deployment;
- scheduled deployment;
- automatic deployment;
- automatic rollback;
- persistent saved-plan promotion;
- HCP Terraform;
- policy-as-code platform integration;
- automatic state repair;
- blue/green infrastructure deployment.

These are separate operational capabilities, not missing pieces of the current
single-operator `dev` deployment model.

## Portfolio Narrative

The project should describe the operating decision as:

```text
CloudDoc intentionally implements a controlled single-operator Terraform
deployment model.

The project does not simulate independent approval through an artificial
second account. Instead, it separates plan and deployment identities, uses a
permissionless deployment workload identity, scopes a dedicated apply role,
binds deployment to a successful plan run and exact commit, compares a
value-free change-set fingerprint, requires explicit destructive-change
authorization, prevents concurrent deployments, and preserves audit evidence.

Independent GitHub Environment reviewers can be added when the system is
operated by a team without redesigning the AWS authorization boundaries.
```

## Related Documentation

- `docs/architecture/terraform-deployment-authorization.md`
- `docs/architecture/terraform-plan-authorization.md`
- `docs/architecture/github-oidc-trust-bootstrap.md`
- `docs/architecture/terraform-state-and-environment-workflow.md`
- `docs/adr/ADR-027-separate-terraform-state-plan-and-apply-authorization.md`
- `docs/adr/ADR-028-controlled-single-operator-terraform-deployment.md`
- `infra/bootstrap/github-oidc/README.md`
- `infra/bootstrap/terraform-authorization/README.md`
- `infra/terraform/README.md`