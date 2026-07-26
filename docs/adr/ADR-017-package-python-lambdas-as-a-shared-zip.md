# ADR-017: Package Python Lambdas as a Shared Deterministic ZIP

## Status

Accepted

## Context

CloudDoc contains multiple Python modules intended to serve as AWS Lambda handlers.

The handlers share:

```text
one application package
one Python runtime
one runtime dependency graph
one repository release cadence
```

The project needs a deployment artifact that is:

```text
compatible with AWS Lambda Python 3.12
compatible with Linux x86_64
fully dependency-locked
hash verified
structurally validated
reproducible from equivalent inputs
testable without AWS
excluded from Git history
```

Terraform should not yet depend on the artifact because Lambda resources are not part of this slice.

Development may occur on Windows while the deployed runtime is Linux.

## Decision

CloudDoc will package the Python application and runtime dependencies into one shared deterministic ZIP artifact.

The artifact path is:

```text
artifacts/lambda/clouddoc-app.zip
```

The checksum path is:

```text
artifacts/lambda/clouddoc-app.sha256
```

The artifact is generated and ignored by Git.

Different Lambda functions will use the same ZIP with different handler strings.

## Runtime Decision

The first package target is:

```text
Python 3.12
CPython
cp312 ABI
Linux manylinux2014
x86_64
```

The builder will reject execution under a different Python minor version.

Runtime dependency installation will require binary wheels compatible with the selected Linux platform and architecture.

## Shared Artifact Decision

One shared application artifact will contain all public CloudDoc handler modules.

This is appropriate because the initial functions share:

```text
application source
dependency graph
runtime
deployment cadence
```

This avoids multiple equivalent ZIP files and duplicated build logic.

Function-specific packages may be introduced when there is evidence of:

```text
material package-size differences
different native dependencies
different release cadence
cold-start pressure
separate ownership boundaries
```

## Dependency Input Decision

Direct runtime dependencies will be declared in:

```text
requirements/lambda.in
```

This file will mirror the production dependency intent declared in `pyproject.toml`.

Development-only dependencies will remain outside the Lambda runtime input.

## Dependency Lock Decision

The complete runtime graph will be committed in:

```text
requirements/lambda.lock.txt
```

The lock will contain:

```text
exact versions
transitive dependencies
SHA-256 hashes
```

`pip-tools` will generate the lock and remain a development-only dependency.

The package build will install with hash verification.

## Boto3 Decision

Boto3 will be included explicitly in the deployment artifact.

CloudDoc will not depend solely on the SDK version supplied by the Lambda runtime.

This creates one controlled runtime dependency graph and avoids mixing a project-packaged dependency with a potentially different runtime SDK release.

## Builder Ownership Decision

Packaging behavior will be owned by:

```text
scripts/build_lambda_package.py
```

The Makefile will delegate to that script.

The builder will own:

```text
runtime validation
lock validation
handler discovery
handler import validation
staging cleanup
dependency installation
application copy
transient cleanup
package validation
deterministic archive generation
checksum generation
```

Packaging logic will not be duplicated across Make, Terraform, CI, or shell scripts.

## Handler Discovery Decision

The builder will dynamically discover public Python modules under:

```text
src/clouddoc/handlers/
```

A public handler module must expose a callable:

```python
lambda_handler
```

Files beginning with an underscore are treated as private implementation modules.

This prevents a second hard-coded handler inventory from drifting away from the source tree.

## Archive Layout Decision

The ZIP root will contain:

```text
clouddoc/
runtime dependency packages
runtime dependency modules
```

The ZIP will not contain:

```text
src/
tests/
docs/
infra/
repository metadata
development caches
```

The `src/clouddoc` package will be copied to `clouddoc` at staging root.

## Determinism Decision

The builder will normalize:

```text
archive entry order
timestamps
file permissions
compression settings
```

Equivalent package contents will produce the same archive bytes and SHA-256 digest.

The deterministic-build claim is scoped to equivalent:

```text
source files
dependency lock
target runtime
dependency distributions
builder version
```

It is not a claim that arbitrary environments with different inputs will produce an identical artifact.

## Artifact Integrity Decision

The builder will generate a SHA-256 checksum file.

A separate Make target will independently recalculate the ZIP digest and compare it with the generated checksum.

The checksum provides integrity verification.

It does not provide signer identity, deployment authorization, or supply-chain provenance.

## Build Output Decision

Generated package state will live under:

```text
.lambda-build/
artifacts/lambda/
```

These paths will not be committed.

The source repository will version only the inputs and implementation required to recreate the artifact.

