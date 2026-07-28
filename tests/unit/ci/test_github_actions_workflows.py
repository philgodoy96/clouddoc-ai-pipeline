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
TERRAFORM_PLAN_WORKFLOW = WORKFLOWS_ROOT / "terraform-plan.yml"
REUSABLE_TERRAFORM_PLAN_WORKFLOW = WORKFLOWS_ROOT / "reusable-terraform-plan.yml"
TERRAFORM_DEPLOY_WORKFLOW = WORKFLOWS_ROOT / "terraform-deploy.yml"
REUSABLE_TERRAFORM_DEPLOY_WORKFLOW = WORKFLOWS_ROOT / "reusable-terraform-deploy.yml"
DEPENDABOT_CONFIG = GITHUB_ROOT / "dependabot.yml"

VALIDATION_WORKFLOWS = (PYTHON_WORKFLOW, INFRASTRUCTURE_WORKFLOW)
IDENTITY_WORKFLOWS = (
    AWS_IDENTITY_WORKFLOW,
    REUSABLE_AWS_IDENTITY_WORKFLOW,
)

LOCAL_REUSABLE_AWS_IDENTITY_USES = "uses: ./.github/workflows/reusable-aws-identity.yml"
LOCAL_REUSABLE_TERRAFORM_PLAN_USES = (
    "uses: ./.github/workflows/reusable-terraform-plan.yml"
)
LOCAL_REUSABLE_TERRAFORM_DEPLOY_USES = (
    "uses: ./.github/workflows/reusable-terraform-deploy.yml"
)
LOCAL_REUSABLE_WORKFLOW_USES = frozenset(
    {
        LOCAL_REUSABLE_AWS_IDENTITY_USES,
        LOCAL_REUSABLE_TERRAFORM_PLAN_USES,
        LOCAL_REUSABLE_TERRAFORM_DEPLOY_USES,
    }
)

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
    "actions/upload-artifact": (
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "v7.0.1",
    ),
    "actions/download-artifact": (
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "v8.0.1",
    ),
}
EXPECTED_ACTION_COUNTS = {
    "actions/checkout": 6,
    "actions/setup-python": 5,
    "hashicorp/setup-terraform": 3,
    "aws-actions/configure-aws-credentials": 3,
    "actions/upload-artifact": 1,
    "actions/download-artifact": 1,
}
EXPECTED_WORKFLOW_FILES = frozenset(
    {
        "python-quality.yml",
        "infrastructure-quality.yml",
        "aws-identity-check.yml",
        "reusable-aws-identity.yml",
        "terraform-plan.yml",
        "reusable-terraform-plan.yml",
        "terraform-deploy.yml",
        "reusable-terraform-deploy.yml",
    }
)

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
    assert TERRAFORM_PLAN_WORKFLOW.is_file()
    assert REUSABLE_TERRAFORM_PLAN_WORKFLOW.is_file()
    assert TERRAFORM_DEPLOY_WORKFLOW.is_file()
    assert REUSABLE_TERRAFORM_DEPLOY_WORKFLOW.is_file()
    assert DEPENDABOT_CONFIG.is_file()
    assert {
        path.name for path in WORKFLOWS_ROOT.glob("*.yml")
    } == EXPECTED_WORKFLOW_FILES


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

    assert len(references) == 19

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
            if line in LOCAL_REUSABLE_WORKFLOW_USES:
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

    assert combined.count("actions/checkout@") == 6
    assert combined.count("persist-credentials: false") == 6


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

    assert LOCAL_REUSABLE_AWS_IDENTITY_USES in job
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


def test_workflows_contain_no_direct_terraform_mutation_commands() -> None:
    """Workflows must never invoke raw Terraform apply/destroy or unlock."""
    combined = "\n".join(workflow_sources().values())
    lowered = combined.lower()

    forbidden = (
        "terraform destroy",
        "force-unlock",
        "migrate-state",
        "-lock=false",
        "-auto-approve",
        "gh release",
        "aws s3",
    )

    for value in forbidden:
        assert value not in lowered

    # Speculative plans and controlled deploys must go through the reviewed wrapper.
    assert re.search(r"(?m)^\s*terraform\s+plan\b", combined) is None
    assert re.search(r"(?m)^\s*terraform\s+apply\b", combined) is None
    assert "python scripts/terraform_workflow.py plan" in combined
    assert "python scripts/terraform_workflow.py deploy" in combined
    assert "python scripts/terraform_workflow.py apply" not in combined


