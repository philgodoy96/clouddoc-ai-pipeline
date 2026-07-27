"""Static contracts for CloudDoc GitHub Actions workflows."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GITHUB_ROOT = REPOSITORY_ROOT / ".github"
WORKFLOWS_ROOT = GITHUB_ROOT / "workflows"

PYTHON_WORKFLOW = WORKFLOWS_ROOT / "python-quality.yml"
INFRASTRUCTURE_WORKFLOW = WORKFLOWS_ROOT / "infrastructure-quality.yml"
AWS_IDENTITY_WORKFLOW = WORKFLOWS_ROOT / "aws-identity-check.yml"
REUSABLE_AWS_IDENTITY_WORKFLOW = WORKFLOWS_ROOT / "reusable-aws-identity.yml"
DEPENDABOT_CONFIG = GITHUB_ROOT / "dependabot.yml"

VALIDATION_WORKFLOWS = (PYTHON_WORKFLOW, INFRASTRUCTURE_WORKFLOW)
IDENTITY_WORKFLOWS = (
    AWS_IDENTITY_WORKFLOW,
    REUSABLE_AWS_IDENTITY_WORKFLOW,
)

LOCAL_REUSABLE_WORKFLOW_USES = "uses: ./.github/workflows/reusable-aws-identity.yml"

EXPECTED_ACTIONS = {
    "actions/checkout": (
        "3d3c42e5aac5ba805825da76410c181273ba90b1",
        "v7.0.1",
    ),
    "actions/setup-python": (
        "5fda3b95a4ea91299a34e894583c3862153e4b97",
        "v7.0.0",
    ),
    "hashicorp/setup-terraform": (
        "dfe3c3f87815947d99a8997f908cb6525fc44e9e",
        "v4.0.1",
    ),
    "aws-actions/configure-aws-credentials": (
        "e6de054238d6b7531b4efff3b6587d9aade6a06c",
        "v6.2.3",
    ),
}
EXPECTED_ACTION_COUNTS = {
    "actions/checkout": 3,
    "actions/setup-python": 3,
    "hashicorp/setup-terraform": 1,
    "aws-actions/configure-aws-credentials": 1,
}

ACTION_REFERENCE_PATTERN = re.compile(
    r"^\s*uses:\s+"
    r"(?P<action>[^@\s]+)@"
    r"(?P<reference>[^\s#]+)"
    r"(?:\s+#\s+(?P<comment>\S+))?"
    r"\s*$",
    flags=re.MULTILINE,
)
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def read_text(path: Path) -> str:
    """Read one committed UTF-8 configuration file."""
    return path.read_text(encoding="utf-8")


def workflow_sources() -> dict[Path, str]:
    """Return every committed GitHub Actions workflow source."""
    return {path: read_text(path) for path in sorted(WORKFLOWS_ROOT.glob("*.yml"))}


def extract_top_level_block(source: str, key: str) -> str:
    """Extract one YAML top-level key and its indented body."""
    pattern = re.compile(
        rf"^{re.escape(key)}:\s*\n"
        r"(?P<body>.*?)(?=^[A-Za-z0-9_-]+:\s*(?:\n|$)|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(source)

    if match is None:
        raise AssertionError(f"Top-level block not found: {key}")

    return match.group(0)


def extract_job_block(source: str, job_id: str) -> str:
    """Extract one job from a workflow jobs block."""
    pattern = re.compile(
        rf"^  {re.escape(job_id)}:\s*\n"
        r"(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\s*\n|\Z)",
        flags=re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(source)

    if match is None:
        raise AssertionError(f"Job block not found: {job_id}")

    return match.group(0)


def action_references(source: str) -> list[tuple[str, str, str | None]]:
    """Return action name, reference, and version comment tuples."""
    return [
        (
            match.group("action"),
            match.group("reference"),
            match.group("comment"),
        )
        for match in ACTION_REFERENCE_PATTERN.finditer(source)
    ]


def test_expected_ci_configuration_files_exist() -> None:
    """The repository must contain both workflows and Dependabot policy."""
    assert PYTHON_WORKFLOW.is_file()
    assert INFRASTRUCTURE_WORKFLOW.is_file()
    assert AWS_IDENTITY_WORKFLOW.is_file()
    assert REUSABLE_AWS_IDENTITY_WORKFLOW.is_file()
    assert DEPENDABOT_CONFIG.is_file()


@pytest.mark.parametrize(
    ("path", "expected_name"),
    [
        (PYTHON_WORKFLOW, "Python Quality"),
        (INFRASTRUCTURE_WORKFLOW, "Infrastructure Quality"),
        (AWS_IDENTITY_WORKFLOW, "AWS Identity Check"),
        (REUSABLE_AWS_IDENTITY_WORKFLOW, "Reusable AWS Identity"),
    ],
)
def test_workflow_names_are_stable(
    path: Path,
    expected_name: str,
) -> None:
    """Required-check workflow names must remain predictable."""
    source = read_text(path)

    assert source.startswith(f"name: {expected_name}\n")


@pytest.mark.parametrize(
    "path",
    [PYTHON_WORKFLOW, INFRASTRUCTURE_WORKFLOW],
)
def test_workflows_use_the_approved_triggers(path: Path) -> None:
    """Validation runs for pull requests, main pushes, and manual checks."""
    triggers = extract_top_level_block(read_text(path), "on")

    assert "pull_request:" in triggers
    assert "push:" in triggers
    assert "workflow_dispatch:" in triggers
    assert triggers.count("- main") == 2
    assert "pull_request_target:" not in triggers


def test_aws_identity_caller_is_manual_only() -> None:
    """Identity verification must start only from an explicit manual run."""
    triggers = extract_top_level_block(
        read_text(AWS_IDENTITY_WORKFLOW),
        "on",
    )

    assert "workflow_dispatch:" in triggers
    assert "pull_request:" not in triggers
    assert "pull_request_target:" not in triggers
    assert "push:" not in triggers
    assert "schedule:" not in triggers
    assert "workflow_run:" not in triggers
    assert "workflow_call:" not in triggers


def test_reusable_aws_identity_uses_workflow_call_only() -> None:
    """The reusable identity workflow must be callable and never standalone."""
    triggers = extract_top_level_block(
        read_text(REUSABLE_AWS_IDENTITY_WORKFLOW),
        "on",
    )

    assert "workflow_call:" in triggers
    assert "workflow_dispatch:" not in triggers
    assert "pull_request:" not in triggers
    assert "pull_request_target:" not in triggers
    assert "push:" not in triggers
    assert "schedule:" not in triggers
    assert "workflow_run:" not in triggers


@pytest.mark.parametrize(
    "path",
    [
        PYTHON_WORKFLOW,
        INFRASTRUCTURE_WORKFLOW,
        AWS_IDENTITY_WORKFLOW,
        REUSABLE_AWS_IDENTITY_WORKFLOW,
    ],
)
def test_workflows_do_not_use_path_filters(path: Path) -> None:
    """Required checks must not disappear because a path filter skipped them."""
    triggers = extract_top_level_block(read_text(path), "on")

    assert "paths:" not in triggers
    assert "paths-ignore:" not in triggers


@pytest.mark.parametrize(
    "path",
    [PYTHON_WORKFLOW, INFRASTRUCTURE_WORKFLOW],
)
def test_validation_workflows_have_read_only_permissions(path: Path) -> None:
    """Validation workflows require repository read access only."""
    permissions = extract_top_level_block(
        read_text(path),
        "permissions",
    )

    assert permissions.strip() == "permissions:\n  contents: read"


@pytest.mark.parametrize(
    "path",
    [AWS_IDENTITY_WORKFLOW, REUSABLE_AWS_IDENTITY_WORKFLOW],
)
def test_identity_workflows_have_exact_oidc_permissions(path: Path) -> None:
    """Identity workflows may request OIDC write plus repository read only."""
    permissions = extract_top_level_block(
        read_text(path),
        "permissions",
    )

    assert permissions.strip() == ("permissions:\n  contents: read\n  id-token: write")


@pytest.mark.parametrize(
    "path",
    [PYTHON_WORKFLOW, INFRASTRUCTURE_WORKFLOW],
)
def test_workflows_cancel_obsolete_branch_runs(path: Path) -> None:
    """A newer branch revision should cancel obsolete validation."""
    concurrency = extract_top_level_block(
        read_text(path),
        "concurrency",
    )

    assert "${{ github.workflow }}" in concurrency
    assert "${{ github.ref }}" in concurrency
    assert "cancel-in-progress: true" in concurrency


def test_aws_identity_caller_uses_non_cancelling_concurrency() -> None:
    """Manual identity verification must keep the active run for a ref."""
    concurrency = extract_top_level_block(
        read_text(AWS_IDENTITY_WORKFLOW),
        "concurrency",
    )

    assert concurrency.strip() == (
        "concurrency:\n"
        "  group: aws-identity-check-${{ github.ref }}\n"
        "  cancel-in-progress: false"
    )


def test_python_quality_check_name_and_timeout_are_stable() -> None:
    """Branch protection can depend on the established Python check name."""
    job = extract_job_block(read_text(PYTHON_WORKFLOW), "quality")

    assert "name: Format, lint, and test" in job
    assert "runs-on: ubuntu-latest" in job
    assert "timeout-minutes: 10" in job


def test_infrastructure_check_names_and_timeouts_are_stable() -> None:
    """Branch protection can depend on both infrastructure check names."""
    source = read_text(INFRASTRUCTURE_WORKFLOW)
    lambda_job = extract_job_block(source, "lambda-package")
    terraform_job = extract_job_block(source, "terraform-offline")

    assert "name: Lambda package" in lambda_job
    assert "name: Terraform offline" in terraform_job
    assert "runs-on: ubuntu-latest" in lambda_job
    assert "runs-on: ubuntu-latest" in terraform_job
    assert "timeout-minutes: 15" in lambda_job
    assert "timeout-minutes: 15" in terraform_job


def test_aws_identity_check_names_are_stable() -> None:
    """Identity check names must remain predictable for operators."""
    caller = extract_job_block(
        read_text(AWS_IDENTITY_WORKFLOW),
        "verify-aws-identity",
    )
    reusable = extract_job_block(
        read_text(REUSABLE_AWS_IDENTITY_WORKFLOW),
        "verify-identity",
    )

    assert "name: Verify AWS identity" in caller
    assert "name: Assume permissionless role" in reusable
    assert "runs-on: ubuntu-latest" in reusable
    assert "timeout-minutes: 5" in reusable
    assert "environment: dev" in reusable


def test_infrastructure_jobs_are_independent() -> None:
    """Terraform validation must start from its own clean checkout."""
    source = read_text(INFRASTRUCTURE_WORKFLOW)

    assert "needs:" not in source
    assert source.count("name: Check out repository") == 2


def test_every_external_action_uses_an_approved_full_sha() -> None:
    """No workflow may execute an action through a mutable reference."""
    references = [
        reference
        for source in workflow_sources().values()
        for reference in action_references(source)
    ]

    assert len(references) == 8

    for action, reference, comment in references:
        assert action in EXPECTED_ACTIONS
        assert FULL_SHA_PATTERN.fullmatch(reference)

        expected_reference, expected_comment = EXPECTED_ACTIONS[action]
        assert reference == expected_reference
        assert comment == expected_comment


def test_action_reference_counts_match_the_reviewed_workflows() -> None:
    """The workflow action surface should remain intentionally small."""
    counts = Counter(
        action
        for source in workflow_sources().values()
        for action, _, _ in action_references(source)
    )

    assert counts == Counter(EXPECTED_ACTION_COUNTS)


def test_no_mutable_action_reference_remains() -> None:
    """Major tags, branches, and short SHAs are forbidden."""
    for path, source in workflow_sources().items():
        action_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith("uses:")
        ]

        assert action_lines, f"No action references found in {path}"

        for line in action_lines:
            if line == LOCAL_REUSABLE_WORKFLOW_USES:
                continue

            match = ACTION_REFERENCE_PATTERN.fullmatch(line)
            assert match is not None, f"Unrecognized action reference in {path}: {line}"
            assert FULL_SHA_PATTERN.fullmatch(match.group("reference"))
            assert not line.startswith("uses: ./"), (
                f"Unapproved local workflow path in {path}: {line}"
            )


def test_every_checkout_disables_persisted_credentials() -> None:
    """Read-only workflows must not retain a writable Git credential."""
    sources = workflow_sources()
    combined = "\n".join(sources.values())

    assert combined.count("actions/checkout@") == 3
    assert combined.count("persist-credentials: false") == 3


@pytest.mark.parametrize(
    "path",
    [AWS_IDENTITY_WORKFLOW, REUSABLE_AWS_IDENTITY_WORKFLOW],
)
def test_identity_workflows_do_not_check_out_the_repository(
    path: Path,
) -> None:
    """Identity verification must never clone repository contents."""
    source = read_text(path)

    assert "actions/checkout" not in source
    assert "name: Check out repository" not in source


def test_python_quality_behavior_remains_intact() -> None:
    """Action hardening must not replace the existing Python checks."""
    source = read_text(PYTHON_WORKFLOW)

    required_fragments = (
        'python-version: "3.12"',
        "cache: pip",
        "cache-dependency-path: pyproject.toml",
        "python -m pip install --upgrade pip",
        'python -m pip install -e ".[dev]"',
        "python -m ruff format . --check",
        "python -m ruff check .",
        "python -m pytest",
    )

    for fragment in required_fragments:
        assert fragment in source


def test_lambda_job_uses_python_312_and_runtime_cache_inputs() -> None:
    """Packaging must use the Lambda runtime Python contract."""
    job = extract_job_block(
        read_text(INFRASTRUCTURE_WORKFLOW),
        "lambda-package",
    )

    assert 'python-version: "3.12"' in job
    assert "cache: pip" in job
    assert "pyproject.toml" in job
    assert "requirements/lambda.lock.txt" in job
    assert "python -m pip install -e ." in job


def test_lambda_job_proves_two_clean_builds_are_reproducible() -> None:
    """One successful build is insufficient for deterministic packaging."""
    job = extract_job_block(
        read_text(INFRASTRUCTURE_WORKFLOW),
        "lambda-package",
    )

    assert job.count("make lambda-package-check") == 2
    assert job.count("make lambda-clean") == 1
    assert "first_digest=" in job
    assert "second_digest=" in job
    assert 'if [[ "$first_digest" != "$second_digest" ]]' in job
    assert "Lambda package is not reproducible." in job
    assert "exit 1" in job


def test_lambda_job_does_not_publish_generated_artifacts() -> None:
    """This workflow validates artifacts but does not promote them."""
    job = extract_job_block(
        read_text(INFRASTRUCTURE_WORKFLOW),
        "lambda-package",
    )

    assert "actions/upload-artifact" not in job
    assert "gh release" not in job
    assert "aws s3" not in job


def test_terraform_job_uses_the_exact_reviewed_cli_contract() -> None:
    """Terraform CI behavior must remain reproducible and wrapper-free."""
    job = extract_job_block(
        read_text(INFRASTRUCTURE_WORKFLOW),
        "terraform-offline",
    )

    assert 'python-version: "3.12"' in job
    assert 'terraform_version: "1.15.8"' in job
    assert "terraform_wrapper: false" in job
    assert "run: python scripts/terraform_workflow.py offline-check" in job


def test_terraform_job_does_not_build_or_consume_lambda_artifacts() -> None:
    """Terraform offline runs from a clean checkout without generated ZIPs."""
    job = extract_job_block(
        read_text(INFRASTRUCTURE_WORKFLOW),
        "terraform-offline",
    )

    assert "lambda-package-check" not in job
    assert "artifacts/lambda" not in job
    assert "upload-artifact" not in job
    assert "download-artifact" not in job


def test_validation_workflows_contain_no_authenticated_aws_inputs() -> None:
    """Validation must remain independent from AWS identity and state."""
    combined = "\n".join(read_text(path) for path in VALIDATION_WORKFLOWS)

    forbidden = (
        "secrets.",
        "vars.",
        "AWS_",
        "CLOUDDOC_TERRAFORM_STATE_BUCKET",
        "CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID",
        "TF_VAR_expected_aws_account_id",
        "id-token:",
        "aws-actions/",
        "environment:",
    )

    for value in forbidden:
        assert value not in combined


def test_aws_identity_caller_delegates_to_the_reusable_workflow() -> None:
    """The caller must only pass reviewed variables into the reusable job."""
    source = read_text(AWS_IDENTITY_WORKFLOW)
    job = extract_job_block(source, "verify-aws-identity")

    assert LOCAL_REUSABLE_WORKFLOW_USES in job
    assert "aws_account_id: ${{ vars.CLOUDDOC_AWS_ACCOUNT_ID }}" in job
    assert "aws_region: us-east-1" in job
    assert "role_arn: ${{ vars.CLOUDDOC_DEV_IDENTITY_ROLE_ARN }}" in job
    assert ("permissions:\n      contents: read\n      id-token: write") in job

    forbidden = (
        "secrets.",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "environment:",
        "runs-on:",
        "steps:",
    )

    for value in forbidden:
        assert value not in job


def test_reusable_aws_identity_declares_exact_workflow_call_inputs() -> None:
    """The reusable workflow accepts only the three reviewed string inputs."""
    triggers = extract_top_level_block(
        read_text(REUSABLE_AWS_IDENTITY_WORKFLOW),
        "on",
    )

    for input_name in ("aws_account_id", "aws_region", "role_arn"):
        assert f"{input_name}:" in triggers

    assert triggers.count("required: true") == 3
    assert triggers.count("type: string") == 3
    assert "secrets:" not in triggers


def test_reusable_aws_identity_validates_trusted_context() -> None:
    """Preflight must reject unexpected repository, ref, event, and role."""
    source = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)

    assert "set -euo pipefail" in source
    assert "GITHUB_REPOSITORY" in source
    assert "philgodoy96/clouddoc-ai-pipeline" in source
    assert "GITHUB_REF" in source
    assert "refs/heads/main" in source
    assert "GITHUB_EVENT_NAME" in source
    assert "workflow_dispatch" in source
    assert r"^[0-9]{12}$" in source
    assert (
        "arn:aws:iam::${EXPECTED_ACCOUNT_ID}:role/clouddoc-dev-github-identity"
    ) in source
    assert "us-east-1" in source


def test_reusable_aws_identity_configures_credentials_exactly() -> None:
    """OIDC assumption must use the pinned action and reviewed inputs."""
    source = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)

    assert (
        "uses: aws-actions/configure-aws-credentials@"
        "e6de054238d6b7531b4efff3b6587d9aade6a06c # v6.2.3"
    ) in source
    assert "role-to-assume: ${{ inputs.role_arn }}" in source
    assert "aws-region: ${{ inputs.aws_region }}" in source
    assert "allowed-account-ids: ${{ inputs.aws_account_id }}" in source
    assert "role-duration-seconds: 900" in source
    assert ("role-session-name: clouddoc-identity-${{ github.run_id }}") in source
    assert "mask-aws-account-id: true" in source
    assert "unset-current-credentials: true" in source

    forbidden = (
        "aws-access-key-id",
        "aws-secret-access-key",
        "aws-session-token",
        "role-chaining",
        "inline-session-policy",
        "managed-session-policies",
        "force-skip-oidc",
        "use-existing-credentials",
    )

    for value in forbidden:
        assert value not in source


def test_reusable_aws_identity_validates_oidc_claims_before_credentials() -> None:
    """OIDC claim preflight must sit between context checks and AWS auth."""
    source = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)
    context_step = "name: Validate trusted workflow context"
    oidc_step = "name: Validate GitHub OIDC token claims"
    credentials_step = "name: Configure temporary AWS credentials"
    identity_step = "name: Verify assumed AWS identity"

    assert source.count(oidc_step) == 1
    assert source.index(context_step) < source.index(oidc_step)
    assert source.index(oidc_step) < source.index(credentials_step)
    assert source.index(credentials_step) < source.index(identity_step)


def test_reusable_aws_identity_oidc_preflight_requests_token_safely() -> None:
    """The OIDC preflight must request and decode the token only in memory."""
    source = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)

    required = (
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "audience",
        "sts.amazonaws.com",
        "Authorization",
        "Bearer",
        "application/json",
        "urllib.request",
        "urllib.parse",
        "hmac.compare_digest",
        "GitHub OIDC token claim contract verified.",
    )

    for value in required:
        assert value in source

    forbidden = (
        "actions-oidc-debugger",
        "actions/github-script",
        "npm install",
        "pip install",
        "continue-on-error",
        "GITHUB_OUTPUT",
        "GITHUB_ENV",
        "echo $ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "echo $ACTIONS_ID_TOKEN_REQUEST_URL",
        "print(jwt",
        "print(token",
        "job_workflow_sha",
    )

    for value in forbidden:
        assert value not in source


def test_reusable_aws_identity_oidc_preflight_enforces_eight_claim_contract() -> None:
    """Preflight must compare the exact eight-claim AWS trust contract."""
    source = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)

    claim_names = (
        "aud",
        "sub",
        "repository",
        "repository_id",
        "repository_owner_id",
        "ref",
        "environment",
        "job_workflow_ref",
    )

    for claim_name in claim_names:
        assert f'"{claim_name}":' in source

    assert (
        "CANONICAL_JOB_WORKFLOW_REF: philgodoy96/clouddoc-ai-pipeline/"
        ".github/workflows/reusable-aws-identity.yml@refs/heads/main"
    ) in source
    assert "EXPECTED_JOB_WORKFLOW_REF: ${{ job.workflow_ref }}" in source
    assert "EXPECTED_REPOSITORY: ${{ github.repository }}" in source
    assert "EXPECTED_REPOSITORY_ID: ${{ github.repository_id }}" in source
    assert "EXPECTED_REPOSITORY_OWNER: ${{ github.repository_owner }}" in source
    assert ("EXPECTED_REPOSITORY_OWNER_ID: ${{ github.repository_owner_id }}") in source
    assert "EXPECTED_REF: ${{ github.ref }}" in source
    assert "EXPECTED_ENVIRONMENT: dev" in source
    assert "EXPECTED_AUDIENCE: sts.amazonaws.com" in source
    assert (
        'f"repo:{expected_repository_owner}@{expected_repository_owner_id}/"' in source
    )
    assert 'f"{repository_name}@{expected_repository_id}"' in source
    assert 'f":environment:{expected_environment}"' in source
    assert "repo:" in source
    assert ":environment:" in source
    assert "job_workflow_sha" not in source


def test_reusable_aws_identity_proves_the_assumed_role() -> None:
    """The reusable workflow must prove the temporary session identity."""
    source = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)

    assert "aws sts get-caller-identity" in source
    assert "--query Arn" in source
    assert "--output text" in source
    assert "EXPECTED_ROLE_NAME: clouddoc-dev-github-identity" in source
    assert ("EXPECTED_SESSION_NAME: clouddoc-identity-${{ github.run_id }}") in source
    assert (":assumed-role/${EXPECTED_ROLE_NAME}/${EXPECTED_SESSION_NAME}") in source
    assert "AWS OIDC identity federation verified." in source


def test_identity_workflows_do_not_execute_project_code() -> None:
    """Identity verification must not install packages or run project tools."""
    combined = "\n".join(read_text(path) for path in IDENTITY_WORKFLOWS)

    forbidden = (
        "actions/checkout",
        "setup-python",
        "setup-terraform",
        "pip install",
        "make",
        "pytest",
        "ruff",
        "terraform",
        "scripts/",
        "artifacts/",
        "upload-artifact",
        "download-artifact",
    )

    for value in forbidden:
        assert value not in combined


def test_workflows_forbid_static_aws_credentials() -> None:
    """No workflow may introduce static AWS keys or secret-backed identity."""
    combined = "\n".join(workflow_sources().values())

    forbidden = (
        "secrets.AWS_ACCESS_KEY_ID",
        "secrets.AWS_SECRET_ACCESS_KEY",
        "secrets.AWS_SESSION_TOKEN",
        "aws-access-key-id:",
        "aws-secret-access-key:",
        "aws-session-token:",
    )

    for value in forbidden:
        assert value not in combined


def test_workflows_contain_no_deployment_or_state_mutation_commands() -> None:
    """Workflows must never mutate remote infrastructure or publish releases."""
    combined = "\n".join(workflow_sources().values()).lower()

    forbidden = (
        "terraform plan",
        "terraform apply",
        "terraform destroy",
        "force-unlock",
        "migrate-state",
        "-lock=false",
        "-auto-approve",
        "actions/upload-artifact",
        "actions/download-artifact",
        "gh release",
        "aws s3",
    )

    for value in forbidden:
        assert value not in combined


def test_only_reusable_identity_uses_the_dev_environment() -> None:
    """Exactly one GitHub Environment reference must exist, on the reusable job."""
    reusable = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)
    caller = read_text(AWS_IDENTITY_WORKFLOW)
    reusable_job = extract_job_block(reusable, "verify-identity")

    assert "\n    environment: dev\n" in reusable_job
    assert reusable.count("\n    environment: ") == 1
    assert reusable.count("environment: dev") == 1
    assert "environment:" not in caller
    assert "environment: " not in read_text(AWS_IDENTITY_WORKFLOW)


def test_workflows_use_no_artifact_transfer_action() -> None:
    """Validation jobs must remain independent and publication-free."""
    combined = "\n".join(workflow_sources().values())

    assert "actions/upload-artifact" not in combined
    assert "actions/download-artifact" not in combined


def test_dependabot_updates_only_github_actions_weekly() -> None:
    """Immutable action pins must receive maintainable update proposals."""
    source = read_text(DEPENDABOT_CONFIG)

    assert source.startswith("version: 2\n")
    assert source.count("package-ecosystem:") == 1
    assert "package-ecosystem: github-actions" in source
    assert "directory: /" in source
    assert "interval: weekly" in source
    assert "open-pull-requests-limit: 5" in source


def test_dependabot_does_not_define_unapproved_ecosystems() -> None:
    """This slice must not silently expand dependency-update ownership."""
    source = read_text(DEPENDABOT_CONFIG)

    forbidden = (
        "package-ecosystem: pip",
        "package-ecosystem: npm",
        "package-ecosystem: docker",
        "package-ecosystem: terraform",
    )

    for value in forbidden:
        assert value not in source
