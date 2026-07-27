# ADR-025: Use S3-Native Locking and Explicit Environment State

## Status

Accepted

## Context

CloudDoc has one Terraform application root that manages:

```text
API Gateway
Lambda
S3 document ingestion
SQS processing and dead-letter topology
DynamoDB
Amazon Bedrock permissions
CloudWatch logs
CloudWatch alarms
CloudWatch dashboard
```

The root supports:

```text
dev
staging
prod
```

Before this decision, the repository could validate Terraform offline but did not define a production-minded state and environment workflow.

Local Terraform state is sufficient for early isolated development but does not provide a durable collaborative deployment boundary.

The project requires controls for:

```text
durable state storage
concurrent writer exclusion
environment isolation
account targeting
saved-plan review
state recovery
credential exclusion
local-state migration safety
offline validation
future CI/CD compatibility
```

Terraform backend configuration cannot depend on ordinary Terraform variables.

The backend must therefore be configured separately from application variables.

The project also needs to remain executable offline without an AWS account during automated validation.

## Decision

CloudDoc will use:

```text
one account-scoped Amazon S3 state bucket
partial S3 backend configuration
S3-native lockfiles
explicit environment state keys
explicit environment tfvars files
environment-specific TF_DATA_DIR values
AWS provider allowed_account_ids
a guarded Python operator workflow
saved-plan integrity manifests
```

Terraform workspaces will not select CloudDoc environments.

DynamoDB will not be used for state locking.

## State Bucket Decision

A separate Terraform bootstrap root will create:

```text
${project_name}-${aws_account_id}-terraform-state
```

The bucket will be account-scoped.

It will contain independent state objects for CloudDoc environments.

The bootstrap root will intentionally retain local state because it creates the backend substrate.

## Bootstrap Protection Decision

The state bucket will declare:

```text
force_destroy = false
prevent_destroy = true
all public access blocked
BucketOwnerEnforced
AES256 default encryption
versioning enabled
HTTPS-only policy
noncurrent-version retention
incomplete multipart cleanup
```

The bootstrap root will not create application resources.

The application root will not create its own backend.

## Environment State Decision

CloudDoc will use explicit state keys:

```text
clouddoc/dev/terraform.tfstate
clouddoc/staging/terraform.tfstate
clouddoc/prod/terraform.tfstate
```

Each key receives an independent S3 lock object.

Environment identity will be encoded in:

```text
selected CLI argument
tfvars environment value
backend state key
Terraform metadata directory
saved-plan directory
plan manifest
```

A mismatch at any checked boundary will stop execution.

## S3-Native Locking Decision

Each backend file will declare:

```hcl
use_lockfile = true
```

The workflow will not provide a locking bypass.

The workflow will wait up to five minutes for plan and apply locks.

DynamoDB locking will not be introduced because S3-native locking satisfies the current requirement and avoids a second state-coordination resource.

## Partial Backend Decision

The application root will declare:

```hcl
terraform {
  backend "s3" {}
}
```

Committed backend files will contain only:

```text
key
region
encrypt
use_lockfile
```

The state bucket will be supplied during initialization.

Credentials will not be supplied through backend files.

## Terraform Version Decision

Both roots will require:

```text
>= 1.10.0
< 2.0.0
```

The lower bound matches the approved lockfile workflow.

The upper bound requires explicit review before a major Terraform upgrade.

The AWS provider remains constrained to:

```text
~> 5.0
```

## Environment File Decision

The repository will commit:

```text
dev.tfvars
staging.tfvars
prod.tfvars
dev.s3.tfbackend
staging.s3.tfbackend
prod.s3.tfbackend
```

These files contain no credentials, bucket name, expected account ID, profile, or role ARN.

## Terraform Workspace Decision

CloudDoc will not use Terraform workspaces to select dev, staging, or prod.

Workspaces create an implicit shell-selected input and make environment identity less visible during review.

Explicit files and paths are preferred.

## Metadata Isolation Decision

CloudDoc will set `TF_DATA_DIR` to an environment-specific directory.

This isolates:

```text
backend initialization metadata
provider installation metadata
environment execution context
```

Directories:

```text
.terraform-data/dev
.terraform-data/staging
.terraform-data/prod
.terraform-data/offline
```

They remain ignored by Git.

## Account Guard Decision

Authenticated operations will require:

```text
CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID
```

The workflow will pass it to:

