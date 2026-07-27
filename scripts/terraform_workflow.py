"""Guarded Terraform workflow for CloudDoc environments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

SUPPORTED_ENVIRONMENTS: Final = ("dev", "staging", "prod")
STATE_BUCKET_ENV: Final = "CLOUDDOC_TERRAFORM_STATE_BUCKET"
EXPECTED_ACCOUNT_ENV: Final = "CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID"
TERRAFORM_BINARY_ENV: Final = "CLOUDDOC_TERRAFORM_BINARY"
LOCK_TIMEOUT: Final = "5m"
PLAN_FILENAME: Final = "clouddoc.tfplan"
MANIFEST_FILENAME: Final = "clouddoc.tfplan.json"

ACCOUNT_ID_PATTERN: Final = re.compile(r"^[0-9]{12}$")
PROJECT_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
ASSIGNMENT_PATTERN: Final = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+?)\s*$"
)
BUCKET_PATTERN: Final = re.compile(
    r"^(?!xn--)(?!sthree-)(?!amzn_s3_demo_)"
    r"(?!.*-s3alias$)(?!.*--ol-s3$)"
    r"(?!.*\.\.)(?!.*\.-)(?!.*-\.)"
    r"[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])$"
)


class WorkflowError(RuntimeError):
    """Raised when a guarded Terraform invariant is violated."""


@dataclass(frozen=True, slots=True)
class WorkflowPaths:
    """Repository paths used by the workflow."""

    repository_root: Path
    terraform_root: Path
    bootstrap_root: Path
    environments_root: Path
    terraform_artifacts_root: Path
    lambda_artifact: Path
    lambda_checksum: Path

    @classmethod
    def from_script(cls, script_path: Path) -> WorkflowPaths:
        """Resolve repository paths from this script."""
        repository_root = script_path.resolve().parents[1]
        terraform_root = repository_root / "infra" / "terraform"

        return cls(
            repository_root=repository_root,
            terraform_root=terraform_root,
            bootstrap_root=(
                repository_root / "infra" / "bootstrap" / "terraform-state"
            ),
            environments_root=terraform_root / "environments",
            terraform_artifacts_root=(repository_root / "artifacts" / "terraform"),
            lambda_artifact=(
                repository_root / "artifacts" / "lambda" / "clouddoc-app.zip"
            ),
            lambda_checksum=(
                repository_root / "artifacts" / "lambda" / "clouddoc-app.sha256"
            ),
        )

    def tfvars_file(self, environment: str) -> Path:
        """Return one environment variable file."""
        return self.environments_root / f"{environment}.tfvars"

    def backend_file(self, environment: str) -> Path:
        """Return one environment backend configuration file."""
        return self.environments_root / f"{environment}.s3.tfbackend"

    def data_dir(self, environment: str) -> Path:
        """Return isolated Terraform metadata storage."""
        return self.terraform_root / ".terraform-data" / environment

    def plan_dir(self, environment: str) -> Path:
        """Return the ignored plan directory."""
        return self.terraform_artifacts_root / environment

    def plan_file(self, environment: str) -> Path:
        """Return the saved Terraform plan path."""
        return self.plan_dir(environment) / PLAN_FILENAME

    def manifest_file(self, environment: str) -> Path:
        """Return the saved-plan manifest path."""
        return self.plan_dir(environment) / MANIFEST_FILENAME


@dataclass(frozen=True, slots=True)
class EnvironmentConfig:
    """Validated committed configuration for one environment."""

    environment: str
    project_name: str
    aws_region: str
    state_key: str
    tfvars_file: Path
    backend_file: Path

    @classmethod
    def load(
        cls,
        paths: WorkflowPaths,
        environment: str,
    ) -> EnvironmentConfig:
        """Load and validate the selected environment files."""
        validate_environment(environment)

        tfvars_file = paths.tfvars_file(environment)
        backend_file = paths.backend_file(environment)
        tfvars = parse_assignments(tfvars_file)
        backend = parse_assignments(backend_file)

        require_exact_fields(
            tfvars_file,
            tfvars,
            {"aws_region", "project_name", "environment"},
        )
        require_exact_fields(
            backend_file,
            backend,
            {"key", "region", "encrypt", "use_lockfile"},
        )

        configured_environment = require_string(
            tfvars_file,
            "environment",
            tfvars["environment"],
        )
        if configured_environment != environment:
            raise WorkflowError(
                f"Environment mismatch: selected {environment!r}, "
                f"but {tfvars_file} declares {configured_environment!r}."
            )

        project_name = require_string(
            tfvars_file,
            "project_name",
            tfvars["project_name"],
        )
        if not (
            3 <= len(project_name) <= 32 and PROJECT_PATTERN.fullmatch(project_name)
        ):
            raise WorkflowError(
                f"{tfvars_file} contains invalid project_name {project_name!r}."
            )

        aws_region = require_string(
            tfvars_file,
            "aws_region",
            tfvars["aws_region"],
        )
        backend_region = require_string(
            backend_file,
            "region",
            backend["region"],
        )
        if backend_region != aws_region:
            raise WorkflowError(
                f"Region mismatch between {tfvars_file} and {backend_file}."
            )

        state_key = require_string(
            backend_file,
            "key",
            backend["key"],
        )
        expected_key = f"{project_name}/{environment}/terraform.tfstate"
        if state_key != expected_key:
            raise WorkflowError(
                f"{backend_file} must use state key {expected_key!r}; "
                f"found {state_key!r}."
            )

        if (
            require_bool(
                backend_file,
                "encrypt",
                backend["encrypt"],
            )
            is not True
        ):
            raise WorkflowError(f"{backend_file} must set encrypt = true.")

        if (
            require_bool(
                backend_file,
                "use_lockfile",
                backend["use_lockfile"],
            )
            is not True
        ):
            raise WorkflowError(f"{backend_file} must set use_lockfile = true.")

        return cls(
            environment=environment,
            project_name=project_name,
            aws_region=aws_region,
            state_key=state_key,
            tfvars_file=tfvars_file,
            backend_file=backend_file,
        )


@dataclass(frozen=True, slots=True)
class RemoteInputs:
    """Validated non-secret inputs for authenticated operations."""

    state_bucket: str
    expected_account_id: str

    @classmethod
    def load(cls, environ: Mapping[str, str]) -> RemoteInputs:
        """Load runtime inputs from environment variables."""
        bucket = environ.get(STATE_BUCKET_ENV, "").strip()
        account_id = environ.get(EXPECTED_ACCOUNT_ENV, "").strip()

        missing = [
            name
            for name, value in (
                (STATE_BUCKET_ENV, bucket),
                (EXPECTED_ACCOUNT_ENV, account_id),
            )
            if not value
        ]
        if missing:
            raise WorkflowError(
                "Missing required environment variable(s): " + ", ".join(missing) + "."
            )

        validate_bucket(bucket)
        if ACCOUNT_ID_PATTERN.fullmatch(account_id) is None:
            raise WorkflowError(
                f"{EXPECTED_ACCOUNT_ENV} must contain exactly 12 digits."
            )

        return cls(
            state_bucket=bucket,
            expected_account_id=account_id,
        )


@dataclass(frozen=True, slots=True)
class PlanManifest:
    """Integrity and execution binding for one saved plan."""

    environment: str
    project_name: str
    aws_region: str
    state_bucket: str
    state_key: str
    expected_account_id: str
    terraform_data_dir: str
    tfvars_file: str
    backend_file: str
    plan_file: str
    plan_sha256: str
    terraform_exit_code: int

    def write(self, path: Path) -> None:
        """Write the manifest atomically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")

        try:
            temporary.write_text(
                json.dumps(
                    asdict(self),
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(temporary, path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise WorkflowError(f"Could not write plan manifest: {path}") from error

    @classmethod
    def read(cls, path: Path) -> PlanManifest:
        """Read and strictly validate a manifest."""
        if not path.is_file():
            raise WorkflowError(f"Plan manifest not found: {path}")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise WorkflowError(f"Could not read plan manifest: {path}") from error

        if not isinstance(payload, dict):
            raise WorkflowError(f"Plan manifest must contain a JSON object: {path}")

        expected_fields = set(cls.__dataclass_fields__)
        if set(payload) != expected_fields:
            raise WorkflowError(f"Plan manifest has an unexpected schema: {path}")

        for field in expected_fields - {"terraform_exit_code"}:
            if not isinstance(payload[field], str) or not payload[field]:
                raise WorkflowError(f"Plan manifest field {field!r} is invalid.")

        exit_code = payload["terraform_exit_code"]
        if (
            isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
            or exit_code not in {0, 2}
        ):
            raise WorkflowError(
                "Plan manifest contains an invalid Terraform exit code."
            )

        return cls(**payload)


def validate_environment(environment: str) -> None:
    """Require one supported environment."""
    if environment not in SUPPORTED_ENVIRONMENTS:
        raise WorkflowError(
            f"Unsupported environment {environment!r}; expected one of: "
            + ", ".join(SUPPORTED_ENVIRONMENTS)
            + "."
        )


def parse_assignments(path: Path) -> dict[str, object]:
    """Parse the scalar-only committed HCL assignment files."""
    if not path.is_file():
        raise WorkflowError(f"Configuration file not found: {path}")

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise WorkflowError(f"Could not read configuration file: {path}") from error

    values: dict[str, object] = {}

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.split("#", maxsplit=1)[0].strip()
        if not line:
            continue

        match = ASSIGNMENT_PATTERN.fullmatch(line)
        if match is None:
            raise WorkflowError(f"Unsupported syntax in {path} at line {line_number}.")

        key = match.group("key")
        if key in values:
            raise WorkflowError(f"Duplicate field {key!r} in {path}.")

        values[key] = parse_scalar(
            match.group("value").strip(),
            path=path,
            line_number=line_number,
        )

    return values


def parse_scalar(
    raw_value: str,
    *,
    path: Path,
    line_number: int,
) -> object:
    """Parse one quoted string or boolean."""
    if raw_value == "true":
        return True
    if raw_value == "false":
        return False

    if raw_value.startswith('"') and raw_value.endswith('"'):
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise WorkflowError(
                f"Invalid string in {path} at line {line_number}."
            ) from error

        if isinstance(value, str):
            return value

    raise WorkflowError(
        f"Only quoted strings and booleans are supported in {path} "
        f"at line {line_number}."
    )


def require_exact_fields(
    path: Path,
    values: Mapping[str, object],
    expected: set[str],
) -> None:
    """Require one exact committed-file schema."""
    missing = expected.difference(values)
    unexpected = set(values).difference(expected)

    if not missing and not unexpected:
        return

    details: list[str] = []
    if missing:
        details.append("missing: " + ", ".join(sorted(missing)))
    if unexpected:
        details.append("unexpected: " + ", ".join(sorted(unexpected)))

    raise WorkflowError(
        f"Invalid field contract for {path}: " + "; ".join(details) + "."
    )


def require_string(
    path: Path,
    field: str,
    value: object,
) -> str:
    """Require a nonempty string."""
    if not isinstance(value, str) or not value:
        raise WorkflowError(f"{path} field {field!r} must be a nonempty string.")
    return value


def require_bool(
    path: Path,
    field: str,
    value: object,
) -> bool:
    """Require a boolean."""
    if not isinstance(value, bool):
        raise WorkflowError(f"{path} field {field!r} must be a boolean.")
    return value


def validate_bucket(bucket: str) -> None:
    """Validate a general-purpose S3 bucket name without AWS access."""
    if not 3 <= len(bucket) <= 63:
        raise WorkflowError(f"{STATE_BUCKET_ENV} must contain 3 through 63 characters.")
    if BUCKET_PATTERN.fullmatch(bucket) is None:
        raise WorkflowError(f"{STATE_BUCKET_ENV} is not a valid S3 bucket name.")
    if re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}", bucket):
        raise WorkflowError(f"{STATE_BUCKET_ENV} must not use an IP-address format.")


def sha256_file(path: Path) -> str:
    """Calculate a file SHA-256 digest."""
    digest = hashlib.sha256()

    try:
        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)
    except OSError as error:
        raise WorkflowError(f"Could not hash file: {path}") from error

    return digest.hexdigest()


def verify_lambda_artifact(paths: WorkflowPaths) -> None:
    """Require the built Lambda package and matching checksum."""
    if not paths.lambda_artifact.is_file():
        raise WorkflowError(
            "Lambda artifact not found. Run `make lambda-package-check`."
        )
    if not paths.lambda_checksum.is_file():
        raise WorkflowError(
            "Lambda checksum not found. Run `make lambda-package-check`."
        )

    try:
        tokens = paths.lambda_checksum.read_text(encoding="utf-8").split()
    except OSError as error:
        raise WorkflowError(
            f"Could not read checksum file: {paths.lambda_checksum}"
        ) from error

    if len(tokens) < 2:
        raise WorkflowError("Lambda checksum file is malformed.")

    expected_digest, expected_filename = tokens[:2]
    if expected_filename != paths.lambda_artifact.name:
        raise WorkflowError("Lambda checksum references an unexpected artifact.")
    if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
        raise WorkflowError("Lambda checksum contains an invalid digest.")
    if sha256_file(paths.lambda_artifact) != expected_digest:
        raise WorkflowError(
            "Lambda artifact checksum mismatch. Run `make lambda-package-check`."
        )


def require_no_local_state(paths: WorkflowPaths) -> None:
    """Block automatic migration of unknown local application state."""
    candidates = [
        paths.terraform_root / "terraform.tfstate",
        paths.terraform_root / "terraform.tfstate.backup",
    ]
    detected: list[Path] = []

    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_size > 0:
                detected.append(candidate)
        except OSError as error:
            raise WorkflowError(
                f"Could not inspect local state: {candidate}"
            ) from error

    workspace_state = paths.terraform_root / "terraform.tfstate.d"
    if workspace_state.exists():
        detected.append(workspace_state)

    if detected:
        raise WorkflowError(
            "Local application state detected. Automatic migration is "
            "forbidden: " + ", ".join(str(path) for path in detected)
        )


def terraform_binary(environ: Mapping[str, str]) -> str:
    """Resolve the Terraform executable."""
    binary = environ.get(TERRAFORM_BINARY_ENV, "terraform").strip()
    if not binary:
        raise WorkflowError(f"{TERRAFORM_BINARY_ENV} must not be blank.")
    return binary


def run_terraform(
    *,
    binary: str,
    root: Path,
    repository_root: Path,
    data_dir: Path,
    arguments: Sequence[str],
    expected_account_id: str | None = None,
    accepted_codes: frozenset[int] = frozenset({0}),
) -> int:
    """Run Terraform without shell interpolation."""
    data_dir.mkdir(parents=True, exist_ok=True)
    child_environment = os.environ.copy()
    child_environment["TF_DATA_DIR"] = str(data_dir.resolve())
    child_environment["TF_IN_AUTOMATION"] = "1"

    if expected_account_id is None:
        child_environment.pop("TF_VAR_expected_aws_account_id", None)
    else:
        child_environment["TF_VAR_expected_aws_account_id"] = expected_account_id

    command = [binary, f"-chdir={root}", *arguments]

    try:
        completed = subprocess.run(
            command,
            cwd=repository_root,
            env=child_environment,
            check=False,
        )
    except FileNotFoundError as error:
        raise WorkflowError(f"Terraform executable not found: {binary!r}.") from error
    except OSError as error:
        raise WorkflowError(f"Could not execute Terraform: {binary!r}.") from error

    if completed.returncode not in accepted_codes:
        raise WorkflowError(
            f"Terraform {arguments[0]} failed with exit code {completed.returncode}."
        )

    return completed.returncode


def display_path(path: Path, repository_root: Path) -> str:
    """Return a stable repository-relative path when possible."""
    try:
        return path.resolve().relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def mask_account_id(account_id: str) -> str:
    """Mask an account ID in console summaries."""
    return f"********{account_id[-4:]}"


def print_remote_summary(
    *,
    paths: WorkflowPaths,
    config: EnvironmentConfig,
    inputs: RemoteInputs,
) -> None:
    """Print the selected execution boundary."""
    print(f"Environment: {config.environment}")
    print(f"AWS Region: {config.aws_region}")
    print(f"State bucket: {inputs.state_bucket}")
    print(f"State key: {config.state_key}")
    print(f"Expected AWS account: {mask_account_id(inputs.expected_account_id)}")
    print(
        "Terraform data directory: "
        + display_path(
            paths.data_dir(config.environment),
            paths.repository_root,
        )
    )


def initialize_backend(
    *,
    binary: str,
    paths: WorkflowPaths,
    config: EnvironmentConfig,
    inputs: RemoteInputs,
) -> None:
    """Initialize one explicit remote backend."""
    require_no_local_state(paths)

    expected_bucket = (
        f"{config.project_name}-{inputs.expected_account_id}-terraform-state"
    )
    if inputs.state_bucket != expected_bucket:
        raise WorkflowError(
            f"{STATE_BUCKET_ENV} must match the selected project and AWS "
            f"account: expected {expected_bucket!r}; "
            f"found {inputs.state_bucket!r}."
        )

    print_remote_summary(paths=paths, config=config, inputs=inputs)

    run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(config.environment),
        expected_account_id=inputs.expected_account_id,
        arguments=[
            "init",
            "-input=false",
            "-reconfigure",
            "-lockfile=readonly",
            f"-backend-config={config.backend_file}",
            f"-backend-config=bucket={inputs.state_bucket}",
        ],
    )


