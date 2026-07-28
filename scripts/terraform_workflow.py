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
from typing import Final, Literal

_SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

import terraform_plan_attestation as plan_attestation  # noqa: E402
from terraform_plan_attestation import PlanAttestationError  # noqa: E402

SUPPORTED_ENVIRONMENTS: Final = ("dev", "staging", "prod")
STATE_BUCKET_ENV: Final = "CLOUDDOC_TERRAFORM_STATE_BUCKET"
EXPECTED_ACCOUNT_ENV: Final = "CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID"
STATE_ROLE_ENV: Final = "CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN"
PLAN_ROLE_ENV: Final = "CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN"
APPLY_ROLE_ENV: Final = "CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN"
PLAN_ROLE_TF_VAR: Final = "TF_VAR_terraform_plan_role_arn"
APPLY_ROLE_TF_VAR: Final = "TF_VAR_terraform_apply_role_arn"
TERRAFORM_BINARY_ENV: Final = "CLOUDDOC_TERRAFORM_BINARY"
LOCK_TIMEOUT: Final = "5m"
ROLE_SESSION_DURATION: Final = "15m"
STATE_ROLE_SESSION_NAME: Final = "clouddoc-terraform-state"
PLAN_ROLE_SESSION_NAME: Final = "clouddoc-terraform-plan"
STATE_ROLE_NAME: Final = "clouddoc-dev-terraform-state"
PLAN_ROLE_NAME: Final = "clouddoc-dev-terraform-plan"
APPLY_ROLE_NAME: Final = "clouddoc-dev-terraform-apply"
APPLY_ROLE_SESSION_NAME: Final = "clouddoc-terraform-apply"
PLAN_FILENAME: Final = "clouddoc.tfplan"
MANIFEST_FILENAME: Final = "clouddoc.tfplan.json"
DEPLOY_PLAN_FILENAME: Final = "clouddoc-deploy.tfplan"
DEPLOY_PLAN_JSON_FILENAME: Final = "clouddoc-deploy.tfplan.json"
DEPLOY_SHOW_JSON_FILENAME: Final = "terraform-deploy-show.json"
DEPLOY_ATTESTATION_FILENAME: Final = "terraform-deploy-attestation.json"
POST_APPLY_PLAN_FILENAME: Final = "clouddoc-post-apply.tfplan"
FORBIDDEN_LOCAL_APPLY_PLAN_NAMES: Final = frozenset(
    {
        "terraform-plan-attestation.json",
        "terraform-deploy-attestation.json",
        "terraform-show.json",
    }
)
REPOSITORY_PATTERN: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)
PLAN_RUN_ID_PATTERN: Final = re.compile(r"^[1-9][0-9]*$")
COMMIT_SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
BACKEND_OVERRIDE_FILENAME: Final = "backend-override.tfbackend"

