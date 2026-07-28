"""Offline unit tests for the guarded Terraform environment workflow."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPOSITORY_ROOT / "scripts" / "terraform_workflow.py"


def load_workflow_module() -> ModuleType:
    """Load the workflow script as an isolated test module."""
    spec = importlib.util.spec_from_file_location(
        "clouddoc_terraform_workflow",
        WORKFLOW_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load workflow module: {WORKFLOW_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = load_workflow_module()


@pytest.fixture
def paths(tmp_path: Path) -> Any:
    """Create one synthetic repository layout."""
    repository_root = tmp_path / "repository"
    terraform_root = repository_root / "infra" / "terraform"
    bootstrap_root = repository_root / "infra" / "bootstrap" / "terraform-state"
    environments_root = terraform_root / "environments"
    terraform_artifacts_root = repository_root / "artifacts" / "terraform"
    lambda_root = repository_root / "artifacts" / "lambda"

    environments_root.mkdir(parents=True)
    bootstrap_root.mkdir(parents=True)
    lambda_root.mkdir(parents=True)

    return workflow.WorkflowPaths(
        repository_root=repository_root,
        terraform_root=terraform_root,
        bootstrap_root=bootstrap_root,
        environments_root=environments_root,
        terraform_artifacts_root=terraform_artifacts_root,
        lambda_artifact=lambda_root / "clouddoc-app.zip",
        lambda_checksum=lambda_root / "clouddoc-app.sha256",
    )


def write_environment(
    paths: Any,
    *,
    environment: str = "dev",
    project_name: str = "clouddoc",
    aws_region: str = "us-east-1",
    backend_region: str | None = None,
    state_key: str | None = None,
    encrypt: bool = True,
    use_lockfile: bool = True,
    extra_tfvars: str = "",
    extra_backend: str = "",
) -> None:
    """Write one complete synthetic environment configuration."""
    backend_region = aws_region if backend_region is None else backend_region
    state_key = (
        f"{project_name}/{environment}/terraform.tfstate"
        if state_key is None
        else state_key
    )

    paths.tfvars_file(environment).write_text(
        (
            f'aws_region = "{aws_region}"\n'
            f'project_name = "{project_name}"\n'
            f'environment = "{environment}"\n'
            f"{extra_tfvars}"
        ),
        encoding="utf-8",
        newline="\n",
    )
    paths.backend_file(environment).write_text(
        (
            f'key = "{state_key}"\n'
            f'region = "{backend_region}"\n'
            f"encrypt = {str(encrypt).lower()}\n"
            f"use_lockfile = {str(use_lockfile).lower()}\n"
            f"{extra_backend}"
        ),
        encoding="utf-8",
        newline="\n",
    )


def remote_environment(
    *,
    account_id: str = "123456789012",
    bucket: str = "clouddoc-123456789012-terraform-state",
) -> dict[str, str]:
    """Return valid non-secret remote execution inputs."""
    return {
        workflow.STATE_BUCKET_ENV: bucket,
        workflow.EXPECTED_ACCOUNT_ENV: account_id,
    }


def write_valid_lambda_artifact(paths: Any, content: bytes = b"lambda-zip") -> None:
    """Write a Lambda artifact and matching checksum file."""
    paths.lambda_artifact.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    paths.lambda_checksum.write_text(
        f"{digest}  {paths.lambda_artifact.name}\n",
        encoding="utf-8",
        newline="\n",
    )


def write_bound_plan(
    paths: Any,
    *,
    environment: str = "dev",
    account_id: str = "123456789012",
    bucket: str = "clouddoc-123456789012-terraform-state",
    plan_content: bytes = b"saved-plan",
    exit_code: int = 2,
) -> Any:
    """Write one saved plan and a matching strict manifest."""
    write_environment(paths, environment=environment)
    config = workflow.EnvironmentConfig.load(paths, environment)
    inputs = workflow.RemoteInputs.load(
        remote_environment(account_id=account_id, bucket=bucket)
    )

    plan_file = paths.plan_file(environment)
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_bytes(plan_content)

    manifest = workflow.build_manifest(
        paths=paths,
        config=config,
        inputs=inputs,
        exit_code=exit_code,
    )
    manifest.write(paths.manifest_file(environment))
    return config, inputs, manifest


def test_committed_environment_files_have_distinct_explicit_contracts() -> None:
    """The real repository must expose three independent state identities."""
    real_paths = workflow.WorkflowPaths.from_script(WORKFLOW_PATH)

    configs = {
        environment: workflow.EnvironmentConfig.load(
            real_paths,
            environment,
        )
        for environment in workflow.SUPPORTED_ENVIRONMENTS
    }

    assert set(configs) == {"dev", "staging", "prod"}
    assert {config.environment for config in configs.values()} == {
        "dev",
        "staging",
        "prod",
    }
    assert {config.state_key for config in configs.values()} == {
        "clouddoc/dev/terraform.tfstate",
        "clouddoc/staging/terraform.tfstate",
        "clouddoc/prod/terraform.tfstate",
    }
    assert {config.aws_region for config in configs.values()} == {"us-east-1"}
    assert {config.project_name for config in configs.values()} == {"clouddoc"}


@pytest.mark.parametrize("environment", ["dev", "staging", "prod"])
def test_environment_config_loads_valid_files(
    paths: Any,
    environment: str,
) -> None:
    """Each approved environment should load its matching state key."""
    write_environment(paths, environment=environment)

    config = workflow.EnvironmentConfig.load(paths, environment)

    assert config.environment == environment
    assert config.project_name == "clouddoc"
    assert config.aws_region == "us-east-1"
    assert config.state_key == f"clouddoc/{environment}/terraform.tfstate"


def test_parse_assignments_accepts_comments_strings_and_booleans(
    tmp_path: Path,
) -> None:
    """Committed scalar configuration should parse deterministically."""
    source = tmp_path / "configuration.tfbackend"
    source.write_text(
        (
            "# comment\n"
            'key = "clouddoc/dev/terraform.tfstate" # trailing comment\n'
            "encrypt = true\n"
            "use_lockfile = false\n"
        ),
        encoding="utf-8",
        newline="\n",
    )

    assert workflow.parse_assignments(source) == {
        "key": "clouddoc/dev/terraform.tfstate",
        "encrypt": True,
        "use_lockfile": False,
    }


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        (
            "environment",
            'environment = "prod"\n',
            "Environment mismatch",
        ),
        (
            "backend_region",
            'region = "eu-west-1"\n',
            "Region mismatch",
        ),
        (
            "state_key",
            'key = "clouddoc/prod/terraform.tfstate"\n',
            "must use state key",
        ),
        (
            "encrypt",
            "encrypt = false\n",
            "must set encrypt = true",
        ),
        (
            "use_lockfile",
            "use_lockfile = false\n",
            "must set use_lockfile = true",
        ),
    ],
)
def test_environment_config_rejects_cross_environment_or_unsafe_values(
    paths: Any,
    field: str,
    replacement: str,
    message: str,
) -> None:
    """Environment files must not silently cross state boundaries."""
    write_environment(paths)

    target = (
        paths.tfvars_file("dev")
        if field == "environment"
        else paths.backend_file("dev")
    )
    source = target.read_text(encoding="utf-8")

    prefixes = {
        "environment": "environment = ",
        "backend_region": "region = ",
        "state_key": "key = ",
        "encrypt": "encrypt = ",
        "use_lockfile": "use_lockfile = ",
    }
    source = (
        "\n".join(
            replacement.rstrip("\n") if line.startswith(prefixes[field]) else line
            for line in source.splitlines()
        )
        + "\n"
    )
    target.write_text(source, encoding="utf-8", newline="\n")

    with pytest.raises(workflow.WorkflowError, match=message):
        workflow.EnvironmentConfig.load(paths, "dev")


@pytest.mark.parametrize(
    ("extra_tfvars", "extra_backend"),
    [
        ('expected_aws_account_id = "123456789012"\n', ""),
        ("", 'bucket = "committed-bucket"\n'),
        ("", 'profile = "developer"\n'),
        ("", 'dynamodb_table = "state-lock"\n'),
    ],
)
def test_environment_config_rejects_unapproved_fields(
    paths: Any,
    extra_tfvars: str,
    extra_backend: str,
) -> None:
    """Runtime-only state and identity values must not enter committed files."""
    write_environment(
        paths,
        extra_tfvars=extra_tfvars,
        extra_backend=extra_backend,
    )

    with pytest.raises(workflow.WorkflowError, match="Invalid field contract"):
        workflow.EnvironmentConfig.load(paths, "dev")


def test_parse_assignments_rejects_duplicate_or_complex_syntax(
    tmp_path: Path,
) -> None:
    """The parser must reject ambiguous or expanded HCL syntax."""
    duplicate = tmp_path / "duplicate.tfvars"
    duplicate.write_text(
        'environment = "dev"\nenvironment = "prod"\n',
        encoding="utf-8",
    )
    with pytest.raises(workflow.WorkflowError, match="Duplicate field"):
        workflow.parse_assignments(duplicate)

    complex_source = tmp_path / "complex.tfbackend"
    complex_source.write_text(
        'key = format("%s/dev/terraform.tfstate", "clouddoc")\n',
        encoding="utf-8",
    )
    with pytest.raises(workflow.WorkflowError, match="Only quoted strings"):
        workflow.parse_assignments(complex_source)


def test_remote_inputs_require_bucket_and_account() -> None:
    """Authenticated operations require both explicit non-secret inputs."""
    with pytest.raises(
        workflow.WorkflowError,
        match=workflow.STATE_BUCKET_ENV,
    ):
        workflow.RemoteInputs.load({})

    with pytest.raises(
        workflow.WorkflowError,
        match=workflow.EXPECTED_ACCOUNT_ENV,
    ):
        workflow.RemoteInputs.load({workflow.STATE_BUCKET_ENV: "clouddoc-state"})


@pytest.mark.parametrize(
    "account_id",
    ["", "123", "12345678901a", "1234567890123"],
)
def test_remote_inputs_reject_invalid_account_ids(account_id: str) -> None:
    """The provider guard must receive exactly one 12-digit account ID."""
    environ = remote_environment(account_id=account_id)

    with pytest.raises(workflow.WorkflowError):
        workflow.RemoteInputs.load(environ)


@pytest.mark.parametrize(
    "bucket",
    [
        "ab",
        "UPPERCASE-BUCKET",
        "192.168.0.1",
        "bucket..name",
        "-bucket",
        "bucket-",
    ],
)
def test_remote_inputs_reject_invalid_bucket_names(bucket: str) -> None:
    """Malformed bucket names must fail before Terraform starts."""
    environ = remote_environment(bucket=bucket)

    with pytest.raises(workflow.WorkflowError):
        workflow.RemoteInputs.load(environ)


def test_remote_inputs_load_valid_values() -> None:
    """Valid non-secret execution inputs should remain unchanged."""
    inputs = workflow.RemoteInputs.load(remote_environment())

    assert inputs.state_bucket == "clouddoc-123456789012-terraform-state"
    assert inputs.expected_account_id == "123456789012"
    assert inputs.state_role_arn is None
    assert inputs.plan_role_arn is None
    assert inputs.apply_role_arn is None
    assert inputs.uses_chained_roles is False


@pytest.mark.parametrize(
    "relative_path",
    [
        "terraform.tfstate",
        "terraform.tfstate.backup",
    ],
)
def test_local_state_blocks_remote_initialization(
    paths: Any,
    relative_path: str,
) -> None:
    """Nonempty local state must require a deliberate migration."""
    state_file = paths.terraform_root / relative_path
    state_file.write_text("{}", encoding="utf-8")

    with pytest.raises(
        workflow.WorkflowError,
        match="Automatic migration is forbidden",
    ):
        workflow.require_no_local_state(paths)


def test_workspace_state_directory_blocks_remote_initialization(
    paths: Any,
) -> None:
    """Legacy workspace state must not be silently ignored."""
    (paths.terraform_root / "terraform.tfstate.d").mkdir()

    with pytest.raises(
        workflow.WorkflowError,
        match="Automatic migration is forbidden",
    ):
        workflow.require_no_local_state(paths)


def test_empty_local_state_file_does_not_trigger_migration_guard(
    paths: Any,
) -> None:
    """An empty placeholder does not represent authoritative state."""
    (paths.terraform_root / "terraform.tfstate").touch()

    workflow.require_no_local_state(paths)


def test_lambda_artifact_guard_accepts_matching_checksum(paths: Any) -> None:
    """A reviewed Lambda package should pass the pre-plan guard."""
    write_valid_lambda_artifact(paths)

    workflow.verify_lambda_artifact(paths)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_artifact",
        "missing_checksum",
        "wrong_filename",
        "invalid_digest",
        "checksum_mismatch",
    ],
)
def test_lambda_artifact_guard_rejects_invalid_inputs(
    paths: Any,
    mutation: str,
) -> None:
    """Plans and applies must stop when the Lambda package is untrusted."""
    write_valid_lambda_artifact(paths)

    if mutation == "missing_artifact":
        paths.lambda_artifact.unlink()
    elif mutation == "missing_checksum":
        paths.lambda_checksum.unlink()
    elif mutation == "wrong_filename":
        digest = hashlib.sha256(paths.lambda_artifact.read_bytes()).hexdigest()
        paths.lambda_checksum.write_text(
            f"{digest}  other.zip\n",
            encoding="utf-8",
        )
    elif mutation == "invalid_digest":
        paths.lambda_checksum.write_text(
            f"not-a-digest  {paths.lambda_artifact.name}\n",
            encoding="utf-8",
        )
    else:
        paths.lambda_artifact.write_bytes(b"tampered")

    with pytest.raises(workflow.WorkflowError):
        workflow.verify_lambda_artifact(paths)


def test_run_terraform_uses_argument_list_and_isolated_environment(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terraform execution must avoid shell interpolation and leak no override."""
    captured: dict[str, Any] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        captured.update(
            command=command,
            cwd=cwd,
            env=env,
            check=check,
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    monkeypatch.setenv(
        "TF_VAR_expected_aws_account_id",
        "999999999999",
    )

    exit_code = workflow.run_terraform(
        binary="terraform-custom",
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir("dev"),
        arguments=["validate"],
        expected_account_id="123456789012",
    )

    assert exit_code == 0
    assert captured["command"] == [
        "terraform-custom",
        f"-chdir={paths.terraform_root}",
        "validate",
    ]
    assert captured["cwd"] == paths.repository_root
    assert captured["check"] is False
    assert captured["env"]["TF_IN_AUTOMATION"] == "1"
    assert captured["env"]["TF_DATA_DIR"] == str(paths.data_dir("dev").resolve())
    assert captured["env"]["TF_VAR_expected_aws_account_id"] == "123456789012"


def test_run_terraform_removes_stale_account_override_for_offline_checks(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline checks must not inherit a shell account restriction."""
    captured_environment: dict[str, str] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, check
        captured_environment.update(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    monkeypatch.setenv(
        "TF_VAR_expected_aws_account_id",
        "999999999999",
    )

    workflow.run_terraform(
        binary="terraform",
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir("offline"),
        arguments=["validate"],
    )

    assert "TF_VAR_expected_aws_account_id" not in captured_environment


def test_run_terraform_rejects_unapproved_exit_code(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected Terraform failures must become workflow failures."""
    monkeypatch.setattr(
        workflow.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1),
    )

    with pytest.raises(workflow.WorkflowError, match="exit code 1"):
        workflow.run_terraform(
            binary="terraform",
            root=paths.terraform_root,
            repository_root=paths.repository_root,
            data_dir=paths.data_dir("dev"),
            arguments=["plan"],
            accepted_codes=frozenset({0, 2}),
        )


def test_initialize_backend_rejects_bucket_account_mismatch_before_execution(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid S3 name is still rejected when it belongs to another account."""
    write_environment(paths)
    config = workflow.EnvironmentConfig.load(paths, "dev")
    inputs = workflow.RemoteInputs.load(
        remote_environment(bucket="clouddoc-999999999999-terraform-state")
    )
    called = False

    def fail_if_called(**kwargs: Any) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fail_if_called)

    with pytest.raises(workflow.WorkflowError, match="must match"):
        workflow.initialize_backend(
            binary="terraform",
            paths=paths,
            config=config,
            inputs=inputs,
        )

    assert called is False


def test_initialize_backend_builds_exact_safe_command(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote initialization must use reconfigure and explicit partial inputs."""
    write_environment(paths)
    config = workflow.EnvironmentConfig.load(paths, "dev")
    inputs = workflow.RemoteInputs.load(remote_environment())
    captured: dict[str, Any] = {}
    override_snapshot: dict[str, str] = {}

    def fake_run_terraform(**kwargs: Any) -> int:
        captured.update(kwargs)
        override_argument = next(
            argument
            for argument in kwargs["arguments"]
            if argument.startswith("-backend-config=")
            and argument.endswith(workflow.BACKEND_OVERRIDE_FILENAME)
        )
        override_path = Path(override_argument.removeprefix("-backend-config="))
        override_snapshot["path"] = str(override_path)
        override_snapshot["content"] = override_path.read_text(encoding="utf-8")
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    workflow.initialize_backend(
        binary="terraform",
        paths=paths,
        config=config,
        inputs=inputs,
    )

    override_path = Path(override_snapshot["path"])
    assert captured["arguments"] == [
        "init",
        "-input=false",
        "-reconfigure",
        "-lockfile=readonly",
        f"-backend-config={config.backend_file}",
        f"-backend-config={override_path}",
    ]
    assert captured["expected_account_id"] == "123456789012"
    assert captured["plan_role_arn"] is None
    assert captured["data_dir"] == paths.data_dir("dev")
    assert override_snapshot["content"] == (
        'bucket = "clouddoc-123456789012-terraform-state"\n'
    )
    assert "assume_role" not in override_snapshot["content"]
    assert not override_path.exists()
    assert config.backend_file.read_text(encoding="utf-8") == (
        'key = "clouddoc/dev/terraform.tfstate"\n'
        'region = "us-east-1"\n'
        "encrypt = true\n"
        "use_lockfile = true\n"
    )


def test_plan_manifest_round_trip_is_strict(paths: Any) -> None:
    """The manifest should preserve plan binding and reject schema drift."""
    _, _, manifest = write_bound_plan(paths)
    manifest_path = paths.manifest_file("dev")

    loaded = workflow.PlanManifest.read(manifest_path)

    assert loaded == manifest

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["unexpected"] = "value"
    manifest_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(workflow.WorkflowError, match="unexpected schema"):
        workflow.PlanManifest.read(manifest_path)


def test_plan_manifest_rejects_invalid_exit_code(paths: Any) -> None:
    """Only Terraform detailed-exitcode success values are valid."""
    _, _, _ = write_bound_plan(paths)
    manifest_path = paths.manifest_file("dev")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["terraform_exit_code"] = 1
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(workflow.WorkflowError, match="invalid Terraform"):
        workflow.PlanManifest.read(manifest_path)


def test_plan_binding_accepts_intact_plan(paths: Any) -> None:
    """An unchanged plan bound to the same environment and account is valid."""
    config, inputs, _ = write_bound_plan(paths)

    workflow.validate_plan_binding(
        paths=paths,
        config=config,
        inputs=inputs,
    )


def test_plan_binding_rejects_tampered_plan(paths: Any) -> None:
    """Apply must reject a plan changed after manifest creation."""
    config, inputs, _ = write_bound_plan(paths)
    paths.plan_file("dev").write_bytes(b"tampered-plan")

    with pytest.raises(workflow.WorkflowError, match="integrity check"):
        workflow.validate_plan_binding(
            paths=paths,
            config=config,
            inputs=inputs,
        )


def test_plan_binding_rejects_other_account_or_bucket(paths: Any) -> None:
    """A plan cannot be reused against a different state/account boundary."""
    config, _, _ = write_bound_plan(paths)
    other_inputs = workflow.RemoteInputs.load(
        remote_environment(
            account_id="999999999999",
            bucket="clouddoc-999999999999-terraform-state",
        )
    )

    with pytest.raises(workflow.WorkflowError, match="manifest mismatch"):
        workflow.validate_plan_binding(
            paths=paths,
            config=config,
            inputs=other_inputs,
        )


def test_command_plan_creates_bound_manifest_and_safe_plan_command(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan must use detailed exit code, locking, tfvars, and a saved file."""
    write_environment(paths)
    write_valid_lambda_artifact(paths)

    initialization_calls: list[tuple[Any, Any]] = []
    terraform_calls: list[dict[str, Any]] = []

    def fake_initialize_backend(**kwargs: Any) -> None:
        initialization_calls.append((kwargs["config"], kwargs["inputs"]))

    def fake_run_terraform(**kwargs: Any) -> int:
        terraform_calls.append(kwargs)
        arguments = kwargs["arguments"]
        if arguments[0] == "plan":
            output_argument = next(
                argument for argument in arguments if argument.startswith("-out=")
            )
            Path(output_argument.removeprefix("-out=")).write_bytes(b"generated-plan")
            return 2
        return 0

    monkeypatch.setattr(
        workflow,
        "initialize_backend",
        fake_initialize_backend,
    )
    monkeypatch.setattr(
        workflow,
        "run_terraform",
        fake_run_terraform,
    )

    workflow.command_plan(
        binary="terraform",
        paths=paths,
        environment="dev",
        environ=remote_environment(),
    )

    assert len(initialization_calls) == 1
    assert len(terraform_calls) == 1

    arguments = terraform_calls[0]["arguments"]
    assert arguments[0] == "plan"
    assert "-input=false" in arguments
    assert "-lock-timeout=5m" in arguments
    assert "-detailed-exitcode" in arguments
    assert f"-var-file={paths.tfvars_file('dev')}" in arguments
    assert f"-out={paths.plan_file('dev')}" in arguments
    assert "-lock=false" not in arguments
    assert "-auto-approve" not in arguments

    manifest = workflow.PlanManifest.read(paths.manifest_file("dev"))
    assert manifest.environment == "dev"
    assert manifest.state_key == "clouddoc/dev/terraform.tfstate"
    assert manifest.terraform_exit_code == 2
    assert manifest.plan_sha256 == hashlib.sha256(b"generated-plan").hexdigest()


def test_command_apply_rejects_confirmation_before_any_dependency(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatched confirmation must fail before files, AWS, or Terraform."""
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(
        workflow.EnvironmentConfig,
        "load",
        fail_if_called,
    )

    with pytest.raises(workflow.WorkflowError, match="confirmation mismatch"):
        workflow.command_apply(
            binary="terraform",
            paths=paths,
            environment="prod",
            confirmation="dev",
            environ={},
        )

    assert called is False


def test_command_apply_uses_only_the_bound_saved_plan(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply must receive the selected saved plan and no approval bypass."""
    write_valid_lambda_artifact(paths)
    write_bound_plan(paths)
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        workflow,
        "initialize_backend",
        lambda **kwargs: None,
    )

    def fake_run_terraform(**kwargs: Any) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        workflow,
        "run_terraform",
        fake_run_terraform,
    )

    workflow.command_apply(
        binary="terraform",
        paths=paths,
        environment="dev",
        confirmation="dev",
        environ=remote_environment(),
    )

    assert len(calls) == 1
    arguments = calls[0]["arguments"]
    assert arguments == [
        "apply",
        "-input=false",
        "-lock-timeout=5m",
        paths.plan_file("dev").as_posix(),
    ]
    assert "-auto-approve" not in arguments
    assert "-lock=false" not in arguments
    assert calls[0]["expected_account_id"] == "123456789012"


def test_command_show_plan_rejects_tampering_without_running_terraform(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Showing a changed plan must fail before Terraform invocation."""
    write_bound_plan(paths)
    paths.plan_file("dev").write_bytes(b"tampered")
    called = False

    def fail_if_called(**kwargs: Any) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fail_if_called)

    with pytest.raises(workflow.WorkflowError, match="integrity check"):
        workflow.command_show_plan(
            binary="terraform",
            paths=paths,
            environment="dev",
        )

    assert called is False


def test_offline_check_runs_committed_roots_with_backend_disabled(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline validation must cover every committed root without remote state."""
    for relative_root in workflow.OFFLINE_TERRAFORM_ROOTS:
        (paths.repository_root.joinpath(*relative_root.split("/"))).mkdir(
            parents=True,
            exist_ok=True,
        )

    calls: list[dict[str, Any]] = []

    def fake_run_terraform(**kwargs: Any) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(
        workflow,
        "run_terraform",
        fake_run_terraform,
    )

    workflow.command_offline_check(binary="terraform", paths=paths)

    assert workflow.OFFLINE_TERRAFORM_ROOTS == (
        "infra/terraform",
        "infra/bootstrap/terraform-state",
        "infra/bootstrap/github-oidc",
        "infra/bootstrap/terraform-authorization",
    )
    assert len(workflow.OFFLINE_TERRAFORM_ROOTS) == 4
    assert len(calls) == 16

    roots = {str(call["root"]) for call in calls}
    expected_roots = {
        str(paths.repository_root.joinpath(*relative.split("/")))
        for relative in workflow.OFFLINE_TERRAFORM_ROOTS
    }
    assert roots == expected_roots

    init_calls = [call for call in calls if call["arguments"][0] == "init"]
    assert len(init_calls) == 4
    for call in init_calls:
        assert call["arguments"] == (
            "init",
            "-backend=false",
            "-lockfile=readonly",
            "-input=false",
        )
        assert call.get("expected_account_id") is None
        assert call.get("plan_role_arn") is None

    forbidden = {"plan", "apply", "destroy", "import", "state"}
    assert not any(call["arguments"][0] in forbidden for call in calls)


def test_cli_exposes_only_approved_commands() -> None:
    """The operator interface must not offer destructive shortcuts."""
    parser = workflow.create_parser()
    subparsers_action = next(
        action
        for action in parser._actions
        if isinstance(action, workflow.argparse._SubParsersAction)
    )

    assert set(subparsers_action.choices) == {
        "offline-check",
        "init",
        "plan",
        "show-plan",
        "apply",
        "deploy",
        "output",
    }


def test_source_contains_no_forbidden_terraform_actions() -> None:
    """The workflow source must not encode unsafe Terraform operations."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    for forbidden in (
        '"destroy"',
        '"force-unlock"',
        '"workspace"',
        '"-lock=false"',
        '"-auto-approve"',
        '"-migrate-state"',
        "shell=True",
        "os.system",
    ):
        assert forbidden not in source


def test_main_returns_one_for_missing_remote_inputs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI workflow failures should be concise and non-traceback outcomes."""
    monkeypatch.setattr(
        workflow.WorkflowPaths,
        "from_script",
        lambda _: workflow.WorkflowPaths(
            repository_root=Path("/repository"),
            terraform_root=Path("/repository/infra/terraform"),
            bootstrap_root=Path("/repository/infra/bootstrap/terraform-state"),
            environments_root=Path("/repository/infra/terraform/environments"),
            terraform_artifacts_root=Path("/repository/artifacts/terraform"),
            lambda_artifact=Path("/repository/artifacts/lambda/clouddoc-app.zip"),
            lambda_checksum=Path("/repository/artifacts/lambda/clouddoc-app.sha256"),
        ),
    )
    monkeypatch.setattr(
        workflow.EnvironmentConfig,
        "load",
        lambda paths, environment: workflow.EnvironmentConfig(
            environment=environment,
            project_name="clouddoc",
            aws_region="us-east-1",
            state_key=f"clouddoc/{environment}/terraform.tfstate",
            tfvars_file=paths.tfvars_file(environment),
            backend_file=paths.backend_file(environment),
        ),
    )

    exit_code = workflow.main(
        ["init", "--environment", "dev"],
        environ={},
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Missing required environment variable" in captured.err
    assert "Traceback" not in captured.err


ACCOUNT_ID = "123456789012"
OTHER_ACCOUNT_ID = "999999999999"
VALID_STATE_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/{workflow.STATE_ROLE_NAME}"
VALID_PLAN_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/{workflow.PLAN_ROLE_NAME}"
VALID_APPLY_ROLE = f"arn:aws:iam::{ACCOUNT_ID}:role/{workflow.APPLY_ROLE_NAME}"


def role_environment(
    *,
    state_role: str | None = VALID_STATE_ROLE,
    plan_role: str | None = VALID_PLAN_ROLE,
    apply_role: str | None = None,
    account_id: str = ACCOUNT_ID,
    bucket: str | None = None,
) -> dict[str, str]:
    """Build remote inputs with optional paired role ARNs."""
    environ = remote_environment(
        account_id=account_id,
        bucket=(f"clouddoc-{account_id}-terraform-state" if bucket is None else bucket),
    )
    if state_role is not None:
        environ[workflow.STATE_ROLE_ENV] = state_role
    if plan_role is not None:
        environ[workflow.PLAN_ROLE_ENV] = plan_role
    if apply_role is not None:
        environ[workflow.APPLY_ROLE_ENV] = apply_role
    return environ


def deploy_role_environment(
    *,
    state_role: str | None = VALID_STATE_ROLE,
    apply_role: str | None = VALID_APPLY_ROLE,
    account_id: str = ACCOUNT_ID,
) -> dict[str, str]:
    """Build deploy authorization inputs with optional chained apply roles."""
    return role_environment(
        state_role=state_role,
        plan_role=None,
        apply_role=apply_role,
        account_id=account_id,
    )


def test_remote_inputs_load_chained_roles() -> None:
    """Both valid role ARNs enable chained-role mode."""
    inputs = workflow.RemoteInputs.load(role_environment())

    assert inputs.state_role_arn == VALID_STATE_ROLE
    assert inputs.plan_role_arn == VALID_PLAN_ROLE
    assert inputs.uses_chained_roles is True


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        (
            role_environment(plan_role=None),
            "missing paired role",
        ),
        (
            role_environment(state_role=None),
            "missing paired role",
        ),
        (
            {
                **remote_environment(),
                workflow.STATE_ROLE_ENV: "",
                workflow.PLAN_ROLE_ENV: VALID_PLAN_ROLE,
            },
            "state role",
        ),
        (
            {
                **remote_environment(),
                workflow.STATE_ROLE_ENV: VALID_STATE_ROLE,
                workflow.PLAN_ROLE_ENV: "",
            },
            "plan role",
        ),
        (
            role_environment(
                state_role=f"arn:aws:iam::{ACCOUNT_ID}:role/other-state-role",
            ),
            "state role",
        ),
        (
            role_environment(
                plan_role=f"arn:aws:iam::{ACCOUNT_ID}:role/other-plan-role",
            ),
            "plan role",
        ),
        (
            role_environment(
                state_role=(
                    f"arn:aws:iam::{OTHER_ACCOUNT_ID}:role/{workflow.STATE_ROLE_NAME}"
                ),
            ),
            "account mismatch",
        ),
        (
            role_environment(
                plan_role=(
                    f"arn:aws:iam::{OTHER_ACCOUNT_ID}:role/{workflow.PLAN_ROLE_NAME}"
                ),
            ),
            "account mismatch",
        ),
        (
            role_environment(
                state_role=(
                    f"arn:aws:iam::{ACCOUNT_ID}:role/{workflow.STATE_ROLE_NAME}*"
                ),
            ),
            "invalid ARN shape",
        ),
        (
            role_environment(
                state_role=(
                    f"arn:aws:sts::{ACCOUNT_ID}:assumed-role/"
                    f"{workflow.STATE_ROLE_NAME}/session"
                ),
            ),
            "invalid ARN shape",
        ),
        (
            role_environment(
                plan_role=(
                    f"arn:aws:iam::{ACCOUNT_ID}:role/path/{workflow.PLAN_ROLE_NAME}"
                ),
            ),
            "invalid ARN shape",
        ),
    ],
)
def test_remote_inputs_reject_invalid_role_pairs(
    environ: dict[str, str],
    message: str,
) -> None:
    """Paired-role validation must fail with sanitized diagnostics."""
    with pytest.raises(workflow.WorkflowError, match=message) as raised:
        workflow.RemoteInputs.load(environ)

    error_text = str(raised.value)
    assert VALID_STATE_ROLE not in error_text
    assert VALID_PLAN_ROLE not in error_text
    assert "arn:aws:" not in error_text


def test_run_terraform_sets_plan_role_tf_var_in_chained_mode(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chained mode must publish the plan role through TF_VAR_*."""
    captured_environment: dict[str, str] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, check
        captured_environment.update(env)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)

    workflow.run_terraform(
        binary="terraform",
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir("dev"),
        arguments=["validate"],
        expected_account_id=ACCOUNT_ID,
        plan_role_arn=VALID_PLAN_ROLE,
    )

    assert captured_environment[workflow.PLAN_ROLE_TF_VAR] == VALID_PLAN_ROLE


def test_run_terraform_accepts_matching_preexisting_plan_role_tf_var(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An identical pre-existing TF_VAR value is accepted."""
    captured_environment: dict[str, str] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, check
        captured_environment.update(env)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    monkeypatch.setenv(workflow.PLAN_ROLE_TF_VAR, VALID_PLAN_ROLE)

    workflow.run_terraform(
        binary="terraform",
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir("dev"),
        arguments=["validate"],
        expected_account_id=ACCOUNT_ID,
        plan_role_arn=VALID_PLAN_ROLE,
    )

    assert captured_environment[workflow.PLAN_ROLE_TF_VAR] == VALID_PLAN_ROLE


def test_run_terraform_rejects_conflicting_plan_role_tf_var(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A conflicting pre-existing TF_VAR value must fail before Terraform."""
    monkeypatch.setenv(
        workflow.PLAN_ROLE_TF_VAR,
        f"arn:aws:iam::{ACCOUNT_ID}:role/other-plan-role",
    )
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(workflow.subprocess, "run", fail_if_called)

    with pytest.raises(workflow.WorkflowError, match="conflicting"):
        workflow.run_terraform(
            binary="terraform",
            root=paths.terraform_root,
            repository_root=paths.repository_root,
            data_dir=paths.data_dir("dev"),
            arguments=["validate"],
            expected_account_id=ACCOUNT_ID,
            plan_role_arn=VALID_PLAN_ROLE,
        )

    assert called is False


def test_run_terraform_ambient_mode_leaves_plan_role_tf_var_absent(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient mode must not synthesize a provider role TF variable."""
    captured_environment: dict[str, str] = {}

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del command, cwd, check
        captured_environment.update(env)
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(workflow.subprocess, "run", fake_run)
    monkeypatch.delenv(workflow.PLAN_ROLE_TF_VAR, raising=False)

    workflow.run_terraform(
        binary="terraform",
        root=paths.terraform_root,
        repository_root=paths.repository_root,
        data_dir=paths.data_dir("dev"),
        arguments=["validate"],
        expected_account_id=ACCOUNT_ID,
    )

    assert workflow.PLAN_ROLE_TF_VAR not in captured_environment


def test_run_terraform_ambient_mode_rejects_preexisting_plan_role_tf_var(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambient mode rejects a non-empty pre-existing plan-role TF variable."""
    monkeypatch.setenv(workflow.PLAN_ROLE_TF_VAR, VALID_PLAN_ROLE)
    called = False

    def fail_if_called(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(workflow.subprocess, "run", fail_if_called)

    with pytest.raises(workflow.WorkflowError, match="ambient mode"):
        workflow.run_terraform(
            binary="terraform",
            root=paths.terraform_root,
            repository_root=paths.repository_root,
            data_dir=paths.data_dir("dev"),
            arguments=["validate"],
            expected_account_id=ACCOUNT_ID,
        )

    assert called is False


def test_initialize_backend_writes_chained_override_without_logging_arn(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Chained mode must add assume_role fields only in the ephemeral override."""
    write_environment(paths)
    config = workflow.EnvironmentConfig.load(paths, "dev")
    inputs = workflow.RemoteInputs.load(role_environment())
    override_snapshot: dict[str, str] = {}
    captured_arguments: list[str] = []

    def fake_run_terraform(**kwargs: Any) -> int:
        captured_arguments.extend(kwargs["arguments"])
        override_argument = next(
            argument
            for argument in kwargs["arguments"]
            if argument.startswith("-backend-config=")
            and argument.endswith(workflow.BACKEND_OVERRIDE_FILENAME)
        )
        override_path = Path(override_argument.removeprefix("-backend-config="))
        override_snapshot["path"] = str(override_path)
        override_snapshot["content"] = override_path.read_text(encoding="utf-8")
        assert kwargs["plan_role_arn"] == VALID_PLAN_ROLE
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    workflow.initialize_backend(
        binary="terraform",
        paths=paths,
        config=config,
        inputs=inputs,
    )

    override_path = Path(override_snapshot["path"])
    content = override_snapshot["content"]
    assert 'bucket = "clouddoc-123456789012-terraform-state"' in content
    assert "assume_role = {" in content
    assert f'role_arn     = "{VALID_STATE_ROLE}"' in content
    assert f'session_name = "{workflow.STATE_ROLE_SESSION_NAME}"' in content
    assert f'duration     = "{workflow.ROLE_SESSION_DURATION}"' in content
    assert f"-backend-config={config.backend_file}" in captured_arguments
    assert f"-backend-config={override_path}" in captured_arguments
    assert VALID_STATE_ROLE not in " ".join(captured_arguments)
    assert VALID_PLAN_ROLE not in " ".join(captured_arguments)
    assert not override_path.exists()
    assert VALID_STATE_ROLE not in capsys.readouterr().out


def test_initialize_backend_deletes_override_after_failed_init(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override cleanup must run even when initialization fails."""
    write_environment(paths)
    config = workflow.EnvironmentConfig.load(paths, "dev")
    inputs = workflow.RemoteInputs.load(remote_environment())
    override_path_holder: dict[str, Path] = {}

    def fake_run_terraform(**kwargs: Any) -> int:
        override_argument = next(
            argument
            for argument in kwargs["arguments"]
            if argument.startswith("-backend-config=")
            and argument.endswith(workflow.BACKEND_OVERRIDE_FILENAME)
        )
        override_path = Path(override_argument.removeprefix("-backend-config="))
        override_path_holder["path"] = override_path
        assert override_path.is_file()
        raise workflow.WorkflowError("Terraform init failed with exit code 1.")

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    with pytest.raises(workflow.WorkflowError, match="init failed"):
        workflow.initialize_backend(
            binary="terraform",
            paths=paths,
            config=config,
            inputs=inputs,
        )

    assert not override_path_holder["path"].exists()
    assert config.backend_file.is_file()


def test_initialize_backend_cleanup_failure_fails_operation(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup failure must fail the command."""
    write_environment(paths)
    config = workflow.EnvironmentConfig.load(paths, "dev")
    inputs = workflow.RemoteInputs.load(remote_environment())

    monkeypatch.setattr(
        workflow,
        "run_terraform",
        lambda **kwargs: 0,
    )

    def fail_cleanup(path: Path) -> None:
        del path
        raise workflow.WorkflowError(
            "Could not remove temporary backend override: backend-override.tfbackend"
        )

    monkeypatch.setattr(workflow, "remove_backend_override", fail_cleanup)

    with pytest.raises(
        workflow.WorkflowError,
        match="Could not remove temporary backend override",
    ):
        workflow.initialize_backend(
            binary="terraform",
            paths=paths,
            config=config,
            inputs=inputs,
        )


def test_resolve_plan_output_directory_defaults_to_artifacts(paths: Any) -> None:
    """Absent --output-directory preserves the current artifact location."""
    resolved = workflow.resolve_plan_output_directory(paths, "dev", None)

    assert resolved == paths.plan_dir("dev")


def test_resolve_plan_output_directory_accepts_absolute_external_path(
    tmp_path: Path,
    paths: Any,
) -> None:
    """Caller-supplied absolute directories outside the repository are accepted."""
    external = tmp_path / "external-plan-output"

    resolved = workflow.resolve_plan_output_directory(paths, "dev", external)

    assert resolved == external.resolve()
    assert resolved.is_dir()


def test_resolve_plan_output_directory_resolves_relative_path(
    tmp_path: Path,
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Relative output directories resolve deterministically from the process cwd."""
    monkeypatch.chdir(tmp_path)
    relative = Path("relative-plan-output")

    resolved = workflow.resolve_plan_output_directory(paths, "dev", relative)

    assert resolved == (tmp_path / "relative-plan-output").resolve()
    assert resolved.is_dir()


def test_resolve_plan_output_directory_rejects_existing_file(
    tmp_path: Path,
    paths: Any,
) -> None:
    """An output path that points to a regular file must be rejected."""
    target = tmp_path / "not-a-directory"
    target.write_text("file", encoding="utf-8")

    with pytest.raises(workflow.WorkflowError, match="regular file"):
        workflow.resolve_plan_output_directory(paths, "dev", target)


def test_command_plan_writes_artifacts_to_requested_output_directory(
    paths: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan artifacts must use the caller-supplied directory and current names."""
    write_environment(paths)
    write_valid_lambda_artifact(paths)
    output_directory = tmp_path / "caller-output"

    monkeypatch.setattr(
        workflow,
        "initialize_backend",
        lambda **kwargs: None,
    )

    def fake_run_terraform(**kwargs: Any) -> int:
        output_argument = next(
            argument for argument in kwargs["arguments"] if argument.startswith("-out=")
        )
        Path(output_argument.removeprefix("-out=")).write_bytes(b"generated-plan")
        return 2

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    workflow.command_plan(
        binary="terraform",
        paths=paths,
        environment="dev",
        environ=remote_environment(),
        output_directory=output_directory,
    )

    plan_file = output_directory / workflow.PLAN_FILENAME
    manifest_file = output_directory / workflow.MANIFEST_FILENAME
    assert plan_file.is_file()
    assert manifest_file.is_file()
    assert not paths.plan_file("dev").exists()
    assert set(output_directory.iterdir()) == {manifest_file, plan_file}

    manifest = workflow.PlanManifest.read(manifest_file)
    assert manifest.plan_file == str(plan_file.resolve())
    assert manifest.plan_sha256 == hashlib.sha256(b"generated-plan").hexdigest()


ATTESTATION_PATH = REPOSITORY_ROOT / "scripts" / "terraform_plan_attestation.py"
DEPLOY_REPOSITORY = "philgodoy96/clouddoc-ai-pipeline"
DEPLOY_PLAN_RUN_ID = "123456789"
DEPLOY_COMMIT_SHA = "a" * 40


def load_attestation_module() -> ModuleType:
    """Load the attestation module for deployment fixtures."""

    spec = importlib.util.spec_from_file_location(
        "clouddoc_terraform_plan_attestation_workflow_tests",
        ATTESTATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load attestation module: {ATTESTATION_PATH}")

    sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


plan_attestation = load_attestation_module()


def _plan_document(*resource_changes: object) -> dict[str, object]:
    return {
        "format_version": "1.2",
        "resource_changes": list(resource_changes),
    }


def _resource_change(
    address: str = "aws_s3_bucket.documents",
    *,
    actions: list[str] | None = None,
) -> dict[str, object]:
    return {
        "address": address,
        "mode": "managed",
        "type": "aws_s3_bucket",
        "name": "documents",
        "provider_name": "registry.terraform.io/hashicorp/aws",
        "change": {
            "actions": ["create"] if actions is None else actions,
            "replace_paths": [],
            "before": {"secret": "hidden"},
            "after": {"secret": "hidden"},
        },
    }


def build_attestation_fixture(document: dict[str, object]) -> Any:
    """Build one valid attestation using the repository module."""

    return plan_attestation.build_attestation(
        document,
        repository=DEPLOY_REPOSITORY,
        plan_run_id=DEPLOY_PLAN_RUN_ID,
        commit_sha=DEPLOY_COMMIT_SHA,
        environment="dev",
    )


def write_attestation_fixture(path: Path, document: dict[str, object]) -> Any:
    """Write one reviewed attestation fixture to disk."""

    built = build_attestation_fixture(document)
    plan_attestation.write_attestation(path, built)
    return built


TERRAFORM_VARIABLES_SOURCE = (
    REPOSITORY_ROOT / "infra" / "terraform" / "variables.tf"
).read_text(encoding="utf-8")
TERRAFORM_PROVIDERS_SOURCE = (
    REPOSITORY_ROOT / "infra" / "terraform" / "providers.tf"
).read_text(encoding="utf-8")


def test_terraform_apply_role_variable_contract() -> None:
    """Terraform root must expose nullable plan and apply provider role variables."""

    assert 'variable "terraform_apply_role_arn"' in TERRAFORM_VARIABLES_SOURCE
    assert 'variable "terraform_plan_role_arn"' in TERRAFORM_VARIABLES_SOURCE


def test_terraform_provider_role_selection_contract() -> None:
    """Provider must use one exclusive assume-role block and exact session names."""

    assert "effective_provider_role_arn" in TERRAFORM_PROVIDERS_SOURCE
    assert TERRAFORM_PROVIDERS_SOURCE.count('dynamic "assume_role"') == 1
    assert '"clouddoc-terraform-plan"' in TERRAFORM_PROVIDERS_SOURCE
    assert '"clouddoc-terraform-apply"' in TERRAFORM_PROVIDERS_SOURCE
    assert (
        "terraform_apply_role_arn and terraform_plan_role_arn cannot both be set"
        in TERRAFORM_VARIABLES_SOURCE
    )


@pytest.mark.parametrize(
    ("apply_role", "message"),
    [
        (
            f"arn:aws:iam::{OTHER_ACCOUNT_ID}:role/{workflow.APPLY_ROLE_NAME}",
            "account mismatch",
        ),
        (
            f"arn:aws:iam::{ACCOUNT_ID}:role/other-apply-role",
            "apply role",
        ),
        (
            f"arn:aws:iam::{ACCOUNT_ID}:role/path/{workflow.APPLY_ROLE_NAME}",
            "apply role",
        ),
        (
            (
                f"arn:aws:sts::{ACCOUNT_ID}:assumed-role/"
                f"{workflow.APPLY_ROLE_NAME}/session"
            ),
            "apply role",
        ),
        (f"arn:aws:iam::{ACCOUNT_ID}:role/{workflow.APPLY_ROLE_NAME} ", "apply role"),
    ],
)
def test_deploy_authorization_rejects_invalid_apply_roles(
    apply_role: str,
    message: str,
) -> None:
    """Apply-role ARNs must match the deployment contract."""

    environ = deploy_role_environment(apply_role=apply_role)

    with pytest.raises(workflow.WorkflowError, match=message):
        workflow.RemoteInputs.load(environ, authorization="deploy")


def test_deploy_authorization_rejects_empty_apply_role() -> None:
    """Empty apply-role values must be rejected."""

    environ = deploy_role_environment()
    environ[workflow.APPLY_ROLE_ENV] = ""

    with pytest.raises(workflow.WorkflowError, match="apply role"):
        workflow.RemoteInputs.load(environ, authorization="deploy")


def test_run_terraform_rejects_conflicting_apply_role_tf_var(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conflicting apply-role TF_VAR values must fail before Terraform."""

    monkeypatch.setenv(
        workflow.APPLY_ROLE_TF_VAR,
        f"arn:aws:iam::{ACCOUNT_ID}:role/other-apply-role",
    )

    with pytest.raises(workflow.WorkflowError, match="conflicting"):
        workflow.run_terraform(
            binary="terraform",
            root=paths.terraform_root,
            repository_root=paths.repository_root,
            data_dir=paths.data_dir("dev"),
            arguments=["validate"],
            expected_account_id=ACCOUNT_ID,
            apply_role_arn=VALID_APPLY_ROLE,
        )


@pytest.mark.parametrize(
    ("authorization", "environ", "message"),
    [
        (
            "plan",
            role_environment(
                apply_role=VALID_APPLY_ROLE, plan_role=None, state_role=None
            ),
            "apply role",
        ),
        ("deploy", role_environment(), "plan role"),
        (
            "deploy",
            role_environment(
                state_role=VALID_STATE_ROLE,
                plan_role=None,
                apply_role=None,
            ),
            "missing paired",
        ),
        (
            "deploy",
            deploy_role_environment(state_role=VALID_STATE_ROLE, apply_role=None),
            "missing paired",
        ),
        (
            "deploy",
            role_environment(
                plan_role=VALID_PLAN_ROLE,
                apply_role=VALID_APPLY_ROLE,
                state_role=VALID_STATE_ROLE,
            ),
            "conflicting",
        ),
        ("apply", deploy_role_environment(), "deploy command"),
    ],
)
def test_role_mode_matrix_rejects_invalid_combinations(
    authorization: str,
    environ: dict[str, str],
    message: str,
) -> None:
    """Plan, deploy, and apply commands must enforce distinct role modes."""

    with pytest.raises(workflow.WorkflowError, match=message):
        workflow.RemoteInputs.load(environ, authorization=authorization)


def test_plan_ambient_mode_succeeds() -> None:
    """Plan authorization accepts bucket and account only."""

    inputs = workflow.RemoteInputs.load(remote_environment(), authorization="plan")

    assert inputs.plan_role_arn is None
    assert inputs.apply_role_arn is None


def test_plan_chained_mode_requires_state_and_plan_only() -> None:
    """Chained plan mode requires paired state and plan roles."""

    inputs = workflow.RemoteInputs.load(role_environment(), authorization="plan")

    assert inputs.uses_chained_roles is True
    assert inputs.apply_role_arn is None


def test_deploy_ambient_mode_succeeds() -> None:
    """Deploy authorization accepts ambient configuration."""

    inputs = workflow.RemoteInputs.load(remote_environment(), authorization="deploy")

    assert inputs.apply_role_arn is None
    assert inputs.plan_role_arn is None


def test_deploy_chained_mode_requires_state_and_apply_only() -> None:
    """Chained deploy mode requires paired state and apply roles."""

    inputs = workflow.RemoteInputs.load(
        deploy_role_environment(),
        authorization="deploy",
    )

    assert inputs.uses_chained_deploy_roles is True
    assert inputs.plan_role_arn is None


def test_offline_check_does_not_require_roles(
    paths: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline check remains ambient and unchanged."""

    monkeypatch.setattr(workflow, "run_terraform", lambda **kwargs: 0)
    workflow.command_offline_check(binary="terraform", paths=paths)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"repository": "bad repo"}, "repository"),
        ({"plan_run_id": "0"}, "plan run"),
        ({"commit_sha": "ABC"}, "commit SHA"),
        ({"environment": "qa"}, "Unsupported environment"),
    ],
)
def test_deploy_argument_validation_rejects_invalid_metadata(
    paths: Any,
    tmp_path: Path,
    kwargs: dict[str, str],
    message: str,
) -> None:
    """Deploy metadata arguments must be validated before Terraform."""

    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(attestation, _plan_document())

    call_kwargs: dict[str, Any] = {
        "binary": "terraform",
        "paths": paths,
        "environment": "dev",
        "environ": remote_environment(),
        "attestation_path": attestation,
        "repository": DEPLOY_REPOSITORY,
        "plan_run_id": DEPLOY_PLAN_RUN_ID,
        "commit_sha": DEPLOY_COMMIT_SHA,
    }
    call_kwargs.update(kwargs)

    with pytest.raises(workflow.WorkflowError, match=message):
        workflow.command_deploy(**call_kwargs)


def test_deploy_rejects_missing_attestation_argument(paths: Any) -> None:
    """Deploy requires an attestation file path."""

    with pytest.raises(workflow.WorkflowError, match="regular file"):
        workflow.command_deploy(
            binary="terraform",
            paths=paths,
            environment="dev",
            environ=remote_environment(),
            attestation_path=Path("missing-attestation.json"),
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
        )


def test_deploy_rejects_attestation_directory(
    paths: Any,
    tmp_path: Path,
) -> None:
    """Attestation paths must not be directories."""

    directory = tmp_path / "attestation-dir"
    directory.mkdir()

    with pytest.raises(workflow.WorkflowError, match="regular file"):
        workflow.command_deploy(
            binary="terraform",
            paths=paths,
            environment="dev",
            environ=remote_environment(),
            attestation_path=directory,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
        )


def test_deploy_rejects_output_directory_traversal(paths: Any) -> None:
    """Output directories must not traverse parents."""

    with pytest.raises(workflow.WorkflowError, match="traversal"):
        workflow.resolve_plan_output_directory(paths, "dev", "../escape-output")


def test_deploy_validates_attestation_before_terraform(
    paths: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid attestation must pass before any Terraform subprocess."""

    write_environment(paths)
    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(attestation, _plan_document())
    called = False

    def fail_if_called(**kwargs: Any) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(workflow, "initialize_backend", fail_if_called)

    with pytest.raises(workflow.WorkflowError, match="Lambda artifact"):
        workflow.command_deploy(
            binary="terraform",
            paths=paths,
            environment="dev",
            environ=remote_environment(),
            attestation_path=attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
        )

    assert called is False


def test_deploy_context_mismatch_fails_before_subprocess(
    paths: Any,
    tmp_path: Path,
) -> None:
    """Attestation context mismatches must fail before Terraform."""

    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(attestation, _plan_document())

    with pytest.raises(workflow.WorkflowError, match="context"):
        workflow.load_reviewed_attestation(
            attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id="987654321",
            commit_sha=DEPLOY_COMMIT_SHA,
            environment="dev",
            allow_destructive_changes=False,
        )


def test_deploy_tampered_fingerprint_fails_before_subprocess(
    tmp_path: Path,
) -> None:
    """Tampered attestations must fail before Terraform."""

    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(attestation, _plan_document())
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["change_set_fingerprint"] = "f" * 64
    attestation.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(workflow.WorkflowError, match="fingerprint"):
        workflow.load_reviewed_attestation(
            attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            environment="dev",
            allow_destructive_changes=False,
        )


def test_deploy_unknown_attestation_field_fails_before_subprocess(
    tmp_path: Path,
) -> None:
    """Unknown attestation fields must fail before Terraform."""

    attestation = tmp_path / "attestation.json"
    built = build_attestation_fixture(_plan_document())
    payload = built.to_mapping()
    payload["unexpected"] = True
    attestation.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(workflow.WorkflowError):
        workflow.load_reviewed_attestation(
            attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            environment="dev",
            allow_destructive_changes=False,
        )


def test_deploy_destructive_attestation_requires_opt_in(tmp_path: Path) -> None:
    """Destructive attestations require explicit authorization."""

    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(
        attestation,
        _plan_document(_resource_change(actions=["delete"])),
    )

    with pytest.raises(workflow.WorkflowError, match="Destructive changes"):
        workflow.load_reviewed_attestation(
            attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            environment="dev",
            allow_destructive_changes=False,
        )


def test_deploy_failure_output_does_not_leak_sensitive_values(
    tmp_path: Path,
) -> None:
    """Attestation failures must not echo resource addresses or sentinel values."""

    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(
        attestation,
        _plan_document(_resource_change(address="aws_s3_bucket.secret-bucket")),
    )
    payload = json.loads(attestation.read_text(encoding="utf-8"))
    payload["change_set_fingerprint"] = "f" * 64
    attestation.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(workflow.WorkflowError) as raised:
        workflow.load_reviewed_attestation(
            attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            environment="dev",
            allow_destructive_changes=False,
        )

    error_text = str(raised.value)
    assert "aws_s3_bucket.secret-bucket" not in error_text
    assert "hidden" not in error_text


@pytest.fixture
def deploy_harness(
    paths: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Prepare one deploy harness with mocked Terraform phases."""

    write_environment(paths)
    write_valid_lambda_artifact(paths)
    attestation = tmp_path / "reviewed-attestation.json"
    write_attestation_fixture(attestation, _plan_document(_resource_change()))
    output_directory = tmp_path / "deploy-output"
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(workflow, "initialize_backend", lambda **kwargs: None)

    def fake_show_json(**kwargs: Any) -> None:
        kwargs["output_path"].write_text(
            json.dumps(_plan_document(_resource_change())),
            encoding="utf-8",
        )
        calls.append({"phase": "show"})

    monkeypatch.setattr(workflow, "run_terraform_show_json", fake_show_json)

    def fake_run_terraform(**kwargs: Any) -> int:
        arguments = list(kwargs["arguments"])
        phase = arguments[0]
        if phase == "plan":
            output_argument = next(
                argument for argument in arguments if argument.startswith("-out=")
            )
            Path(output_argument.removeprefix("-out=")).write_bytes(b"deploy-plan")
            if output_argument.endswith(workflow.POST_APPLY_PLAN_FILENAME):
                return 0
            return 2
        if phase == "apply":
            calls.append({"phase": "apply", "arguments": arguments})
            return 0
        calls.append({"phase": phase, "arguments": arguments})
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    return {
        "paths": paths,
        "attestation": attestation,
        "output_directory": output_directory,
        "calls": calls,
    }


def test_deploy_plan_uses_apply_role_provider_env(
    deploy_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regenerated plans must publish the apply provider role."""

    captured: list[dict[str, Any]] = []

    def capture_run(**kwargs: Any) -> int:
        captured.append(kwargs)
        arguments = kwargs["arguments"]
        if arguments[0] == "plan":
            output_argument = next(
                argument for argument in arguments if argument.startswith("-out=")
            )
            Path(output_argument.removeprefix("-out=")).write_bytes(b"deploy-plan")
            if output_argument.endswith(workflow.POST_APPLY_PLAN_FILENAME):
                return 0
            return 2
        if arguments[0] == "apply":
            return 0
        return 0

    monkeypatch.setattr(workflow, "run_terraform", capture_run)
    monkeypatch.setattr(
        workflow,
        "run_terraform_show_json",
        lambda **kwargs: kwargs["output_path"].write_text(
            json.dumps(_plan_document(_resource_change())),
            encoding="utf-8",
        ),
    )

    workflow.command_deploy(
        binary="terraform",
        paths=deploy_harness["paths"],
        environment="dev",
        environ=deploy_role_environment(),
        attestation_path=deploy_harness["attestation"],
        repository=DEPLOY_REPOSITORY,
        plan_run_id=DEPLOY_PLAN_RUN_ID,
        commit_sha=DEPLOY_COMMIT_SHA,
        output_directory=deploy_harness["output_directory"],
    )

    plan_calls = [call for call in captured if call["arguments"][0] == "plan"]
    assert plan_calls[0]["apply_role_arn"] == VALID_APPLY_ROLE
    assert plan_calls[0]["plan_role_arn"] is None


def test_deploy_lifecycle_applies_exact_regenerated_plan(
    deploy_harness: dict[str, Any],
) -> None:
    """Deploy must apply only the regenerated plan file."""

    workflow.command_deploy(
        binary="terraform",
        paths=deploy_harness["paths"],
        environment="dev",
        environ=remote_environment(),
        attestation_path=deploy_harness["attestation"],
        repository=DEPLOY_REPOSITORY,
        plan_run_id=DEPLOY_PLAN_RUN_ID,
        commit_sha=DEPLOY_COMMIT_SHA,
        output_directory=deploy_harness["output_directory"],
    )

    apply_calls = [
        call for call in deploy_harness["calls"] if call.get("phase") == "apply"
    ]
    assert len(apply_calls) == 1
    regenerated_plan = (
        deploy_harness["output_directory"] / workflow.DEPLOY_PLAN_FILENAME
    ).as_posix()
    assert apply_calls[0]["arguments"][-1] == regenerated_plan


def test_deploy_noop_skips_apply_and_convergence(
    paths: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching no-op attestations must not run apply or convergence plans."""

    write_environment(paths)
    write_valid_lambda_artifact(paths)
    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(attestation, _plan_document())
    output_directory = tmp_path / "deploy-output"
    calls: list[str] = []

    monkeypatch.setattr(workflow, "initialize_backend", lambda **kwargs: None)
    monkeypatch.setattr(
        workflow,
        "run_terraform_show_json",
        lambda **kwargs: kwargs["output_path"].write_text(
            json.dumps(_plan_document()),
            encoding="utf-8",
        ),
    )

    def fake_run_terraform(**kwargs: Any) -> int:
        calls.append(kwargs["arguments"][0])
        if kwargs["arguments"][0] == "plan":
            output_argument = next(
                argument
                for argument in kwargs["arguments"]
                if argument.startswith("-out=")
            )
            Path(output_argument.removeprefix("-out=")).write_bytes(b"deploy-plan")
            return 0
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    workflow.command_deploy(
        binary="terraform",
        paths=paths,
        environment="dev",
        environ=remote_environment(),
        attestation_path=attestation,
        repository=DEPLOY_REPOSITORY,
        plan_run_id=DEPLOY_PLAN_RUN_ID,
        commit_sha=DEPLOY_COMMIT_SHA,
        output_directory=output_directory,
    )

    assert calls == ["plan"]


def test_deploy_fingerprint_mismatch_fails_before_apply(
    paths: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fingerprint mismatches must fail before apply."""

    write_environment(paths)
    write_valid_lambda_artifact(paths)
    attestation = tmp_path / "attestation.json"
    write_attestation_fixture(attestation, _plan_document())
    output_directory = tmp_path / "deploy-output"
    apply_called = False

    monkeypatch.setattr(workflow, "initialize_backend", lambda **kwargs: None)
    monkeypatch.setattr(
        workflow,
        "run_terraform_show_json",
        lambda **kwargs: kwargs["output_path"].write_text(
            json.dumps(_plan_document(_resource_change(actions=["update"]))),
            encoding="utf-8",
        ),
    )

    def fake_run_terraform(**kwargs: Any) -> int:
        nonlocal apply_called
        if kwargs["arguments"][0] == "apply":
            apply_called = True
        if kwargs["arguments"][0] == "plan":
            output_argument = next(
                argument
                for argument in kwargs["arguments"]
                if argument.startswith("-out=")
            )
            Path(output_argument.removeprefix("-out=")).write_bytes(b"deploy-plan")
            return 2
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    with pytest.raises(workflow.WorkflowError, match="mismatch"):
        workflow.command_deploy(
            binary="terraform",
            paths=paths,
            environment="dev",
            environ=remote_environment(),
            attestation_path=attestation,
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            output_directory=output_directory,
        )

    assert apply_called is False


def test_deploy_nonzero_apply_propagates_partial_apply_warning(
    deploy_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nonzero apply failures must explain possible partial apply."""

    def failing_apply(**kwargs: Any) -> int:
        if kwargs["arguments"][0] == "apply":
            raise workflow.WorkflowError("Terraform apply failed with exit code 1.")
        output_argument = next(
            argument for argument in kwargs["arguments"] if argument.startswith("-out=")
        )
        Path(output_argument.removeprefix("-out=")).write_bytes(b"deploy-plan")
        return 2

    monkeypatch.setattr(workflow, "run_terraform", failing_apply)

    with pytest.raises(workflow.WorkflowError, match="partially changed"):
        workflow.command_deploy(
            binary="terraform",
            paths=deploy_harness["paths"],
            environment="dev",
            environ=remote_environment(),
            attestation_path=deploy_harness["attestation"],
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            output_directory=deploy_harness["output_directory"],
        )


def test_deploy_convergence_exit_two_fails(
    deploy_harness: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Convergence exit code 2 must fail without a second apply."""

    apply_count = 0

    def fake_run_terraform(**kwargs: Any) -> int:
        nonlocal apply_count
        arguments = kwargs["arguments"]
        if arguments[0] == "apply":
            apply_count += 1
            return 0
        if arguments[0] == "plan":
            output_argument = next(
                argument for argument in arguments if argument.startswith("-out=")
            )
            Path(output_argument.removeprefix("-out=")).write_bytes(b"deploy-plan")
            if output_argument.endswith(workflow.POST_APPLY_PLAN_FILENAME):
                return 2
            return 2
        return 0

    monkeypatch.setattr(workflow, "run_terraform", fake_run_terraform)

    with pytest.raises(workflow.WorkflowError, match="convergence"):
        workflow.command_deploy(
            binary="terraform",
            paths=deploy_harness["paths"],
            environment="dev",
            environ=remote_environment(),
            attestation_path=deploy_harness["attestation"],
            repository=DEPLOY_REPOSITORY,
            plan_run_id=DEPLOY_PLAN_RUN_ID,
            commit_sha=DEPLOY_COMMIT_SHA,
            output_directory=deploy_harness["output_directory"],
        )

    assert apply_count == 1


def test_local_apply_rejects_attestation_paths(tmp_path: Path) -> None:
    """Local apply must reject attestation and directory inputs."""

    forbidden = tmp_path / "terraform-plan-attestation.json"
    forbidden.write_text("{}", encoding="utf-8")

    with pytest.raises(workflow.WorkflowError, match="valid Terraform plan"):
        workflow.validate_local_apply_plan_path(forbidden)

    directory = tmp_path / "plan-directory"
    directory.mkdir()
    with pytest.raises(workflow.WorkflowError, match="regular file"):
        workflow.validate_local_apply_plan_path(directory)