def build_manifest(
    *,
    paths: WorkflowPaths,
    config: EnvironmentConfig,
    inputs: RemoteInputs,
    exit_code: int,
) -> PlanManifest:
    """Create a manifest for the selected saved plan."""
    plan_file = paths.plan_file(config.environment)

    return PlanManifest(
        environment=config.environment,
        project_name=config.project_name,
        aws_region=config.aws_region,
        state_bucket=inputs.state_bucket,
        state_key=config.state_key,
        expected_account_id=inputs.expected_account_id,
        terraform_data_dir=display_path(
            paths.data_dir(config.environment),
            paths.repository_root,
        ),
        tfvars_file=display_path(
            config.tfvars_file,
            paths.repository_root,
        ),
        backend_file=display_path(
            config.backend_file,
            paths.repository_root,
        ),
        plan_file=display_path(
            plan_file,
            paths.repository_root,
        ),
        plan_sha256=sha256_file(plan_file),
        terraform_exit_code=exit_code,
    )


def validate_plan_binding(
    *,
    paths: WorkflowPaths,
    config: EnvironmentConfig,
    inputs: RemoteInputs,
) -> None:
    """Require an intact plan bound to the selected environment and account."""
    plan_file = paths.plan_file(config.environment)
    if not plan_file.is_file():
        raise WorkflowError(f"Saved plan not found: {plan_file}")

    manifest = PlanManifest.read(paths.manifest_file(config.environment))
    expected = {
        "environment": config.environment,
        "project_name": config.project_name,
        "aws_region": config.aws_region,
        "state_bucket": inputs.state_bucket,
        "state_key": config.state_key,
        "expected_account_id": inputs.expected_account_id,
        "terraform_data_dir": display_path(
            paths.data_dir(config.environment),
            paths.repository_root,
        ),
        "tfvars_file": display_path(
            config.tfvars_file,
            paths.repository_root,
        ),
        "backend_file": display_path(
            config.backend_file,
            paths.repository_root,
        ),
        "plan_file": display_path(
            plan_file,
            paths.repository_root,
        ),
    }

    for field, expected_value in expected.items():
        actual_value = getattr(manifest, field)
        if actual_value != expected_value:
            raise WorkflowError(
                f"Plan manifest mismatch for {field}: "
                f"expected {expected_value!r}; found {actual_value!r}."
            )

    if sha256_file(plan_file) != manifest.plan_sha256:
        raise WorkflowError("Saved plan integrity check failed. Create a new plan.")