def test_artifact_transfer_is_limited_to_value_free_plan_attestation() -> None:
    """Only the value-free plan attestation may cross workflow runs."""
    plan = read_text(REUSABLE_TERRAFORM_PLAN_WORKFLOW)
    deploy = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)
    combined = "\n".join(workflow_sources().values())

    assert plan.count("actions/upload-artifact@") == 1
    assert deploy.count("actions/download-artifact@") == 1
    assert combined.count("actions/upload-artifact@") == 1
    assert combined.count("actions/download-artifact@") == 1

    assert "name: clouddoc-terraform-plan-attestation" in plan
    assert "path: ${{ env.PLAN_ATTESTATION }}" in plan
    assert "retention-days: 1" in plan
    assert "if-no-files-found: error" in plan
    assert "include-hidden-files: false" in plan

    assert "name: clouddoc-terraform-plan-attestation" in deploy
    assert "digest-mismatch: error" in deploy
    assert "digest-mismatch: ignore" not in combined
    assert "digest-mismatch: warn" not in combined
    assert "merge-multiple:" not in combined
    assert re.search(r"(?m)^\s*pattern:\s*", combined) is None

    forbidden_upload_paths = (
        "clouddoc.tfplan",
        "terraform-show.json",
        "clouddoc.tfplan.json",
    )
    upload_block = plan[
        plan.index("id: upload-plan-attestation") : plan.index(
            "name: Record attestation artifact digest"
        )
    ]
    for value in forbidden_upload_paths:
        assert value not in upload_block
    assert "path: ${{ env.PLAN_DIRECTORY }}" not in upload_block
    assert "path: ${{ runner.temp }}" not in upload_block


def test_workflows_forbid_binary_plan_and_state_artifact_publication() -> None:
    """Binary plans, full JSON, and state must never become artifacts."""
    combined = "\n".join(workflow_sources().values())

    assert "actions/upload-artifact@" in combined
    upload_sections = [
        line.strip()
        for line in combined.splitlines()
        if "path:" in line
        and (
            "clouddoc.tfplan" in line
            or "terraform-show.json" in line
            or "tfstate" in line
        )
    ]
    assert upload_sections == []
    assert "skip-decompress" not in combined
    assert "repository: ${{ vars." not in combined


def test_only_reusable_identity_uses_the_dev_environment() -> None:
    """Identity verification retains its dedicated reusable-job environment."""
    reusable = read_text(REUSABLE_AWS_IDENTITY_WORKFLOW)
    caller = read_text(AWS_IDENTITY_WORKFLOW)
    reusable_job = extract_job_block(reusable, "verify-identity")

    assert "\n    environment: dev\n" in reusable_job
    assert reusable.count("\n    environment: ") == 1
    assert reusable.count("environment: dev") == 1
    assert "environment:" not in caller
    assert "environment: " not in read_text(AWS_IDENTITY_WORKFLOW)


def test_reusable_terraform_plan_remains_workflow_call_only() -> None:
    """The plan reusable workflow must stay callable and never standalone."""
    triggers = extract_top_level_block(
        read_text(REUSABLE_TERRAFORM_PLAN_WORKFLOW),
        "on",
    )

    assert "workflow_call:" in triggers
    assert "workflow_dispatch:" not in triggers
    assert "pull_request:" not in triggers
    assert "push:" not in triggers


def test_reusable_terraform_plan_publishes_value_free_attestation_only() -> None:
    """Plan must generate, validate, upload, and clean the attestation artifact."""
    source = read_text(REUSABLE_TERRAFORM_PLAN_WORKFLOW)
    job = extract_job_block(source, "plan-dev")

    assert "environment: dev" in job
    assert "terraform_plan_attestation.py generate" in source
    assert "terraform_plan_attestation.py validate" in source
    assert "show" in source
    assert "-json" in source
    assert source.index("PLAN_JSON=") < source.index(
        "terraform_plan_attestation.py generate"
    )
    assert source.index("terraform_plan_attestation.py generate") < source.index(
        "terraform_plan_attestation.py validate"
    )
    assert source.index("terraform_plan_attestation.py validate") < source.index(
        "summarize_terraform_plan.py"
    )
    assert source.index("summarize_terraform_plan.py") < source.index(
        "id: upload-plan-attestation"
    )
    assert "PLAN_ATTESTATION=" in source
    assert "terraform-plan-attestation.json" in source
    assert (
        "uses: actions/upload-artifact@"
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
    ) in source
    assert "name: clouddoc-terraform-plan-attestation" in source
    assert "path: ${{ env.PLAN_ATTESTATION }}" in source
    assert "retention-days: 1" in source
    assert "if-no-files-found: error" in source
    assert "include-hidden-files: false" in source
    assert "path: ${{ env.PLAN_JSON }}" not in source
    assert "path: ${{ env.PLAN_FILE }}" not in source
    assert "Clean up Terraform plan files" in source
    assert "Verify Terraform plan cleanup" in source
    assert "if: ${{ always() }}" in source
    assert "summarize_terraform_plan.py" in source
    assert (
        "> Speculative plan only. No deployment command was executed, "
        "and no saved plan was retained."
    ) in source


