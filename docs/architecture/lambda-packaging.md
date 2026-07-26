# Lambda Packaging Architecture

## Status

Implemented as a repository-owned packaging foundation.

This document defines how CloudDoc AI Pipeline produces a reproducible AWS Lambda ZIP artifact from the existing Python application without provisioning or deploying Lambda functions.

## Purpose

CloudDoc already contains multiple Lambda-compatible handlers under:

```text
src/clouddoc/handlers/
```

The packaging boundary converts the application source and its locked runtime dependencies into one shared deployment artifact:

```text
artifacts/lambda/clouddoc-app.zip
```

The artifact is generated locally and is intentionally excluded from Git.

This slice establishes artifact construction, validation, and cleanup. Lambda resources, IAM roles, event-source mappings, environment variables, and deployment automation remain separate infrastructure responsibilities.

## Packaging Flow

```text
pyproject.toml
requirements/lambda.in
requirements/lambda.lock.txt
src/clouddoc/
        │
        ▼
scripts/build_lambda_package.py
        │
        ├── validates Python 3.12
        ├── validates the runtime lock
        ├── discovers handler modules
        ├── validates callable entrypoints
        ├── clears stale build outputs
        ├── installs Linux x86_64 wheels
        ├── copies the application package
        ├── removes transient files
        ├── validates staging layout
        ├── writes a deterministic ZIP
        └── writes a SHA-256 checksum
        │
        ▼
.lambda-build/clouddoc-app/
artifacts/lambda/clouddoc-app.zip
artifacts/lambda/clouddoc-app.sha256
```

## Shared Artifact Decision

The first Lambda deployment stage uses one shared application ZIP.

Different Lambda functions will use the same artifact with different handler strings.

Conceptually:

```text
shared artifact
├── create-job handler
├── get-job handler
├── process-uploaded-document handler
└── dead-letter reconciliation handler
```

This avoids duplicating the dependency graph and packaging implementation while the functions still share one application package.

Function-specific artifacts remain available as a future optimization when runtime dependencies, release cadence, package size, or cold-start characteristics materially diverge.

## Runtime Contract

The package targets:

```text
Python runtime: 3.12
Instruction-set architecture: x86_64
Python implementation: CPython
Python ABI: cp312
Wheel platform: manylinux2014_x86_64
```

The builder requires binary wheels compatible with that runtime contract.

Host-native dependency installation is not used for the deployment staging directory.

This matters because development may occur on Windows or macOS while Lambda executes on Linux.

## Dependency Boundaries

### Direct Runtime Input

The direct dependency intent is stored in:

```text
requirements/lambda.in
```

It contains only runtime dependencies required by the deployed application.

Development tools do not belong in this file.

### Fully Resolved Runtime Lock

The resolved dependency graph is stored in:

```text
requirements/lambda.lock.txt
```

The lock contains:

```text
exact package versions
transitive dependencies
SHA-256 distribution hashes
```

The build installs from the lock using hash verification.

This prevents an ordinary packaging run from silently resolving a different transitive dependency graph.

### Project Metadata

`pyproject.toml` remains the authoritative package and development configuration.

The direct Lambda requirements intentionally mirror the production dependency ranges declared by the project.

`pip-tools` is a development-only dependency used to regenerate the committed runtime lock.

## Explicit Boto3 Packaging

The artifact includes the project-selected Boto3 dependency rather than relying only on the AWS Lambda runtime copy.

This gives CloudDoc one controlled SDK dependency graph and reduces the risk of mixing a packaged transitive dependency with a different runtime-provided SDK version.

## Archive Layout

The package must expose the application and dependencies at the ZIP root:

```text
clouddoc-app.zip
├── clouddoc/
├── boto3/
├── botocore/
├── pydantic/
├── pydantic_core/
├── s3transfer/
├── typing_extensions.py
└── other locked runtime dependencies
```

The archive must not contain:

```text
src/
tests/
docs/
infra/
.git/
.venv/
__pycache__/
*.pyc
*.pyo
```

The application package is copied from:

```text
src/clouddoc/
```

to:

```text
staging/clouddoc/
```

The `src` directory itself is not included in the archive.

## Handler Discovery

The builder discovers public Python modules under:

```text
src/clouddoc/handlers/
```

A module is treated as a Lambda handler module when:

```text
the file is a Python module
the file is not __init__.py
the module name does not begin with an underscore
```

Each discovered module must expose:

```python
lambda_handler
```

and that attribute must be callable.

The discovery strategy avoids maintaining a duplicated hard-coded handler list in the packaging tool.

A private helper module can remain excluded by using a leading underscore.

## Import Validation Boundary

The builder validates handler imports from the local project environment before assembling the deployment ZIP.

This verifies:

```text
the module can be imported
lambda_handler exists
lambda_handler is callable
```

It does not:

```text
invoke AWS
execute a business workflow
validate Linux-native packaged extensions on a Windows host
prove deployed Lambda startup
```

A later Linux CI or container validation stage may import directly from the completed artifact.

## Staging Ownership

Temporary package content is written under:

```text
.lambda-build/clouddoc-app/
```

Before each build, the builder removes:

```text
the previous staging directory
the previous ZIP artifact
the previous checksum
```

This prevents deleted or renamed source files from remaining in a later package.

The staging directory is generated state and is ignored by Git.

## Transient File Removal

Before archive creation, the builder removes:

```text
__pycache__ directories
.pyc files
.pyo files
console-script directories created by dependency installation
common operating-system metadata files
```

The archive contains source modules and runtime dependencies, not development caches.

## Package Validation

Before creating the ZIP, the builder verifies:

```text
clouddoc/__init__.py exists
boto3/__init__.py exists
pydantic/__init__.py exists
every discovered handler source exists
no forbidden top-level repository path exists
the package contains at least one file
no symbolic link is packaged
no cache bytecode remains
```

A packaging invariant failure raises a dedicated `PackagingError`.

## Deterministic ZIP Construction

The archive writer controls:

```text
entry ordering
entry timestamps
file permissions
compression method
compression level
```

Files are ordered by their POSIX-style archive path.

Each entry uses the normalized timestamp:

```text
1980-01-01 00:00:00
```

Each regular file uses normalized read/write permissions equivalent to:

```text
0644
```

The archive is written to a temporary file and atomically replaced after successful completion.

Equivalent staging contents therefore produce the same archive bytes and SHA-256 digest.

The reproducibility guarantee assumes the same:

```text
application source
runtime lock
target runtime contract
dependency distributions
builder implementation
```

## Artifact Integrity

After archive creation, the builder calculates SHA-256 and writes:

```text
artifacts/lambda/clouddoc-app.sha256
```

The checksum file uses the form:

```text
<sha256>  clouddoc-app.zip
```

`make lambda-package-check` independently recalculates the archive digest and compares it with the checksum file.

A checksum verifies artifact integrity after construction. It is not a code-signing or provenance mechanism.

## Generated Artifact Ownership

The repository versions:

```text
runtime dependency input
runtime dependency lock
package builder
builder tests
Make targets
architecture documentation
decision record
```

The repository does not version:

```text
.lambda-build/
artifacts/lambda/clouddoc-app.zip
artifacts/lambda/clouddoc-app.sha256
installed staging dependencies
```

This keeps generated binary content out of source history.

## Developer Commands

The Makefile provides:

```text
make lambda-lock
make lambda-package
make lambda-package-check
make lambda-clean
```

### `lambda-lock`

Regenerates the hash-verified runtime lock from the direct dependency input.

This is an intentional dependency-update action and may select newer versions allowed by the declared ranges.

### `lambda-package`

Runs the repository-owned package builder.

### `lambda-package-check`