def command_offline_check(
    *,
    binary: str,
    paths: WorkflowPaths,
) -> None:
    """Validate both Terraform roots without remote state or AWS access."""
    roots = (
        (
            "application",
            paths.terraform_root,
            paths.data_dir("offline"),
        ),
        (
            "bootstrap",
            paths.bootstrap_root,
            paths.bootstrap_root / ".terraform-data" / "offline",
        ),
    )

    for label, root, data_dir in roots:
        print(f"Running {label} Terraform offline checks.")
        for arguments in (
            (
                "init",
                "-backend=false",
                "-lockfile=readonly",
                "-input=false",
            ),
            ("fmt", "-check", "-recursive"),
            ("validate",),
            ("test",),
        ):
            run_terraform(
                binary=binary,
                root=root,
                repository_root=paths.repository_root,
                data_dir=data_dir,
                arguments=arguments,
            )

    print("Terraform offline checks completed successfully.")


def command_init(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
    environ: Mapping[str, str],
) -> None:
    """Initialize one explicit remote backend."""
    config = EnvironmentConfig.load(paths, environment)
    inputs = RemoteInputs.load(environ)
    initialize_backend(
        binary=binary,
        paths=paths,
        config=config,
        inputs=inputs,
    )
    print("Remote backend initialization completed successfully.")


