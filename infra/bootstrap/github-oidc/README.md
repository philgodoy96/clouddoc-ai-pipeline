# CloudDoc GitHub OIDC Trust Bootstrap

## Purpose

This Terraform root creates the initial AWS trust substrate required for GitHub Actions OpenID Connect federation.

It creates:

```text
GitHub Actions IAM OIDC provider
permissionless development identity verification role
permissionless Terraform deployment identity role
strict AssumeRoleWithWebIdentity trust policies
```

It does not grant CloudDoc plan or deployment authorization permissions.

The identity roles can prove that an approved GitHub workflow has authenticated successfully, but they cannot read Terraform state, plan infrastructure, apply infrastructure, or manage application resources. Downstream authorization roles remain owned by `../terraform-authorization/`.

## Ownership Boundary

This root owns only:

```text
GitHub Actions IAM OIDC provider
GitHub development identity verification role
GitHub Terraform deployment identity role
role trust policies
identity-bootstrap outputs
```

It does not own:

```text
Terraform state bucket
application Terraform state
state access policies
plan authorization policies
apply authorization policies
deployment policies
Lambda deployment
DynamoDB access
SQS access
S3 application access
API Gateway access
CloudWatch access
IAM PassRole
GitHub Environment configuration
GitHub repository variables
```

## Authentication Before Authorization

CloudDoc separates two concerns:

```text
Authentication
    → Which GitHub workload is calling AWS?

Authorization
    → What may that workload do after authentication?
```

This root implements authentication only.

Both identity roles have:

```text
no inline policies
no managed policies
no state permissions
no application permissions
```

Terraform state, plan, and apply authorization are implemented as a separate authorization boundary in repository source. This root remains authentication only; the authorization roles are owned by `../terraform-authorization/README.md`. Source is implemented; AWS apply of the extended trust and the deployment identity remains pending.

## Terraform Root

```text
infra/bootstrap/github-oidc
```

This root is intentionally separate from:

```text
infra/bootstrap/terraform-state
infra/terraform
```

The GitHub trust substrate and the Terraform state substrate have different recovery, security, and change boundaries.

## State Model

This bootstrap root intentionally uses local Terraform state.

The root cannot rely on GitHub OIDC to create the trust relationship that GitHub OIDC itself requires.

After the first successful apply:

1. Protect the local state from accidental deletion.
2. Store a secure backup outside the repository.
3. Never commit the state file.
4. Use the root only for deliberate identity-trust maintenance.
5. Recover lost bindings through reviewed Terraform import.

## Resources

```text
aws_iam_openid_connect_provider.github_actions
aws_iam_role.github_dev_identity
aws_iam_role.github_dev_deploy_identity
```

No permission policy resource is declared.

## Identity Roles

### Plan and identity verification role

Default role name:

```text
clouddoc-dev-github-identity
```

Trusted reusable workflows:

```text
reusable-aws-identity.yml
reusable-terraform-plan.yml
```

Trusted environment:

```text
dev
```

### Deployment identity role

Default role name:

```text
clouddoc-dev-github-deploy-identity
```

Trusted reusable workflow:

```text
reusable-terraform-deploy.yml
```

Trusted environment:

```text
dev-deploy
```

Both roles share this contract:

```text
permissionless identity roles
maximum session duration = 3600 seconds
no inline policies
no managed policies
no permissions boundary in this slice
exact eight-claim trust
StringEquals only
no wildcard
```

The deployment identity is intentionally separate from the plan identity so that plan workflows cannot assume the Terraform apply role. The existing identity role is therefore not reused for apply authorization.

Workflow ownership:

```text
existing identity:
    reusable-aws-identity.yml
    reusable-terraform-plan.yml

deployment identity:
    reusable-terraform-deploy.yml
```

Environment separation:

```text
plan identity:
    dev

deployment identity:
    dev-deploy
```

The identity verification and plan workflows request a 900-second session. The deployment identity remains source implemented; AWS apply is pending. Do not document the deployment identity as already present in AWS.

## OIDC Provider Contract

Issuer:

```text
https://token.actions.githubusercontent.com
```

Audience:

```text
sts.amazonaws.com
```

The Terraform resource does not pin a legacy GitHub certificate thumbprint.

AWS validates public OIDC providers through its trusted CA library and can retrieve a thumbprint when required.

## Trust Policy

Both permissionless roles allow only:

```text
sts:AssumeRoleWithWebIdentity
```

Federated principal:

```text
GitHub Actions IAM OIDC provider created by this root
```

All conditions use exact `StringEquals` comparisons.

Required token claims for both roles:

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

Eight exact claims. No wildcard.

### Exact subject condition

AWS evaluates the environment-scoped subject through:

```text
token.actions.githubusercontent.com:sub
```

The ID-qualified subjects are constructed from reviewed Terraform variables.

Plan identity subject shape:

```text
repo:philgodoy96@<github_repository_owner_id>/clouddoc-ai-pipeline@<github_repository_id>:environment:dev
```

Deployment identity subject shape:

```text
repo:philgodoy96@<github_repository_owner_id>/clouddoc-ai-pipeline@<github_repository_id>:environment:dev-deploy
```

The exact subject condition:

```text
is exact
is environment-scoped
embeds the immutable repository ID
embeds the immutable repository-owner ID
complements the separate repository_id and repository_owner_id claims
complements job_workflow_ref
contains no wildcard
```

`job_workflow_ref` remains ref-based.

Plan identity trusts exactly two reusable workflows on `refs/heads/main`:

```text
...reusable-aws-identity.yml@refs/heads/main
...reusable-terraform-plan.yml@refs/heads/main
```

Deployment identity trusts exactly one reusable workflow on `refs/heads/main`:

```text
...reusable-terraform-deploy.yml@refs/heads/main
```

`job_workflow_sha` is a separate GitHub claim and is intentionally not part of this trust contract.

Default trusted values for the plan identity:

```text
aud
    = sts.amazonaws.com

sub
    = repo:philgodoy96@<github_repository_owner_id>/
      clouddoc-ai-pipeline@<github_repository_id>:environment:dev

repository
    = philgodoy96/clouddoc-ai-pipeline

ref
    = refs/heads/main

environment
    = dev

job_workflow_ref
    = philgodoy96/clouddoc-ai-pipeline/.github/workflows/
      reusable-aws-identity.yml@refs/heads/main
      or
      reusable-terraform-plan.yml@refs/heads/main
```

Default trusted values for the deployment identity:

```text
aud
    = sts.amazonaws.com

sub
    = repo:philgodoy96@<github_repository_owner_id>/
      clouddoc-ai-pipeline@<github_repository_id>:environment:dev-deploy

repository
    = philgodoy96/clouddoc-ai-pipeline

ref
    = refs/heads/main

environment
    = dev-deploy

job_workflow_ref
    = philgodoy96/clouddoc-ai-pipeline/.github/workflows/
      reusable-terraform-deploy.yml@refs/heads/main
```

The immutable numeric repository and owner IDs are required runtime inputs.

## Incident Note

An initial identity verification run reached AWS STS but was denied because
the role trust did not evaluate `sub`.

CloudTrail showed that this repository receives an ID-qualified environment
subject.

The source hotfix adds the exact subject condition.

The corrected trust contract is implemented in repository source.

It is not yet applied to the AWS role and has not yet been re-verified through
the AWS Identity Check workflow.

## OIDC claim preflight

The reusable AWS identity workflow performs a permanent OIDC claim preflight
before AWS credential configuration.

Final runtime step order:

```text
Validate trusted workflow context
Validate GitHub OIDC token claims
Configure temporary AWS credentials
Verify assumed AWS identity
```

The OIDC claim preflight is a fail-fast identity contract. It:

```text
requests a GitHub OIDC token with audience sts.amazonaws.com
decodes only the JWT payload in process memory
validates eight exact claims
logs only sanitized claim diagnostics
fails before AWS STS when a claim differs
uses Python standard library only
does not use a third-party OIDC debugger action
never prints or stores the JWT
never prints the GitHub runtime request token
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

Expected immutable subject shape:

```text
repo:<owner>@<owner_id>/<repository>@<repository_id>:environment:<environment>
```

CloudDoc subject shape with placeholders:

```text
repo:philgodoy96@<github_repository_owner_id>/clouddoc-ai-pipeline@<github_repository_id>:environment:dev
```

`job_workflow_ref` remains ref-based. `job_workflow_sha` is not part of this
contract.

### Preflight security boundary

```text
The preflight does not validate the JWT signature or issuer.