Builds the artifact and independently verifies its checksum.

### `lambda-clean`

Removes only generated Lambda staging and artifact directories.

The repository-wide `clean` target depends on `lambda-clean` and preserves its pre-existing cleanup behavior.

## Test Strategy

Builder tests live under:

```text
tests/tooling/test_lambda_package_builder.py
```

The tests require no:

```text
AWS credentials
network access
Docker daemon
real dependency installation
Terraform execution
```

They use temporary directories and local dependency fixtures.

The tests cover:

```text
runtime-lock validation
missing hashes
non-exact pins
missing direct dependencies
handler discovery
private-module exclusion
callable entrypoint validation
stale-output cleanup
transient-file cleanup
stable file ordering
forbidden top-level paths
normalized ZIP metadata
stable SHA-256
root-level application layout
offline end-to-end package creation
```

The dependency-installation function is replaced only inside the offline unit test.

The remaining packaging pipeline is exercised directly.

## Security Boundary

The packaging workflow is designed to avoid:

### Credential Coupling

The builder does not call AWS APIs and does not require AWS credentials.

### Secret Inclusion

The builder copies only:

```text
locked runtime dependencies
src/clouddoc
```

It does not copy `.env`, Terraform state, AWS profiles, documents, or repository metadata.

### Unverified Dependencies

The runtime lock contains exact versions and SHA-256 hashes.

The build requires those hashes during installation.

### Cross-Platform Binary Mismatch

The dependency installation explicitly targets Linux x86_64 CPython 3.12 wheels.

### Symlink Inclusion

The staging validator rejects symbolic links.

### Stale Source Inclusion

Previous staging content is deleted before every build.

### Binary Repository Bloat

Generated deployment artifacts remain ignored by Git.

## Failure Modes

### Wrong Python Minor Version

The builder exits before package construction.

### Missing Runtime Lock

The builder exits with a packaging error.

### Lock Without Hashes

The builder rejects the dependency graph.

### Non-Exact Runtime Pin

The builder rejects the lock.

### Linux-Compatible Wheel Unavailable

The dependency installation fails.

### Handler Import Failure

The builder fails before producing an artifact.

### Missing Callable Entrypoint

The builder rejects the handler module.

### Incorrect ZIP Root

The staging validator rejects forbidden repository roots and requires `clouddoc` at the root.

### Stale Staging Content

The previous staging directory is removed before installation and copy operations.

### Empty Package

The builder rejects the staging directory.

### Cache Files Included

Transient cleanup removes caches, and package validation rejects remaining bytecode.

### Checksum Mismatch

`make lambda-package-check` exits unsuccessfully.

### Generated Artifact Missing During Terraform Plan

Terraform does not reference the artifact in this slice, so Terraform validation remains independent from packaging.

## Cost and Operational Posture

Packaging itself creates no AWS resources and incurs no AWS runtime cost.

Operational complexity is kept bounded through:

```text
one shared artifact
one dependency graph
one builder
one checksum
no layer versioning
no image registry
no deployment automation
```

## Intentionally Deferred

The packaging foundation does not introduce:

```text
aws_lambda_function resources
execution roles or IAM policies
API Gateway integrations
SQS event-source mappings
ReportBatchItemFailures configuration
runtime environment variables
CloudWatch log groups
memory or timeout configuration
reserved concurrency
artifact upload to S3
CI artifact publishing
automatic deployment
Lambda code signing
Lambda layers
container-image packaging
arm64 artifacts
provisioned concurrency
real Lambda invocation
```

These are intentionally sequenced after artifact construction is stable.

## Follow-Up Work

The next infrastructure stage should provision Lambda execution boundaries around the shared artifact.

That work must define:

```text
function ownership
handler strings
runtime and architecture
artifact integration
separate execution roles
least-privilege policies
environment variables
timeouts and memory
event-source mappings
partial batch failure behavior
CloudWatch log retention
deployment validation
```