def command_plan(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
    environ: Mapping[str, str],
) -> None:
    """Create one environment-bound saved plan."""
    config = EnvironmentConfig.load(paths, environment)
    inputs = RemoteInputs.load(environ)

    verify_lambda_artifact(paths)
    initialize_backend(
        binary=binary,
        paths=paths,
        config=config,
        inputs=inputs,
    )

    paths.plan_dir(environment).mkdir(parents=True, exist_ok=True)
    plan_file = paths.plan_file(environment)
    manifest_file = paths.manifest_file(environment)
    plan_file.unlink(missing_ok=True)
    manifest_file.unlink(missing_ok=True)

    exit_code = run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        accepted_codes=frozenset({0, 2}),
        arguments=[
            "plan",
            "-input=false",
            f"-lock-timeout={LOCK_TIMEOUT}",
            "-detailed-exitcode",
            f"-var-file={config.tfvars_file}",
            f"-out={plan_file}",
        ],
    )

    if not plan_file.is_file():
        raise WorkflowError(f"Terraform did not create the saved plan: {plan_file}")

    build_manifest(
        paths=paths,
        config=config,
        inputs=inputs,
        exit_code=exit_code,
    ).write(manifest_file)

    outcome = "no changes" if exit_code == 0 else "proposed changes"
    print(f"Terraform plan completed with {outcome}.")
    print("Saved plan: " + display_path(plan_file, paths.repository_root))
    print("Plan manifest: " + display_path(manifest_file, paths.repository_root))