AWS STS and IAM remain authoritative for cryptographic token validation,
provider trust, and role-assumption authorization.
```

Process-memory-only token handling keeps the JWT in the Python process.
AWS remains authoritative for signature and issuer verification and for IAM
trust-policy evaluation. Authentication before authorization still applies:
the role remains a permissionless identity role.

### Preflight failure modes

```text
Preflight claim mismatch
    → workflow fails before AWS credential configuration

OIDC token request unavailable
    → workflow fails before AWS credential configuration

Malformed JWT payload
    → workflow fails before AWS credential configuration

All preflight claims match but AWS denies assume-role
    → investigate provider trust, effective IAM trust, or AWS-side validation
```

### Current operational status

```text
source trust correction implemented
OIDC claim preflight implemented in the reusable workflow
second exact reusable workflow trust entry for plan implemented in source
deployment identity role implemented in source
AWS trust extension not yet applied
deployment identity not yet present in AWS
Terraform plan federation not yet verified
controlled deploy federation not yet verified
both roles remain permissionless
```

## Wildcard Boundary

The trust policy contains no wildcard condition.

It does not trust:

```text
all repositories owned by the user
all workflows in the repository
all branches
all environments
pull request refs
tags
forks
```

A repository rename or workflow-path change requires a reviewed trust-policy update even though immutable repository IDs remain stable.

## Required Inputs

Copy:

```text
terraform.tfvars.example
```

to ignored:

```text
terraform.tfvars
```

Then replace:

```text
REPLACE_WITH_GITHUB_REPOSITORY_ID
REPLACE_WITH_GITHUB_REPOSITORY_OWNER_ID
```

The IDs are identifiers, not secrets.

Key workflow-ref inputs remain reviewed source contracts:

```text
github_identity_workflow_ref
github_terraform_plan_workflow_ref
github_trusted_workflow_refs
github_terraform_deploy_workflow_ref
github_deploy_environment
```

Expected default values for the plan identity allowlist are the two exact reusable workflows pinned to `refs/heads/main`:

```text
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main
```

Expected default value for the deployment identity is:

```text
philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main
```

with environment:

```text
dev-deploy
```

Both identity roles remain permissionless. Do not add plan, state, or apply permissions here. Do not invent the IDs.

## Prerequisites for Offline Validation

```text
Terraform >= 1.10.0 and < 2.0.0
reviewed AWS provider lock file
```

AWS authentication is not required for formatting or static validation.

## Prerequisites for Real Plan and Apply

```text
temporary human AWS authentication
permission to create an IAM OIDC provider
permission to create the IAM roles
permission to configure the role trust policies
confirmed target AWS account
confirmed GitHub repository and owner IDs
reviewed saved plan
```

Do not use root-user access keys.

Do not place credentials in Terraform files.

Post-merge bootstrap apply is required before repository variables can consume the new deployment-identity outputs. Source implementation does not mean the deployment identity already exists in AWS.

## Initialize Offline

From the repository root:

```powershell
terraform -chdir=infra/bootstrap/github-oidc init `
  -backend=false `
  -lockfile=readonly `
  -input=false
```

## Validate Offline

```powershell
terraform -chdir=infra/bootstrap/github-oidc fmt -check -recursive
terraform -chdir=infra/bootstrap/github-oidc validate
```

No AWS API call is required for these checks.

## Real Initialization

Real bootstrap execution will occur only after:

```text
implementation review
offline tests
pull request review
trust-policy review
human AWS authentication setup
target account verification
```

At that time:

```powershell
Copy-Item `
  "infra/bootstrap/github-oidc/terraform.tfvars.example" `
  "infra/bootstrap/github-oidc/terraform.tfvars"

terraform -chdir=infra/bootstrap/github-oidc init
```

Replace the placeholder IDs before planning.

## Plan

Create a saved plan:

```powershell
terraform -chdir=infra/bootstrap/github-oidc plan `
  -input=false `
  -out="github-oidc-bootstrap.tfplan"
```

Review it:

```powershell
terraform -chdir=infra/bootstrap/github-oidc show `
  "github-oidc-bootstrap.tfplan"
```

The plan must contain only:

```text
one GitHub IAM OIDC provider
one permissionless plan/identity role
one permissionless deployment identity role
exact trust policies using StringEquals only
plan identity trust for two reviewed reusable workflow refs on main
deployment identity trust for reusable-terraform-deploy.yml on main
```

## Apply

Apply only the reviewed saved plan:

```powershell
terraform -chdir=infra/bootstrap/github-oidc apply `
  "github-oidc-bootstrap.tfplan"
```