def test_terraform_deploy_caller_is_manual_only_with_exact_inputs() -> None:
    """The deploy caller accepts only the three reviewed manual inputs."""
    source = read_text(TERRAFORM_DEPLOY_WORKFLOW)
    triggers = extract_top_level_block(source, "on")
    permissions = extract_top_level_block(source, "permissions")
    concurrency = extract_top_level_block(source, "concurrency")
    job = extract_job_block(source, "deploy-dev")

    assert source.startswith("name: Terraform Deploy\n")
    assert "workflow_dispatch:" in triggers
    assert "pull_request:" not in triggers
    assert "push:" not in triggers
    assert "workflow_call:" not in triggers
    assert "schedule:" not in triggers

    assert triggers.count("plan_run_id:") == 1
    assert triggers.count("confirmation:") == 1
    assert triggers.count("allow_destructive_changes:") == 1
    assert "type: string" in triggers
    assert "type: boolean" in triggers
    assert "default: false" in triggers
    assert "expected_commit_sha" not in triggers
    assert "environment selector" not in triggers

    assert permissions.strip() == (
        "permissions:\n  actions: read\n  contents: read\n  id-token: write"
    )
    assert concurrency.strip() == (
        "concurrency:\n"
        "  group: clouddoc-terraform-deploy-dev\n"
        "  cancel-in-progress: false"
    )

    assert LOCAL_REUSABLE_TERRAFORM_DEPLOY_USES in job
    assert source.count("uses: ./.github/workflows/") == 1
    assert "plan_run_id: ${{ inputs.plan_run_id }}" in job
    assert "confirmation: ${{ inputs.confirmation }}" in job
    assert ("allow_destructive_changes: ${{ inputs.allow_destructive_changes }}") in job
    assert "aws_account_id: ${{ vars.CLOUDDOC_AWS_ACCOUNT_ID }}" in job
    assert "aws_region: us-east-1" in job
    assert (
        "deploy_identity_role_arn: ${{ vars.CLOUDDOC_DEV_DEPLOY_IDENTITY_ROLE_ARN }}"
    ) in job
    assert "state_bucket: ${{ vars.CLOUDDOC_TERRAFORM_STATE_BUCKET }}" in job
    assert ("state_role_arn: ${{ vars.CLOUDDOC_DEV_TERRAFORM_STATE_ROLE_ARN }}") in job
    assert ("apply_role_arn: ${{ vars.CLOUDDOC_DEV_TERRAFORM_APPLY_ROLE_ARN }}") in job
    assert (
        "permissions:\n      actions: read\n      contents: read\n      id-token: write"
    ) in job
    assert "runs-on:" not in job
    assert "steps:" not in job
    assert "environment:" not in job
    assert "secrets: inherit" not in source
    assert "shell:" not in job


def test_reusable_terraform_deploy_interface_and_environment() -> None:
    """The reusable deploy workflow exposes the exact reviewed call contract."""
    source = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)
    triggers = extract_top_level_block(source, "on")
    permissions = extract_top_level_block(source, "permissions")
    job = extract_job_block(source, "deploy-dev")

    assert source.startswith("name: Reusable Terraform Deploy\n")
    assert "workflow_call:" in triggers
    assert "workflow_dispatch:" not in triggers
    assert "secrets:" not in triggers

    for input_name in (
        "plan_run_id",
        "confirmation",
        "allow_destructive_changes",
        "aws_account_id",
        "aws_region",
        "deploy_identity_role_arn",
        "state_bucket",
        "state_role_arn",
        "apply_role_arn",
    ):
        assert f"{input_name}:" in triggers

    assert triggers.count("required: true") == 9
    assert permissions.strip() == (
        "permissions:\n  actions: read\n  contents: read\n  id-token: write"
    )
    assert source.count("\n  deploy-dev:\n") == 1
    assert "environment: dev-deploy" in job
    assert "runs-on: ubuntu-latest" in job
    assert "timeout-minutes: 45" in job
    assert "concurrency:" not in job