def command_show_plan(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
) -> None:
    """Display one intact saved plan."""
    config = EnvironmentConfig.load(paths, environment)
    plan_file = paths.plan_file(environment)

    if not plan_file.is_file():
        raise WorkflowError(f"Saved plan not found: {plan_file}")

    manifest = PlanManifest.read(paths.manifest_file(environment))
    if manifest.environment != config.environment:
        raise WorkflowError("Plan manifest does not match the selected environment.")
    if sha256_file(plan_file) != manifest.plan_sha256:
        raise WorkflowError("Saved plan integrity check failed.")

    run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        arguments=["show", plan_file.as_posix()],
    )


def command_apply(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
    confirmation: str,
    environ: Mapping[str, str],
) -> None:
    """Apply only an intact saved plan for one environment."""
    validate_environment(confirmation)
    if confirmation != environment:
        raise WorkflowError(
            f"Apply confirmation mismatch: selected {environment!r}, "
            f"confirmed {confirmation!r}."
        )

    config = EnvironmentConfig.load(paths, environment)
    inputs = RemoteInputs.load(environ)

    verify_lambda_artifact(paths)
    validate_plan_binding(paths=paths, config=config, inputs=inputs)
    initialize_backend(
        binary=binary,
        paths=paths,
        config=config,
        inputs=inputs,
    )

    plan_file = paths.plan_file(environment)
    print("Applying reviewed plan: " + display_path(plan_file, paths.repository_root))

    run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        arguments=[
            "apply",
            "-input=false",
            f"-lock-timeout={LOCK_TIMEOUT}",
            plan_file.as_posix(),
        ],
    )
    print("Terraform apply completed successfully.")