Do not use:

```text
-auto-approve
```

## Outputs

```powershell
terraform -chdir=infra/bootstrap/github-oidc output
```

Available outputs:

```text
github_oidc_provider_arn
github_dev_identity_role_name
github_dev_identity_role_arn
github_dev_identity_role_max_session_duration
github_deploy_identity_role_name
github_deploy_identity_role_arn
github_deploy_identity_role_max_session_duration
github_repository_identity
github_identity_workflow_ref
github_deploy_environment
github_terraform_deploy_workflow_ref
github_deploy_trusted_repository_identity
github_trusted_workflow_refs
```

No credential or token is an output. `github_trusted_workflow_refs` should show exactly the two reviewed plan/identity reusable workflows on `refs/heads/main`. `github_terraform_deploy_workflow_ref` should show the exact deploy reusable workflow on `refs/heads/main`. Use the identity and deployment role ARN outputs when configuring repository variables after AWS apply.

## GitHub Configuration Boundary

After the root is applied, GitHub repository configuration will require:

```text
GitHub Environment: dev
GitHub Environment: dev-deploy
repository variables with the AWS account ID
repository variables with the plan identity role ARN
repository variables with the deployment identity role ARN
main-only environment deployment branch rules
```

No AWS access key or secret key will be added to GitHub.

## Failure Modes

### Missing exact sub condition

```text
AWS denies AssumeRoleWithWebIdentity
```

### Classic owner/repository subject used instead of the ID-qualified subject

```text
AWS denies role assumption
```

### Incorrect repository or owner numeric IDs inside the subject

```text
AWS denies role assumption
```

### Wrong repository ID

```text
role assumption denied
```

### Wrong repository owner ID

```text
role assumption denied
```

### Workflow outside main

```text
ref claim mismatch
role assumption denied
```

### Wrong reusable workflow

```text
job_workflow_ref mismatch
role assumption denied
```

### GitHub Environment absent

```text
environment claim unavailable
role assumption denied
```

### Role receives an application permission

```text
security contract violated
review and tests must fail
```

### Bootstrap state lost

```text
reviewed Terraform import or recovery required
```

## Security Invariants

```text
No AWS access keys are committed.

The trust evaluates the exact ID-qualified subject.

Plan identity subject is scoped to the dev environment.

Deployment identity subject is scoped to the dev-deploy environment.

The subject contains no wildcard.

The trust policy uses immutable repository and owner IDs.

The trust policy requires the exact repository name.

The trust policy requires refs/heads/main.

Plan identity requires the dev environment.

Deployment identity requires the dev-deploy environment.

Plan identity requires exactly two reusable workflows on main.

Deployment identity requires exactly one reusable deploy workflow on main.

All trust conditions use StringEquals.

No wildcard claim is allowed.

Only AssumeRoleWithWebIdentity is trusted.

Both roles have no authorization policies.

Local bootstrap state remains outside Git.
```

## Intentionally Deferred

```text
corrective AWS role trust apply
AWS Identity Check re-verification
AWS apply of the deployment identity
Terraform plan federation verification
controlled deploy federation verification
staging identity
production identity
cross-account deployment
permissions boundary
CloudTrail alerting
team-based reviewers
multi-party approval
```

Authorization policies for state, plan, and apply remain owned by the separate Terraform authorization bootstrap. These capabilities require separate implementation, review, and operational evidence.

## Related Documentation

- [Terraform State Bootstrap](../terraform-state/README.md)
- [Terraform Authorization Bootstrap](../terraform-authorization/README.md)
- [Terraform Plan Authorization](../../../docs/architecture/terraform-plan-authorization.md)
- [Terraform Deployment Authorization](../../../docs/architecture/terraform-deployment-authorization.md)
- [Terraform Plan Workflow Runbook](../../../docs/operations/terraform-plan-workflow.md)
- [Terraform Deploy Workflow Runbook](../../../docs/operations/terraform-deploy-workflow.md)
- [Terraform State and Environment Workflow](../../../docs/architecture/terraform-state-and-environment-workflow.md)
- [Infrastructure CI Validation](../../../docs/architecture/infrastructure-ci-validation.md)
- [ADR-028: Controlled Single-Operator Terraform Deployment](../../../docs/adr/ADR-028-controlled-single-operator-terraform-deployment.md)
