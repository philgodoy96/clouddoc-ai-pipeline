# ADR-026: Separate OIDC Authentication from Deployment Authorization

## Status

Accepted

## Date

2026-07-27

## Context

CloudDoc needs GitHub Actions to interact with AWS without storing long-lived AWS access keys in GitHub.

The project already has:

```text
credential-free Python validation
credential-free Lambda package validation
credential-free Terraform offline validation
S3 remote-state architecture
guarded local Terraform plan and apply workflow
```

The next platform capability is GitHub-to-AWS workload identity.

A common implementation path is to create one GitHub OIDC role that immediately receives broad permissions for:

```text
Terraform state
Terraform plan
Terraform apply
IAM
Lambda
S3
DynamoDB
SQS
API Gateway
CloudWatch
```

That approach combines multiple security decisions:

```text
who may authenticate
which workflow is trusted
which repository is trusted
which branch is trusted
which environment is trusted
what the role may access
what the role may mutate
how deployments are approved
```

It would be difficult to prove whether an OIDC failure came from:

```text
token issuance
claim mismatch
OIDC provider configuration
role trust
account selection
authorization policy
resource policy
Terraform behavior
deployment workflow behavior
```

CloudDoc needs a smaller trust boundary that can be reviewed, tested, provisioned, and verified before deployment authorization exists.

## Decision

CloudDoc will separate GitHub OIDC authentication from AWS deployment authorization.

The first OIDC role is:

```text
clouddoc-dev-github-identity
```

It is a permissionless identity-verification role.

The role:

```text
has an exact AssumeRoleWithWebIdentity trust policy
has no inline policies
has no managed policies
has no Terraform state permissions
has no application permissions
has no IAM PassRole permission
```

The role trust requires exact values for:

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

All eight conditions use `StringEquals`. No wildcard is allowed.

CloudDoc pins:

```text
repository name
immutable repository ID
immutable repository-owner ID
ID-qualified environment subject
main ref
dev environment
reusable workflow ref
```

The exact ID-qualified subject strategy:

```text
repo:${github_repository_owner}@${github_repository_owner_id}/${github_repository_name}@${github_repository_id}:environment:${github_environment}
```

Approved CloudDoc shape with placeholders:

```text
repo:philgodoy96@<github_repository_owner_id>/clouddoc-ai-pipeline@<github_repository_id>:environment:dev
```

AWS evaluates the subject through:

```text
token.actions.githubusercontent.com:sub
```

The trusted workload is:

```text
repository:
    philgodoy96/clouddoc-ai-pipeline

subject:
    repo:philgodoy96@<github_repository_owner_id>/
    clouddoc-ai-pipeline@<github_repository_id>:environment:dev

ref:
    refs/heads/main

environment:
    dev

reusable workflow:
    .github/workflows/reusable-aws-identity.yml@refs/heads/main
```

The numeric GitHub repository and owner IDs are required runtime inputs.

`job_workflow_ref` remains ref-based. `job_workflow_sha` is a separate claim and is intentionally not part of this trust contract.

The identity workflow:

```text
is manually triggered
uses a reviewed reusable workflow
performs no repository checkout
executes no project source
runs a permanent OIDC claim preflight before AWS credential configuration
requests a 900-second session
validates the expected AWS account
masks the AWS account ID
uses the GitHub run ID in the STS session name
proves identity with GetCallerIdentity
```

### OIDC claim preflight

CloudDoc validates the issued GitHub OIDC payload against the expected
workload identity contract before calling AWS STS.

The fail-fast identity contract:

```text
requests a token with audience sts.amazonaws.com
decodes only the JWT payload
compares eight exact claims
logs only sanitized claim diagnostics
fails before AWS STS on mismatch
uses process-memory-only token handling
uses Python standard library only
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

Why the preflight exists:

```text
generic AWS assume-role errors do not identify the mismatched claim
fail-fast diagnostics reduce unsafe trial-and-error trust changes
exact claim comparison supports least privilege
sanitized logs improve operability without exposing the JWT
```

Security boundaries:

```text
The preflight is not a trust anchor.
The preflight does not verify token signatures.
The preflight does not authorize AWS access.
AWS remains authoritative for token and IAM validation.
```

AWS remains authoritative for signature and issuer verification and for IAM
trust-policy evaluation. Authentication before authorization remains
unchanged: the role remains a permissionless identity role.

A later slice will introduce authorization through separate, least-privilege role and policy decisions.

## Decision Drivers

```text
avoid long-lived AWS credentials
minimize initial blast radius
separate authentication failures from authorization failures
make IAM trust independently reviewable
prove the OIDC path before state or deployment access
restrict trust to one repository workload
avoid broad repository or branch wildcards
support clear audit correlation
preserve small focused pull requests
keep each implementation commit testable
fail-fast identity contract before AWS STS
sanitized claim diagnostics without JWT exposure
```

## Trust Strategy

CloudDoc will not rely on a broad `sub` pattern or an implicit subject check.

The trust policy uses exact `StringEquals` conditions for:

```text
STS audience
exact ID-qualified subject
repository name
immutable repository ID
immutable repository-owner ID
main ref
dev environment
reviewed reusable workflow ref
```

This creates defense in depth across mutable and immutable identity attributes.

The exact subject condition is environment-scoped and embeds the immutable repository ID and immutable repository-owner ID.

The subject complements the separate `repository_id` and `repository_owner_id` claims and complements `job_workflow_ref`.

The role cannot be assumed by:

```text
another repository
another repository owned by the same user
a feature branch
a pull request
a tag
another environment
another workflow file
a fork
a classic owner/repository subject that does not match the ID-qualified token
```

## Workflow Strategy

OIDC permission is isolated.

Validation workflows retain:

```yaml
permissions:
  contents: read