```text
TF_VAR_expected_aws_account_id
```

The AWS provider will use:

```text
allowed_account_ids
```

The provider guard defaults to null for offline mocked tests.

## Bucket/Account Binding Decision

Authenticated operations will require:

```text
CLOUDDOC_TERRAFORM_STATE_BUCKET
```

The workflow will validate that the bucket equals:

```text
{project_name}-{expected_account_id}-terraform-state
```

This protects against a valid but unrelated bucket.

## Authentication Decision

The workflow will not manage AWS credentials.

Credentials will continue to come from an approved external authentication method.

The AWS CLI is not required for automated validation.

Identity configuration will occur only when real AWS bootstrap and deployment work begins.

## Saved-Plan Decision

Real planning will always produce:

```text
artifacts/terraform/{environment}/clouddoc.tfplan
```

Apply will accept only that saved plan.

The workflow will not expose direct apply from configuration.

The workflow will not use `-auto-approve`.

## Plan Manifest Decision

Every plan will receive a JSON manifest that binds:

```text
environment
project
Region
state bucket
state key
expected AWS account
TF_DATA_DIR
tfvars file
backend file
plan path
plan SHA-256
Terraform detailed exit code
```

Apply will validate the manifest and recalculate the plan hash.

The manifest is a local guard, not an external signature.

## Environment Confirmation Decision

Apply will require:

```text
--environment <environment>
--confirm-environment <environment>
```

The values must match.

The confirmation check occurs before environment loading or AWS input validation.

## Local-State Migration Decision

The workflow will refuse remote initialization when it detects:

```text
terraform.tfstate
terraform.tfstate.backup
terraform.tfstate.d/
```

The workflow will not execute automatic migration.

State migration requires separate review and explicit operator action.

## Artifact Guard Decision

Plan and apply will require a valid deterministic Lambda package and checksum.

The infrastructure workflow will verify the artifact.

It will not build it.

## Offline Validation Decision

The workflow will expose:

```text
offline-check
```

It will initialize both Terraform roots with:

```text
-backend=false
-lockfile=readonly
-input=false
```

Then run formatting, validation, and tests.

Automated tests will remain independent from:

```text
AWS credentials
AWS CLI
S3
real Terraform state
real Terraform plan
real Terraform apply
```

## Destroy Decision

The workflow will not expose a destroy command.

Destructive application changes remain possible only through normal reviewed Terraform planning when configuration intentionally removes resources.

State-bucket destruction requires explicit bootstrap code changes and independent review.

## Force-Unlock Decision

The workflow will not automate `terraform force-unlock`.

A stale lock requires operator investigation and the exact lock ID.

## Consequences

### Positive

- State storage is durable and account-scoped.
- State objects are isolated by environment.
- Each environment receives an independent lockfile.
- The project avoids deprecated DynamoDB locking.
- Versioning supports state recovery.
- State-bucket deletion is difficult to perform accidentally.
- Bucket configuration remains separate from application resources.
- Backend files contain no credentials.
- Environment selection is explicit.
- Terraform workspace drift is avoided.
- Backend metadata is isolated by environment.
- A wrong AWS account is rejected.
- A wrong state bucket is rejected.
- Local state is not migrated silently.
- Lambda artifacts are verified before planning.
- Apply uses only a reviewed saved plan.
- Plan tampering is detected locally.
- Automated tests remain offline.
- The workflow can later be called from CI with a temporary AWS identity.
- The design is explainable and auditable in code review.

### Negative

- The bootstrap root retains local state.
- Bootstrap state needs a separate secure backup procedure.
- Real operation requires two Terraform roots.
- Operators must manage two non-secret runtime values.
- Environment files require deliberate maintenance.
- The custom Python workflow adds code and tests.
- The plan manifest is not a signed artifact.
- Saved plans are local and should not be assumed portable.
- The initial workflow does not publish plans to pull requests.
- The initial workflow does not create AWS identities.
- The initial workflow does not notify on drift.
- State-bucket version retention creates S3 storage cost.
- The initial state bucket is not replicated across Regions.
- Recovery still requires operator judgment.
- Real deployment behavior remains unvalidated until AWS bootstrap occurs.

## Alternatives Considered

### Continue Using Local Application State

Rejected.

Local state does not provide a durable shared deployment boundary.

It creates higher risk of state loss, conflicting operators, and machine-specific ownership.

### One State Bucket per Environment

Not selected for the current account model.