## Local Import Validation Decision

The builder will import discovered handlers from the local source environment and require a callable `lambda_handler`.

It will not import the completed Linux dependency tree directly on a Windows host.

A later Linux CI or container stage may validate imports directly from the completed artifact.

## Test Decision

Builder tests will use:

```text
pytest
temporary directories
local dependency fixtures
monkeypatched dependency installation
```

The tests will not require:

```text
network access
AWS credentials
Docker
real package installation
real AWS resources
```

The test suite will exercise all packaging stages except the external dependency download.

## Make Command Decision

The repository will expose:

```text
make lambda-lock
make lambda-package
make lambda-package-check
make lambda-clean
```

`make check` will remain the application quality path and will not automatically build the deployment package.

The package build may require package-registry access for locked Linux wheels and therefore remains an explicit command.

## Terraform Independence Decision

Terraform will not reference the generated ZIP in this slice.

This preserves:

```text
terraform validate
terraform test
```

as operations that do not require a local artifact build.

Artifact integration belongs to the future Lambda provisioning slice.

## Consequences

### Positive

- Runtime dependencies are exactly pinned.
- Dependency distributions are hash verified.
- Linux x86_64 compatibility is explicit.
- Host operating-system dependencies are not copied accidentally.
- Boto3 is controlled by the project.
- All current handlers share one artifact.
- The application package is placed at the correct ZIP root.
- Stale staging content is removed.
- Cache and development files are excluded.
- Archive metadata is normalized.
- Equivalent builds produce stable SHA-256 values.
- Builder logic is unit tested without network access.
- No AWS credentials are required.
- Generated binaries remain outside Git history.
- Terraform remains independent from local build state.

### Negative

- The package includes code unused by some individual functions.
- Any shared-package change produces a new artifact for all functions.
- Versioning Boto3 increases artifact size.
- A real package build may require package-registry access.
- Local source imports do not prove completed-artifact imports on Linux.
- The generated checksum is not a signing mechanism.
- x86_64 is fixed until another artifact target is introduced.
- Dependency lock updates require an explicit regeneration workflow.

## Alternatives Considered

### Create One ZIP per Handler

Deferred.

The initial handlers share one package and dependency graph.

Separate artifacts would duplicate content and build logic without a demonstrated operational benefit.

### Use Lambda Layers

Deferred.

Layers introduce a second artifact lifecycle, independent versioning, function-to-layer associations, and additional deployment coordination.

They become useful when dependency reuse, package-size pressure, or independent release cadence justifies the boundary.

### Use Container Images

Deferred.

The current runtime does not require OS packages, custom runtime control, or image-sized dependencies.

ZIP packaging is the simpler deployment model for the initial serverless workload.

### Rely on Lambda-Provided Boto3

Rejected.

The project needs one controlled SDK dependency graph and should avoid version misalignment with packaged transitive dependencies.

### Install Dependencies for the Host Platform

Rejected.

Development hosts may not match the Lambda Linux runtime or instruction-set architecture.

### Commit the ZIP Artifact

Rejected.

Generated binary artifacts create repository bloat and opaque history.

The artifact must be reproducible from versioned inputs.

### Use Unpinned Runtime Ranges During Build

Rejected.

Ordinary builds could resolve different transitive versions over time.

### Omit Distribution Hashes

Rejected.

Exact versions alone do not verify the selected package distributions.

### Put Packaging Logic in the Makefile

Rejected.

Complex packaging behavior belongs in testable Python code.

The Makefile should expose commands, not own application logic.

### Make Terraform Build the Artifact

Deferred.

Terraform should consume infrastructure inputs rather than hide a local software-build process inside resource evaluation.

The artifact will be built before future Terraform deployment commands.

### Build Only in CI

Deferred.

A local reproducible path is valuable for engineering review and troubleshooting.

CI artifact publication will be introduced after the local contract is stable.

### Target arm64 Immediately

Deferred.

x86_64 reduces initial compatibility variables.

arm64 can be evaluated later with measured package compatibility, cost, and runtime behavior.

### Claim Full Reproducibility Across Arbitrary Machines

Rejected.

The reproducibility guarantee is bounded by explicit build inputs and the selected dependency distributions.

## Follow-Up Decisions

Future work must define:

```text
how Terraform consumes the artifact
whether the artifact is local or uploaded to S3
Lambda handler strings
function-specific runtime configuration
execution roles
least-privilege IAM
environment variables
timeouts and memory
SQS event-source mappings
partial batch failures
CloudWatch log retention
Linux artifact smoke testing in CI
artifact publication
code signing
arm64 evaluation
```