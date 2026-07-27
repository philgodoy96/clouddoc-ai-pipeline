# CloudDoc Terraform State Bootstrap

## Purpose

This root creates the account-scoped Amazon S3 bucket used by the CloudDoc application Terraform root for durable remote state and S3-native lockfiles.

It is intentionally separate from `infra/terraform` because the application root cannot create the backend it already depends on.

## Ownership Boundary

This bootstrap root owns only:

```text
account-scoped Terraform state bucket
public-access controls
bucket ownership controls
default server-side encryption
object versioning
state-version lifecycle retention
HTTPS-only bucket policy
```

It does not own:

```text
CloudDoc application resources
environment state objects
deployment identities
GitHub OIDC roles
state-access IAM policies
DynamoDB locking
```

## State Model

The bootstrap root intentionally uses local Terraform state.

That local state is an account-foundation artifact and is not part of the routine CloudDoc application deployment workflow.

After the first successful apply:

1. Protect the local bootstrap state from accidental deletion.
2. Store a secure backup outside the repository.
3. Never commit the state file.
4. Use this root only for deliberate state-bucket maintenance.
5. Recover a lost binding through reviewed Terraform import rather than recreating the bucket.

## Bucket Naming

The bucket name is derived as:

```text
${project_name}-${aws_account_id}-terraform-state
```

Example:

```text
clouddoc-123456789012-terraform-state
```

One AWS account receives one CloudDoc state bucket. Application environments later use independent keys inside that bucket.

## Security and Recovery Controls

The root declares:

```text
force_destroy = false
lifecycle.prevent_destroy = true
all public access blocked
BucketOwnerEnforced object ownership
AES256 default encryption
versioning enabled
HTTPS-only bucket policy
365-day default noncurrent-version retention
one-day incomplete multipart cleanup
```

The lifecycle retention period is configurable from 30 through 3650 days.

## Prerequisites

```text
Terraform >= 1.10.0 and < 2.0.0
AWS credentials for the intended account
permission to create and configure an S3 bucket
an explicitly selected AWS Region
```

Credentials must come from the standard AWS authentication chain. Do not place credentials in Terraform files.

## Initialize

From the repository root:

```powershell
Copy-Item `
  "infra/bootstrap/terraform-state/terraform.tfvars.example" `
  "infra/bootstrap/terraform-state/terraform.tfvars"

terraform -chdir=infra/bootstrap/terraform-state init
```

The committed dependency lock file is shared from the application Terraform root so both roots use the same reviewed AWS provider version.

## Validate

```powershell
terraform -chdir=infra/bootstrap/terraform-state fmt -check -recursive
terraform -chdir=infra/bootstrap/terraform-state validate
```

## Review the Target Account

Before planning:

```powershell
aws sts get-caller-identity
```

Confirm that the returned AWS account is the intended state-owning account.

The bucket name includes this account ID, but the operator remains responsible for selecting the correct credentials.

## Plan

```powershell
terraform -chdir=infra/bootstrap/terraform-state plan `
  -input=false `
  -out="terraform-state-bootstrap.tfplan"
```

The plan file is ignored by Git.

Review the plan before applying:

```powershell
terraform -chdir=infra/bootstrap/terraform-state show `
  "terraform-state-bootstrap.tfplan"
```

## Apply

Apply only the reviewed saved plan:

```powershell
terraform -chdir=infra/bootstrap/terraform-state apply `
  "terraform-state-bootstrap.tfplan"
```

Do not use `-auto-approve`.

## Read the Bucket Name

```powershell
terraform -chdir=infra/bootstrap/terraform-state output `
  -raw terraform_state_bucket_name
```

The value later becomes:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
```

for the guarded application Terraform workflow.

## Destruction Boundary

Routine destruction is intentionally unavailable.

The S3 bucket has both:

```text
force_destroy = false
prevent_destroy = true
```

Removing the state substrate requires an explicit code change, review, backup confirmation, environment-state inspection, and deliberate handling of retained object versions.

## Intentionally Deferred

```text
application backend configuration
S3-native application state locking
environment state keys
guarded plan and apply workflow
GitHub Actions
GitHub OIDC
state-access IAM roles
customer-managed KMS
cross-region replication
S3 Object Lock
CloudTrail data events
```

These capabilities are delivered by later commits or slices with separate ownership and approval contracts.