Independent keys provide sufficient environment isolation inside one account while reducing repeated bucket policy and lifecycle configuration.

Separate buckets may be adopted if environments move to separate accounts or compliance boundaries require it.

### One State Bucket Across Multiple AWS Accounts

Deferred.

A centralized state account requires cross-account IAM, trust policy, and platform ownership decisions.

The current design creates one bucket per account.

### DynamoDB State Locking

Rejected.

S3-native lockfiles satisfy the current locking requirement without a separate DynamoDB table.

### Terraform Workspaces

Rejected for environment selection.

Workspaces add implicit operator context and make state identity less visible in committed files and commands.

### Separate Terraform Root per Environment

Rejected for now.

Three duplicated roots would increase drift and review cost.

One shared root plus explicit environment files preserves common infrastructure definitions.

### Hard-Code the State Bucket in Backend Files

Rejected.

The bucket is account-specific.

Committing it would make the repository less reusable and would mix execution ownership with shared configuration.

### Commit Expected AWS Account IDs

Rejected.

Account ownership is an execution concern and may differ by installation.

The value is supplied deliberately during authenticated operation.

### Store AWS Profiles in Backend Files

Rejected.

Profiles are operator-machine configuration and should not be committed as shared infrastructure behavior.

### Pass Credentials Through Backend Configuration

Rejected.

Backend configuration may be retained under Terraform metadata and plan artifacts.

Credentials remain external.

### Use HCP Terraform

Deferred.

HCP Terraform provides managed state, locking, runs, policy, and access controls, but introduces a SaaS platform and organization workflow beyond the current project requirement.

### Use Terraform Cloud Workspaces for Environments

Deferred with HCP Terraform.

The current project uses explicit open-source Terraform execution.

### Customer-Managed KMS Key

Deferred.

SSE-S3 provides encryption at rest without a separate KMS key lifecycle, policy, and request cost.

A customer-managed key may be introduced when a concrete compliance or cross-account requirement exists.

### S3 Object Lock

Deferred.

Object Lock introduces retention governance and recovery constraints that require explicit operational ownership.

### Cross-Region Replication

Deferred.

The current state design first establishes versioned durable storage.

Replication requires a second bucket, replication role, recovery procedure, and cost model.

### Automatic State Migration

Rejected.

Unknown local state must never be migrated by a convenience script.

### Automatic Force Unlock

Rejected.

Force-unlocking an active state can create multiple writers.

### Direct Terraform Apply

Rejected.

The workflow requires an explicit saved plan to preserve review/apply separation.

### Apply With Auto-Approve

Rejected.

Saved plans already encode reviewed changes.

The workflow should not add another approval bypass.

### Only a Shell Script

Not selected.

Python provides:

```text
portable argument parsing
strict file validation
testable command construction
manifest serialization
hash verification
clear error handling
```

without adding a third-party dependency.

### No Plan Manifest

Rejected.

A plan file alone does not make environment, account, bucket, and state-key binding visible to the workflow.

### Signed Plan Artifacts

Deferred.

Cryptographic signing requires identity, key management, artifact publication, and CI ownership.

### Build Lambda During Plan

Rejected.

Artifact production and infrastructure planning remain separate responsibilities.

## Follow-Up Decisions

Future work must define:

```text
real AWS authentication method
state bootstrap execution
bootstrap local-state backup
state access IAM
GitHub OIDC trust
CI plan identity
deployment identity
pull-request plan publication
environment approval
production deployment authorization
artifact publication
plan artifact signing
state audit logging
CloudTrail data events
replication
disaster recovery
scheduled drift detection
state migration if authoritative local state appears
destroy and teardown runbooks
stale-lock recovery procedure
```

## Validation Requirements

Before review:

```text
Python formatting and linting
Python unit tests
application Terraform offline checks
bootstrap Terraform offline checks
provider lock-file consistency
Git ignore validation
no committed state
no committed plan
no committed credentials
```

Before real AWS bootstrap:

```text
approved authentication
verified target account
reviewed bootstrap plan
confirmed bucket name
confirmed Region
confirmed versioning and protection
secure bootstrap-state backup location
explicit approval
```

Before first real application apply:

```text
state bucket exists
versioning is active
runtime bucket input is correct
expected account is correct
Lambda artifact is verified
dev backend initialization succeeds
saved plan is reviewed
plan manifest is intact
environment confirmation matches
explicit approval is recorded
```