```

Identity workflows receive:

```yaml
permissions:
  contents: read
  id-token: write
```

The reusable identity workflow performs no checkout.

The temporary AWS session therefore cannot execute repository-controlled application or infrastructure code during the identity proof.

## State Strategy

The OIDC bootstrap root uses local Terraform state.

GitHub OIDC cannot create the initial trust relationship that GitHub OIDC itself requires.

The first apply must use a pre-existing temporary human AWS session.

The local bootstrap state is:

```text
ignored by Git
backed up securely after apply
used rarely
recovered through reviewed import when necessary
```

## Consequences

### Positive

```text
No AWS access keys are stored in GitHub.

The initial AWS role has no application blast radius.

Trust-policy debugging is independent from deployment permissions.

The role can be verified through STS GetCallerIdentity.

The trust names one repository, branch, environment, and reusable workflow.

Immutable GitHub IDs remain stable across repository renames.

AWS receives an explicit shared-provider subject boundary.

The subject remains stable across repository/owner renames when IDs remain.

The environment is encoded directly in the subject.

The trust no longer depends on an implicit sub check.

Claim mismatches are visible before AWS STS retries.

Trust corrections can be evidence-driven.

No third-party OIDC debugger dependency is introduced.

JWT material is not persisted.

The identity workflow has a small auditable execution surface.

The STS session is correlated to a GitHub run ID.

Future authorization can be added incrementally.

Compromising the identity workflow does not immediately provide deployment access.
```

### Negative

```text
The project temporarily has an assumable role that cannot perform deployment work.

An additional Terraform bootstrap root must be maintained.

The first apply still requires a human AWS identity.

Local bootstrap state requires secure backup and recovery discipline.

GitHub Environment and repository variables require manual configuration.

Future authorization needs another design and implementation slice.

Exact workflow and branch conditions make intentional renames require trust-policy updates.

Incorrect numeric IDs make the role unassumable.

The subject must match the repository OIDC customization actually in effect.

Repository identity changes require a reviewed trust update.

The workflow contains additional security-sensitive validation logic.

GitHub claim-shape changes may fail the workflow before AWS.

Static tests must protect sanitization and ordering contracts.

The preflight cannot diagnose AWS-side signature or provider failures.
```

### Neutral

```text
AWS account IDs and role ARNs are stored as non-secret GitHub variables.

The role maximum session duration is 3600 seconds, while the verification workflow requests 900 seconds.

The identity workflow can call STS GetCallerIdentity without an attached identity policy.

Branch protection remains separate repository configuration.

The corrected trust contract is implemented in repository source.