OFFLINE_TERRAFORM_ROOTS: Final[tuple[str, ...]] = (
    "infra/terraform",
    "infra/bootstrap/terraform-state",
    "infra/bootstrap/github-oidc",
    "infra/bootstrap/terraform-authorization",
)

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
IAM_ROLE_ARN_PATTERN: Final = re.compile(
    r"^arn:(?P<partition>aws|aws-us-gov|aws-cn):iam::"
    r"(?P<account>[0-9]{12}):role/(?P<name>[A-Za-z0-9+=,.@_/-]+)$"
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
    state_role_arn: str | None
    plan_role_arn: str | None
    apply_role_arn: str | None

    @property
    def uses_chained_roles(self) -> bool:
        """Return whether backend and plan provider role assumption is active."""
        return self.state_role_arn is not None and self.plan_role_arn is not None

    @property
    def uses_chained_deploy_roles(self) -> bool:
        """Return whether backend and apply provider role assumption is active."""
        return self.state_role_arn is not None and self.apply_role_arn is not None

    @classmethod
    def load(
        cls,
        environ: Mapping[str, str],
        *,
        authorization: Literal["plan", "deploy", "apply"] = "plan",
    ) -> RemoteInputs:
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

        state_role_arn = _optional_role_env_value(
            environ,
            STATE_ROLE_ENV,
            role_label="state role",
        )
        plan_role_arn = _optional_role_env_value(
            environ,
            PLAN_ROLE_ENV,
            role_label="plan role",
        )
        apply_role_arn = _optional_role_env_value(
            environ,
            APPLY_ROLE_ENV,
            role_label="apply role",
        )

        if (
            state_role_arn is not None
            and plan_role_arn is not None
            and apply_role_arn is not None
        ):
            raise WorkflowError(
                "Invalid authorization roles: conflicting role configuration."
            )

        if authorization == "plan":
            if apply_role_arn is not None:
                raise WorkflowError("Plan command rejects apply role configuration.")
            state_role_arn, plan_role_arn = finalize_paired_plan_roles(
                state_role_arn,
                plan_role_arn,
                expected_account_id=account_id,
            )
            apply_role_arn = None
        elif authorization == "deploy":
            if plan_role_arn is not None:
                raise WorkflowError("Deploy command rejects plan role configuration.")
            state_role_arn, apply_role_arn = finalize_paired_apply_roles(
                state_role_arn,
                apply_role_arn,
                expected_account_id=account_id,
            )
            plan_role_arn = None
        else:
            if apply_role_arn is not None:
                raise WorkflowError(
                    "Controlled deployment requires the deploy command when apply "
                    "authorization is configured."
                )
            state_role_arn, plan_role_arn = finalize_paired_plan_roles(
                state_role_arn,
                plan_role_arn,
                expected_account_id=account_id,
            )
            apply_role_arn = None

        return cls(
            state_bucket=bucket,
            expected_account_id=account_id,
            state_role_arn=state_role_arn,
            plan_role_arn=plan_role_arn,
            apply_role_arn=apply_role_arn,
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


def _optional_role_env_value(
    environ: Mapping[str, str],
    name: str,
    *,
    role_label: str,
) -> str | None:
    """Return a present role ARN or None when the variable is absent."""
    if name not in environ:
        return None

    value = environ[name]
    if value.strip() == "":
        raise WorkflowError(f"Invalid {role_label}: empty value.")
    if value != value.strip() or any(character.isspace() for character in value):
        raise WorkflowError(f"Invalid {role_label}: invalid ARN shape.")
    return value


def validate_authorization_role_arn(
    role_arn: str,
    *,
    role_label: str,
    expected_role_name: str,
    expected_account_id: str,
) -> str:
    """Validate one state or plan IAM role ARN without echoing it."""
    if "*" in role_arn or any(character.isspace() for character in role_arn):
        raise WorkflowError(f"Invalid {role_label}: invalid ARN shape.")

    if ":assumed-role/" in role_arn or ":sts:" in role_arn:
        raise WorkflowError(f"Invalid {role_label}: invalid ARN shape.")

    match = IAM_ROLE_ARN_PATTERN.fullmatch(role_arn)
    if match is None:
        raise WorkflowError(f"Invalid {role_label}: invalid ARN shape.")

    role_name = match.group("name")
    if "/" in role_name:
        raise WorkflowError(f"Invalid {role_label}: invalid ARN shape.")
    if role_name != expected_role_name:
        raise WorkflowError(f"Invalid {role_label}: invalid ARN shape.")

    account_id = match.group("account")
    if account_id != expected_account_id:
        raise WorkflowError(f"Invalid {role_label}: account mismatch.")

    return role_arn


def finalize_paired_plan_roles(
    state_role_arn: str | None,
    plan_role_arn: str | None,
    *,
    expected_account_id: str,
) -> tuple[str | None, str | None]:
    """Validate ambient or chained plan-role authorization."""
    if state_role_arn is None and plan_role_arn is None:
        return None, None

    if state_role_arn is None or plan_role_arn is None:
        raise WorkflowError("Invalid authorization roles: missing paired role.")

    validated_state = validate_authorization_role_arn(
        state_role_arn,
        role_label="state role",
        expected_role_name=STATE_ROLE_NAME,
        expected_account_id=expected_account_id,
    )
    validated_plan = validate_authorization_role_arn(
        plan_role_arn,
        role_label="plan role",
        expected_role_name=PLAN_ROLE_NAME,
        expected_account_id=expected_account_id,
    )

    state_account = IAM_ROLE_ARN_PATTERN.fullmatch(validated_state)
    plan_account = IAM_ROLE_ARN_PATTERN.fullmatch(validated_plan)
    if (
        state_account is None
        or plan_account is None
        or state_account.group("account") != plan_account.group("account")
    ):
        raise WorkflowError("Invalid authorization roles: account mismatch.")

    return validated_state, validated_plan


def finalize_paired_apply_roles(
    state_role_arn: str | None,
    apply_role_arn: str | None,
    *,
    expected_account_id: str,
) -> tuple[str | None, str | None]:
    """Validate ambient or chained apply-role deployment authorization."""
    if state_role_arn is None and apply_role_arn is None:
        return None, None

    if state_role_arn is None or apply_role_arn is None:
        raise WorkflowError("Invalid authorization roles: missing paired role.")

    validated_state = validate_authorization_role_arn(
        state_role_arn,
        role_label="state role",
        expected_role_name=STATE_ROLE_NAME,
        expected_account_id=expected_account_id,
    )
    validated_apply = validate_authorization_role_arn(
        apply_role_arn,
        role_label="apply role",
        expected_role_name=APPLY_ROLE_NAME,
        expected_account_id=expected_account_id,
    )

    state_account = IAM_ROLE_ARN_PATTERN.fullmatch(validated_state)
    apply_account = IAM_ROLE_ARN_PATTERN.fullmatch(validated_apply)
    if (
        state_account is None
        or apply_account is None
        or state_account.group("account") != apply_account.group("account")
    ):
        raise WorkflowError("Invalid authorization roles: account mismatch.")

    return validated_state, validated_apply


def load_paired_role_arns(
    environ: Mapping[str, str],
    *,
    expected_account_id: str,
) -> tuple[str | None, str | None]:
    """Load ambient or chained plan role ARNs with paired-role validation."""
    state_role_arn = _optional_role_env_value(
        environ,
        STATE_ROLE_ENV,
        role_label="state role",
    )
    plan_role_arn = _optional_role_env_value(
        environ,
        PLAN_ROLE_ENV,
        role_label="plan role",
    )
    return finalize_paired_plan_roles(
        state_role_arn,
        plan_role_arn,
        expected_account_id=expected_account_id,
    )


def env_get_ci(environment: Mapping[str, str], name: str) -> str | None:
    """Read one environment value with Windows-safe case handling."""
    for key, value in environment.items():
        if key.lower() == name.lower():
            return value
    return None


def env_pop_ci(environment: dict[str, str], name: str) -> str | None:
    """Remove one environment value with Windows-safe case handling."""
    matched_keys = [key for key in environment if key.lower() == name.lower()]
    value: str | None = None
    for key in matched_keys:
        value = environment.pop(key)
    return value


def apply_plan_role_tf_var(
    child_environment: dict[str, str],
    plan_role_arn: str | None,
) -> None:
    """Map the plan role into TF_VAR_* with conflict detection."""
    existing = env_get_ci(child_environment, PLAN_ROLE_TF_VAR)

    if plan_role_arn is None:
        if existing is not None and existing != "":
            raise WorkflowError(
                "Invalid plan role: ambient mode rejects a pre-existing "
                f"{PLAN_ROLE_TF_VAR} value."
            )
        env_pop_ci(child_environment, PLAN_ROLE_TF_VAR)
        return

    if existing is not None and existing != plan_role_arn:
        raise WorkflowError(
            f"Invalid plan role: conflicting pre-existing {PLAN_ROLE_TF_VAR} value."
        )

    env_pop_ci(child_environment, PLAN_ROLE_TF_VAR)
    child_environment[PLAN_ROLE_TF_VAR] = plan_role_arn


def apply_apply_role_tf_var(
    child_environment: dict[str, str],
    apply_role_arn: str | None,
) -> None:
    """Map the apply role into TF_VAR_* with conflict detection."""
    existing = env_get_ci(child_environment, APPLY_ROLE_TF_VAR)

    if apply_role_arn is None:
        if existing is not None and existing != "":
            raise WorkflowError(
                "Invalid apply role: ambient mode rejects a pre-existing "
                f"{APPLY_ROLE_TF_VAR} value."
            )
        env_pop_ci(child_environment, APPLY_ROLE_TF_VAR)
        return

    if existing is not None and existing != apply_role_arn:
        raise WorkflowError(
            f"Invalid apply role: conflicting pre-existing {APPLY_ROLE_TF_VAR} value."
        )

    env_pop_ci(child_environment, APPLY_ROLE_TF_VAR)
    child_environment[APPLY_ROLE_TF_VAR] = apply_role_arn


def write_backend_override(
    *,
    path: Path,
    state_bucket: str,
    state_role_arn: str | None,
) -> Path:
    """Write an ephemeral backend override containing only runtime fields."""
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f'bucket = "{state_bucket}"\n']
    if state_role_arn is not None:
        lines.extend(
            [
                "assume_role = {\n",
                f'  role_arn     = "{state_role_arn}"\n',
                f'  session_name = "{STATE_ROLE_SESSION_NAME}"\n',
                f'  duration     = "{ROLE_SESSION_DURATION}"\n',
                "}\n",
            ]
        )

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    try:
        file_descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise WorkflowError(
            f"Could not create temporary backend override: {path}"
        ) from error

    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.writelines(lines)
    except OSError as error:
        path.unlink(missing_ok=True)
        raise WorkflowError(
            f"Could not write temporary backend override: {path}"
        ) from error

    return path


def remove_backend_override(path: Path) -> None:
    """Remove one ephemeral backend override and fail if cleanup cannot finish."""
    try:
        path.unlink(missing_ok=True)
    except OSError as error:
        raise WorkflowError(
            f"Could not remove temporary backend override: {path}"
        ) from error


def resolve_plan_output_directory(
    paths: WorkflowPaths,
    environment: str,
    output_directory: str | Path | None,
) -> Path:
    """Resolve the plan artifact directory, preserving the default when unset."""
    if output_directory is None:
        resolved = paths.plan_dir(environment)
    else:
        candidate = Path(output_directory).expanduser()
        if ".." in candidate.parts:
            raise WorkflowError(
                "Output directory must not contain parent path traversal."
            )
        resolved = candidate.resolve()
        if resolved.exists() and resolved.is_file():
            raise WorkflowError(
                "Plan output directory must not point to an existing regular file: "
                f"{resolved}."
            )

    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise WorkflowError(
            f"Could not create plan output directory: {resolved}"
        ) from error

    return resolved


def ensure_output_file_path(output_directory: Path, filename: str) -> Path:
    """Resolve one output file path and reject directory escape."""
    root = output_directory.resolve()
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
        raise WorkflowError(
            f"Deployment output path escapes the output directory: {filename}."
        )
    return target


def resolve_attestation_path(path: str | Path) -> Path:
    """Resolve one caller-owned attestation file path."""
    candidate = Path(path).expanduser()
    if ".." in candidate.parts:
        raise WorkflowError("Attestation path must not contain parent path traversal.")
    resolved = candidate.resolve()
    if resolved.is_dir():
        raise WorkflowError("Attestation path must be a regular file.")
    return resolved


def validate_repository(repository: str) -> None:
    """Require one owner/repository deployment binding."""
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise WorkflowError("Invalid repository identifier.")


def validate_plan_run_id(plan_run_id: str) -> None:
    """Require one positive decimal GitHub run ID."""
    if PLAN_RUN_ID_PATTERN.fullmatch(plan_run_id) is None:
        raise WorkflowError("Invalid plan run ID.")


def validate_commit_sha(commit_sha: str) -> None:
    """Require one lowercase 40-character commit SHA."""
    if COMMIT_SHA_PATTERN.fullmatch(commit_sha) is None:
        raise WorkflowError("Invalid commit SHA.")


def attestation_error_to_workflow(error: PlanAttestationError) -> WorkflowError:
    """Map attestation validation failures to workflow errors."""
    return WorkflowError(str(error))


def load_reviewed_attestation(
    path: Path,
    *,
    repository: str,
    plan_run_id: str,
    commit_sha: str,
    environment: str,
    allow_destructive_changes: bool,
) -> plan_attestation.TerraformPlanAttestation:
    """Validate one reviewed attestation before any Terraform subprocess."""
    try:
        reviewed = plan_attestation.read_attestation(path)
        plan_attestation.validate_attestation_context(
            reviewed,
            repository=repository,
            plan_run_id=plan_run_id,
            commit_sha=commit_sha,
            environment=environment,
        )
    except PlanAttestationError as error:
        raise attestation_error_to_workflow(error) from error

    if reviewed.destructive_changes and not allow_destructive_changes:
        raise WorkflowError("Destructive changes require --allow-destructive-changes.")

    return reviewed


def compare_deployment_attestations(
    reviewed: plan_attestation.TerraformPlanAttestation,
    regenerated: plan_attestation.TerraformPlanAttestation,
) -> None:
    """Require matching reviewed and regenerated deployment attestations."""
    comparisons = (
        ("schema_version", reviewed.schema_version, regenerated.schema_version),
        ("repository", reviewed.repository, regenerated.repository),
        ("plan_run_id", reviewed.plan_run_id, regenerated.plan_run_id),
        ("commit_sha", reviewed.commit_sha, regenerated.commit_sha),
        ("environment", reviewed.environment, regenerated.environment),
        (
            "change_set_fingerprint",
            reviewed.change_set_fingerprint,
            regenerated.change_set_fingerprint,
        ),
        ("no_changes", reviewed.no_changes, regenerated.no_changes),
        (
            "destructive_changes",
            reviewed.destructive_changes,
            regenerated.destructive_changes,
        ),
        (
            "action_counts",
            dict(reviewed.action_counts),
            dict(regenerated.action_counts),
        ),
        ("resource_changes", reviewed.resource_changes, regenerated.resource_changes),
    )
    for field, expected, actual in comparisons:
        if expected != actual:
            raise WorkflowError(f"Deployment attestation mismatch for {field}.")

    try:
        plan_attestation.require_matching_change_sets(reviewed, regenerated)
    except PlanAttestationError as error:
        raise attestation_error_to_workflow(error) from error


def validate_local_apply_plan_path(plan_file: Path) -> None:
    """Reject attestation files, directories, and other non-plan inputs."""
    if plan_file.is_dir():
        raise WorkflowError("Saved plan path must be a regular file.")
    if not plan_file.is_file():
        raise WorkflowError(f"Saved plan not found: {plan_file}")
    if plan_file.name in FORBIDDEN_LOCAL_APPLY_PLAN_NAMES:
        raise WorkflowError("Saved plan path is not a valid Terraform plan file.")
    if plan_file.name != PLAN_FILENAME:
        raise WorkflowError("Saved plan path is not a valid Terraform plan file.")


def run_terraform_show_json(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
    repository_root: Path,
    expected_account_id: str,
    plan_role_arn: str | None,
    apply_role_arn: str | None,
    plan_file: Path,
    output_path: Path,
) -> None:
    """Render one saved plan as JSON inside the deployment output directory."""
    data_dir = paths.data_dir(environment)
    if plan_role_arn is not None and apply_role_arn is not None:
        raise WorkflowError(
            "Invalid provider role configuration: plan and apply roles are exclusive."
        )

    child_environment = os.environ.copy()
    child_environment["TF_DATA_DIR"] = str(data_dir.resolve())
    child_environment["TF_IN_AUTOMATION"] = "1"
    env_pop_ci(child_environment, "TF_VAR_expected_aws_account_id")
    child_environment["TF_VAR_expected_aws_account_id"] = expected_account_id
    apply_plan_role_tf_var(child_environment, plan_role_arn)
    apply_apply_role_tf_var(child_environment, apply_role_arn)

    command = [
        binary,
        f"-chdir={paths.terraform_root}",
        "show",
        "-json",
        plan_file.as_posix(),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=repository_root,
            env=child_environment,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise WorkflowError(f"Terraform executable not found: {binary!r}.") from error
    except OSError as error:
        raise WorkflowError(f"Could not execute Terraform: {binary!r}.") from error

    if completed.returncode != 0:
        raise WorkflowError(
            f"Terraform show failed with exit code {completed.returncode}."
        )

    try:
        output_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    except OSError as error:
        raise WorkflowError(
            f"Could not write deployment plan JSON: {output_path}"
        ) from error


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
    plan_role_arn: str | None = None,
    apply_role_arn: str | None = None,
    accepted_codes: frozenset[int] = frozenset({0}),
) -> int:
    """Run Terraform without shell interpolation."""
    if plan_role_arn is not None and apply_role_arn is not None:
        raise WorkflowError(
            "Invalid provider role configuration: plan and apply roles are exclusive."
        )

    data_dir.mkdir(parents=True, exist_ok=True)
    child_environment = os.environ.copy()
    child_environment["TF_DATA_DIR"] = str(data_dir.resolve())
    child_environment["TF_IN_AUTOMATION"] = "1"

    if expected_account_id is None:
        env_pop_ci(child_environment, "TF_VAR_expected_aws_account_id")
    else:
        env_pop_ci(child_environment, "TF_VAR_expected_aws_account_id")
        child_environment["TF_VAR_expected_aws_account_id"] = expected_account_id

    apply_plan_role_tf_var(child_environment, plan_role_arn)
    apply_apply_role_tf_var(child_environment, apply_role_arn)

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


def provider_roles_for_mode(
    inputs: RemoteInputs,
    mode: Literal["plan", "deploy"],
) -> tuple[str | None, str | None]:
    """Return exclusive plan or apply provider roles for one workflow mode."""
    if mode == "plan":
        return inputs.plan_role_arn, None
    return None, inputs.apply_role_arn


def initialize_backend(
    *,
    binary: str,
    paths: WorkflowPaths,
    config: EnvironmentConfig,
    inputs: RemoteInputs,
    provider_mode: Literal["plan", "deploy"] = "plan",
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

    override_path = (
        paths.data_dir(config.environment)
        / "backend-overrides"
        / BACKEND_OVERRIDE_FILENAME
    )
    write_backend_override(
        path=override_path,
        state_bucket=inputs.state_bucket,
        state_role_arn=inputs.state_role_arn,
    )

    plan_role_arn, apply_role_arn = provider_roles_for_mode(inputs, provider_mode)

    try:
        run_terraform(
            binary=binary,
            root=paths.terraform_root,
            repository_root=paths.repository_root,
            data_dir=paths.data_dir(config.environment),
            expected_account_id=inputs.expected_account_id,
            plan_role_arn=plan_role_arn,
            apply_role_arn=apply_role_arn,
            arguments=[
                "init",
                "-input=false",
                "-reconfigure",
                "-lockfile=readonly",
                f"-backend-config={config.backend_file}",
                f"-backend-config={override_path}",
            ],
        )
    finally:
        remove_backend_override(override_path)


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
    """Validate committed Terraform roots without remote state or AWS access."""
    for relative_root in OFFLINE_TERRAFORM_ROOTS:
        root = paths.repository_root.joinpath(*relative_root.split("/"))
        data_dir = (
            paths.terraform_root
            / ".terraform-data"
            / "offline-roots"
            / relative_root.replace("/", "__")
        )
        print(f"Running offline Terraform checks for {relative_root}.")

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
            phase = arguments[0]
            try:
                run_terraform(
                    binary=binary,
                    root=root,
                    repository_root=paths.repository_root,
                    data_dir=data_dir,
                    arguments=arguments,
                )
            except WorkflowError as error:
                raise WorkflowError(
                    f"Offline check failed for root {relative_root} "
                    f"during {phase}: {error}"
                ) from error

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
    output_directory: str | Path | None = None,
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

    plan_directory = resolve_plan_output_directory(
        paths,
        environment,
        output_directory,
    )
    plan_file = plan_directory / PLAN_FILENAME
    manifest_file = plan_directory / MANIFEST_FILENAME
    plan_file.unlink(missing_ok=True)
    manifest_file.unlink(missing_ok=True)

    exit_code = run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        plan_role_arn=inputs.plan_role_arn,
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

    PlanManifest(
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
    inputs = RemoteInputs.load(environ, authorization="apply")

    verify_lambda_artifact(paths)
    validate_plan_binding(paths=paths, config=config, inputs=inputs)
    initialize_backend(
        binary=binary,
        paths=paths,
        config=config,
        inputs=inputs,
        provider_mode="plan",
    )

    plan_file = paths.plan_file(environment)
    validate_local_apply_plan_path(plan_file)
    print("Applying reviewed plan: " + display_path(plan_file, paths.repository_root))

    run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        plan_role_arn=inputs.plan_role_arn,
        arguments=[
            "apply",
            "-input=false",
            f"-lock-timeout={LOCK_TIMEOUT}",
            plan_file.as_posix(),
        ],
    )
    print("Terraform apply completed successfully.")


def command_deploy(
    *,
    binary: str,
    paths: WorkflowPaths,
    environment: str,
    environ: Mapping[str, str],
    attestation_path: str | Path,
    repository: str,
    plan_run_id: str,
    commit_sha: str,
    output_directory: str | Path | None = None,
    allow_destructive_changes: bool = False,
) -> None:
    """Run controlled deployment from one reviewed attestation."""
    validate_environment(environment)
    validate_repository(repository)
    validate_plan_run_id(plan_run_id)
    validate_commit_sha(commit_sha)

    attestation_file = resolve_attestation_path(attestation_path)
    if not attestation_file.is_file():
        raise WorkflowError("Attestation path must be a regular file.")

    reviewed = load_reviewed_attestation(
        attestation_file,
        repository=repository,
        plan_run_id=plan_run_id,
        commit_sha=commit_sha,
        environment=environment,
        allow_destructive_changes=allow_destructive_changes,
    )

    config = EnvironmentConfig.load(paths, environment)
    inputs = RemoteInputs.load(environ, authorization="deploy")

    verify_lambda_artifact(paths)
    output_dir = resolve_plan_output_directory(paths, environment, output_directory)

    deploy_plan = ensure_output_file_path(output_dir, DEPLOY_PLAN_FILENAME)
    deploy_plan_json = ensure_output_file_path(output_dir, DEPLOY_PLAN_JSON_FILENAME)
    deploy_show_json = ensure_output_file_path(output_dir, DEPLOY_SHOW_JSON_FILENAME)
    deploy_attestation_path = ensure_output_file_path(
        output_dir,
        DEPLOY_ATTESTATION_FILENAME,
    )
    post_apply_plan = ensure_output_file_path(output_dir, POST_APPLY_PLAN_FILENAME)

    for artifact in (
        deploy_plan,
        deploy_plan_json,
        deploy_show_json,
        deploy_attestation_path,
        post_apply_plan,
    ):
        artifact.unlink(missing_ok=True)

    initialize_backend(
        binary=binary,
        paths=paths,
        config=config,
        inputs=inputs,
        provider_mode="deploy",
    )

    plan_role_arn, apply_role_arn = provider_roles_for_mode(inputs, "deploy")

    run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        plan_role_arn=plan_role_arn,
        apply_role_arn=apply_role_arn,
        accepted_codes=frozenset({0, 2}),
        arguments=[
            "plan",
            "-input=false",
            f"-lock-timeout={LOCK_TIMEOUT}",
            "-detailed-exitcode",
            f"-var-file={config.tfvars_file}",
            f"-out={deploy_plan}",
        ],
    )

    if not deploy_plan.is_file():
        raise WorkflowError(
            f"Terraform did not create the regenerated deployment plan: {deploy_plan}"
        )

    run_terraform_show_json(
        binary=binary,
        paths=paths,
        environment=environment,
        repository_root=paths.repository_root,
        expected_account_id=inputs.expected_account_id,
        plan_role_arn=plan_role_arn,
        apply_role_arn=apply_role_arn,
        plan_file=deploy_plan,
        output_path=deploy_show_json,
    )

    try:
        deploy_plan_json.write_text(
            deploy_show_json.read_text(encoding="utf-8"),
            encoding="utf-8",
            newline="\n",
        )
    except OSError as error:
        raise WorkflowError(
            f"Could not write deployment plan JSON: {deploy_plan_json}"
        ) from error

    try:
        plan_document = plan_attestation.load_json_object(
            deploy_show_json,
            description="deployment plan JSON",
        )
        regenerated = plan_attestation.build_attestation(
            plan_document,
            repository=repository,
            plan_run_id=plan_run_id,
            commit_sha=commit_sha,
            environment=environment,
        )
        plan_attestation.write_attestation(deploy_attestation_path, regenerated)
    except PlanAttestationError as error:
        raise attestation_error_to_workflow(error) from error

    compare_deployment_attestations(reviewed, regenerated)

    if reviewed.no_changes and regenerated.no_changes:
        print(f"Verified no-op deployment for environment {environment}.")
        return

    try:
        run_terraform(
            binary=binary,
            root=paths.terraform_root,
            repository_root=paths.repository_root,
            data_dir=paths.data_dir(environment),
            expected_account_id=inputs.expected_account_id,
            plan_role_arn=plan_role_arn,
            apply_role_arn=apply_role_arn,
            arguments=[
                "apply",
                "-input=false",
                f"-lock-timeout={LOCK_TIMEOUT}",
                deploy_plan.as_posix(),
            ],
        )
    except WorkflowError as error:
        raise WorkflowError(
            "Terraform apply failed; infrastructure may be partially changed. "
            "Create a new reviewed plan before retry."
        ) from error

    print("Terraform apply completed successfully.")

    convergence_exit_code = run_terraform(
        binary=binary,
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir(environment),
        expected_account_id=inputs.expected_account_id,
        plan_role_arn=plan_role_arn,
        apply_role_arn=apply_role_arn,
        accepted_codes=frozenset({0, 2}),
        arguments=[
            "plan",
            "-input=false",
            f"-lock-timeout={LOCK_TIMEOUT}",
            "-detailed-exitcode",
            f"-var-file={config.tfvars_file}",
            f"-out={post_apply_plan}",
        ],
    )

    if convergence_exit_code == 2:
        raise WorkflowError(
            "Post-apply convergence check detected remaining changes. "
            "Create a new reviewed plan before retry."
        )

    print("Post-apply convergence verified.")


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
        plan_role_arn=inputs.plan_role_arn,
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
        help="Validate committed Terraform roots without remote state.",
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
        if name == "plan":
            command.add_argument(
                "--output-directory",
                default=None,
                help=(
                    "Optional directory for plan artifacts. "
                    "Defaults to artifacts/terraform/<environment>/."
                ),
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

    deploy_command = subparsers.add_parser(
        "deploy",
        help="Run controlled deployment from one reviewed attestation.",
    )
    deploy_command.add_argument(
        "--environment",
        required=True,
        choices=SUPPORTED_ENVIRONMENTS,
    )
    deploy_command.add_argument(
        "--attestation",
        required=True,
        help="Path to the reviewed value-free attestation JSON file.",
    )
    deploy_command.add_argument(
        "--repository",
        required=True,
        help="Exact owner/repository identifier for the deployment.",
    )
    deploy_command.add_argument(
        "--plan-run-id",
        required=True,
        dest="plan_run_id",
        help="Positive decimal GitHub Actions run ID for the reviewed plan.",
    )
    deploy_command.add_argument(
        "--commit-sha",
        required=True,
        dest="commit_sha",
        help="Lowercase 40-character commit SHA for the reviewed plan.",
    )
    deploy_command.add_argument(
        "--output-directory",
        default=None,
        help=(
            "Optional directory for deployment artifacts. "
            "Defaults to artifacts/terraform/<environment>/."
        ),
    )
    deploy_command.add_argument(
        "--allow-destructive-changes",
        action="store_true",
        default=False,
        help="Authorize deployment when the reviewed attestation is destructive.",
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
                output_directory=arguments.output_directory,
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
        elif arguments.command == "deploy":
            command_deploy(
                binary=binary,
                paths=paths,
                environment=arguments.environment,
                environ=current_environment,
                attestation_path=arguments.attestation,
                repository=arguments.repository,
                plan_run_id=arguments.plan_run_id,
                commit_sha=arguments.commit_sha,
                output_directory=arguments.output_directory,
                allow_destructive_changes=arguments.allow_destructive_changes,
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