def command_output(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
    environ: Mapping[str, str],
    json_output: bool,
) -> None:
    """Read outputs from one explicit remote environment."""
    config = EnvironmentConfig.load(paths, environment)
    inputs = RemoteInputs.load(environ)
    initialize_backend(
        binary=binary,
        paths=paths,
        config=config,
        inputs=inputs,
    )

    arguments = ["output"]
    if json_output:
        arguments.append("-json")

    run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        arguments=arguments,
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Run CloudDoc Terraform with explicit environment, state, "
            "account, and saved-plan boundaries."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "offline-check",
        help="Validate both Terraform roots without remote state.",
    )

    for name, help_text in (
        ("init", "Initialize one environment backend."),
        ("plan", "Create one environment saved plan."),
        ("show-plan", "Display one saved plan."),
        ("output", "Read one environment output set."),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument(
            "--environment",
            required=True,
            choices=SUPPORTED_ENVIRONMENTS,
        )
        if name == "output":
            command.add_argument(
                "--json",
                action="store_true",
                dest="json_output",
            )

    apply_command = subparsers.add_parser(
        "apply",
        help="Apply only an intact environment saved plan.",
    )
    apply_command.add_argument(
        "--environment",
        required=True,
        choices=SUPPORTED_ENVIRONMENTS,
    )
    apply_command.add_argument(
        "--confirm-environment",
        required=True,
        choices=SUPPORTED_ENVIRONMENTS,
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run the guarded workflow."""
    arguments = create_parser().parse_args(argv)
    current_environment = os.environ if environ is None else environ
    paths = WorkflowPaths.from_script(Path(__file__))

    try:
        binary = terraform_binary(current_environment)

        if arguments.command == "offline-check":
            command_offline_check(binary=binary, paths=paths)
        elif arguments.command == "init":
            command_init(
                binary=binary,
                paths=paths,
                environment=arguments.environment,
                environ=current_environment,
            )
        elif arguments.command == "plan":
            command_plan(
                binary=binary,
                paths=paths,
                environment=arguments.environment,
                environ=current_environment,
            )
        elif arguments.command == "show-plan":
            command_show_plan(
                binary=binary,
                paths=paths,
                environment=arguments.environment,
            )
        elif arguments.command == "apply":
            command_apply(
                binary=binary,
                paths=paths,
                environment=arguments.environment,
                confirmation=arguments.confirm_environment,
                environ=current_environment,
            )
        elif arguments.command == "output":
            command_output(
                binary=binary,
                paths=paths,
                environment=arguments.environment,
                environ=current_environment,
                json_output=arguments.json_output,
            )
        else:
            raise WorkflowError(f"Unsupported command: {arguments.command!r}.")
    except WorkflowError as error:
        print(
            f"Terraform workflow failed: {error}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