def test_reusable_terraform_deploy_security_ordering() -> None:
    """Request, artifact, destructive, and OIDC checks must precede AWS auth."""
    source = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)

    context_step = "name: Validate trusted workflow context"
    plan_run_step = "name: Validate referenced Terraform Plan run"
    download_step = "name: Download plan attestation"
    attestation_step = "name: Validate Terraform plan attestation"
    destructive_step = "name: Validate destructive-change authorization"
    oidc_step = "name: Validate GitHub OIDC token claims"
    credentials_step = "name: Configure temporary AWS credentials"
    identity_step = "name: Verify assumed AWS identity"
    checkout_step = "name: Check out repository\n"
    deploy_step = "name: Run controlled Terraform deploy"

    assert source.index(context_step) < source.index(plan_run_step)
    assert source.index(plan_run_step) < source.index(download_step)
    assert source.index(download_step) < source.index(attestation_step)
    assert source.index(attestation_step) < source.index(destructive_step)
    assert source.index(destructive_step) < source.index(oidc_step)
    assert source.index(oidc_step) < source.index(credentials_step)
    assert source.index(credentials_step) < source.index(identity_step)
    assert source.index(identity_step) < source.index(checkout_step)
    assert source.index(checkout_step) < source.index(deploy_step)
    assert source.index(plan_run_step) < source.index(credentials_step)
    assert source.index(download_step) < source.index(credentials_step)
    assert source.index(attestation_step) < source.index(credentials_step)
    assert source.index(destructive_step) < source.index(credentials_step)


def test_reusable_terraform_deploy_oidc_and_identity_contract() -> None:
    """Deploy OIDC must enforce eight claims and the permissionless deploy role."""
    source = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)

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

    assert source.count('"aud":') >= 1
    assert (
        "CANONICAL_JOB_WORKFLOW_REF: philgodoy96/clouddoc-ai-pipeline/"
        ".github/workflows/reusable-terraform-deploy.yml@refs/heads/main"
    ) in source
    assert "EXPECTED_ENVIRONMENT: dev-deploy" in source
    assert "EXPECTED_ROLE_NAME: clouddoc-dev-github-deploy-identity" in source
    assert "role-session-name: clouddoc-terraform-deploy-identity" in source
    assert "role-duration-seconds: 900" in source
    assert "clouddoc-dev-terraform-state" in source
    assert "clouddoc-dev-terraform-apply" in source
    assert "CLOUDDOC_DEV_TERRAFORM_PLAN_ROLE_ARN" not in source
    assert "TF_VAR_terraform_plan_role_arn" not in source


def test_reusable_terraform_deploy_toolchain_and_invocation() -> None:
    """Deploy must rebuild Lambda and invoke only the controlled wrapper."""
    source = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)

    assert 'python-version: "3.12"' in source
    assert 'terraform_version: "1.15.8"' in source
    assert "terraform_wrapper: false" in source
    assert "make lambda-package" in source
    assert "make lambda-package-check" in source
    assert "python scripts/terraform_workflow.py deploy" in source
    assert "terraform_workflow.py apply" not in source
    assert re.search(r"(?m)^\s*terraform\s+(plan|apply)\b", source) is None
    assert "--allow-destructive-changes" in source
    assert 'ALLOW_DESTRUCTIVE_CHANGES" == "true"' in source
    assert "clouddoc-terraform-deploy" in source
    assert "$OUTPUT_DIRECTORY" in source
    assert "actions/upload-artifact" not in source
    assert "aws-access-key-id" not in source
    assert "secrets.AWS_ACCESS_KEY_ID" not in source
    assert "trap cleanup EXIT" in source
    assert "Verify Terraform deploy cleanup" in source
    assert "if: ${{ always() }}" in source
    assert (
        "uses: actions/download-artifact@"
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1"
    ) in source
    assert "digest-mismatch: error" in source
    assert "validate_terraform_deployment_request.py" in source
    assert "ref: ${{ github.sha }}" in source
    assert "persist-credentials: false" in source


def test_reusable_terraform_deploy_does_not_consume_binary_plan_artifacts() -> None:
    """Deployment regenerates plans and never downloads binary or full JSON plans."""
    source = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)
    download_block = source[
        source.index("name: Download plan attestation") : source.index(
            "name: Require exact attestation file"
        )
    ]

    assert "clouddoc-terraform-plan-attestation" in download_block
    assert "clouddoc.tfplan" not in download_block
    assert "terraform-show.json" not in download_block
    assert "pattern:" not in download_block
    assert "merge-multiple:" not in download_block


def test_artifact_action_pins_are_exact() -> None:
    """Upload and download artifact actions must use the approved immutable pins."""
    plan = read_text(REUSABLE_TERRAFORM_PLAN_WORKFLOW)
    deploy = read_text(REUSABLE_TERRAFORM_DEPLOY_WORKFLOW)

    assert (
        "uses: actions/upload-artifact@"
        "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
    ) in plan
    assert (
        "uses: actions/download-artifact@"
        "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1"
    ) in deploy


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