It is not yet applied to the AWS role and has not yet been re-verified against AWS.
```

## Alternatives Considered

### Store AWS access keys in GitHub Secrets

Rejected.

Reasons:

```text
long-lived credentials
rotation burden
secret-distribution risk
larger incident-response surface
weaker workload identity
```

### Create one broad deployment role immediately

Rejected for this slice.

Reasons:

```text
combines authentication and authorization
larger blast radius
harder failure diagnosis
harder IAM review
premature state and deployment permissions
```

### Trust every workflow in the repository

Rejected.

Example:

```text
repo:philgodoy96/clouddoc-ai-pipeline:*
```

Reasons:

```text
any workflow change could reach AWS
pull-request and branch boundaries become harder to reason about
reusable workflow identity would not be enforced
```

### Classic owner/repository environment subject

Rejected for this repository because CloudTrail proved that the token
used the ID-qualified form.

Example of the rejected classic form:

```text
repo:philgodoy96/clouddoc-ai-pipeline:environment:dev
```

### Wildcard subject

Rejected because it broadens trust and violates the exact workload
boundary.

### Replace `job_workflow_ref` with SHA

Rejected because `job_workflow_ref` and `job_workflow_sha` are separate
claims, and no evidence identified workflow SHA as the failure.

`job_workflow_ref` remains ref-based:

```text
...reusable-aws-identity.yml@refs/heads/main
```

### Trust every repository owned by the user

Rejected.

Example:

```text
repo:philgodoy96/*
```

Reasons:

```text
cross-repository blast radius
unrelated repository compromise could reach CloudDoc AWS identity
weak portfolio-grade security posture
```

### Trust only the repository name

Rejected as the sole control.

Repository and owner names are human-readable but mutable.

CloudDoc also requires immutable numeric repository and owner IDs.

### Trust only immutable repository IDs

Rejected as the sole control.

Numeric IDs are strong identity anchors but are less readable during review.

CloudDoc keeps the repository claim as defense in depth and review context.

### Use feature-branch or pull-request OIDC

Rejected.

The identity role is intended for a reviewed workflow on `main`, not arbitrary branch execution.

### Combine OIDC bootstrap with Terraform state bootstrap

Rejected.

The roots have distinct:

```text
ownership
recovery
security
change cadence
operational purpose
```

### Use remote state for the OIDC bootstrap immediately

Rejected.

The initial OIDC trust is a bootstrap dependency and must not depend on the identity path it creates.

### Add a TLS provider for GitHub thumbprint calculation

Rejected for the current AWS integration.

The root avoids unnecessary certificate-scraping infrastructure and keeps the provider resource focused on issuer and audience.

### Permit checkout in the identity workflow

Rejected.

The identity proof requires no repository source.

No checkout reduces execution surface during the temporary AWS session.

### Rely only on configure-aws-credentials errors

Rejected.

The AWS credential-action error is too generic for safe trust diagnosis.
A permanent OIDC claim preflight provides sanitized claim diagnostics before
STS retries.

### Use a third-party OIDC debugger action

Rejected.

A third-party debugger would add another supply-chain dependency and an
unnecessary token exposure surface. CloudDoc keeps process-memory-only token
handling inside the reviewed reusable workflow.

### Print the JWT payload directly

Rejected.

Direct payload printing can expose immutable identifiers and other token
metadata beyond operational need. Logs may contain only sanitized claim
diagnostics.

### Remove strict trust conditions temporarily

Rejected.

Diagnosis must not broaden production trust. Fail-fast identity contract
validation must preserve exact claim comparison and least privilege.

## Security Invariants

```text
No static AWS credential in GitHub.

No static AWS credential in Terraform.

No OIDC permission in validation workflows.

Manual identity trigger only.

Workflow-call-only reusable identity workflow.

Exact repository identity.

Exact ID-qualified subject.

Exact main ref.

Exact dev environment.

Exact reusable workflow ref.

No wildcard trust value.

AssumeRoleWithWebIdentity only.

Permissionless verification role.

OIDC claim preflight before AWS credential configuration.

Process-memory-only token handling.

No JWT or runtime request-token logging.

AWS remains authoritative for signature, issuer, and IAM trust.

No project checkout during AWS session.

Expected AWS account validation.

15-minute requested session.

GitHub run ID in the STS session name.

Local bootstrap state outside Git.
```

## Verification

Offline verification:

```text
Terraform formatting
Terraform validation
mocked Terraform tests
static bootstrap tests
GitHub Actions source contracts
full repository quality gates
source tests require eight exact claims
CI contract tests validate the preflight source
```

Corrective and real verification requirements:

```text
CI contract tests validate the preflight source
manual AWS Identity Check validates real token claims
AWS STS validates cryptographic and IAM trust
GetCallerIdentity validates the assumed principal
role-policy inspection confirms the role remains permissionless
corrective Terraform plan must contain one in-place role update
effective AWS trust must contain exact ID-qualified sub
```

These corrective verification steps are not yet complete.
Manual AWS Identity Check validation is not yet complete.

Real verification also includes:

```text
apply OIDC bootstrap root
create dev GitHub Environment
configure account ID and role ARN variables
dispatch AWS Identity Check from main
observe successful AssumeRoleWithWebIdentity
observe expected GetCallerIdentity ARN
confirm an application API remains unauthorized
```

## Follow-Up Decisions

Future ADRs or implementation slices must decide:

```text
state-read and state-lock permissions
plan role versus apply role
environment-specific identities
GitHub Environment approval rules
artifact publication identity
IAM PassRole boundary
application resource permissions
deployment approval
saved-plan promotion
rollback authorization
CloudTrail alerting
cross-account architecture
permissions boundaries
session policies
```

## Related Documentation

- [GitHub OIDC Trust Bootstrap](../architecture/github-oidc-trust-bootstrap.md)
- [GitHub OIDC Bootstrap Root](../../infra/bootstrap/github-oidc/README.md)
- [Infrastructure CI Validation](../architecture/infrastructure-ci-validation.md)
- [Terraform State and Environment Workflow](../architecture/terraform-state-and-environment-workflow.md)
