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
DEPENDABOT_CONFIG = GITHUB_ROOT / "dependabot.yml"

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
}
EXPECTED_ACTION_COUNTS = {
    "actions/checkout": 3,
    "actions/setup-python": 3,
    "hashicorp/setup-terraform": 1,
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
    assert DEPENDABOT_CONFIG.is_file()


@pytest.mark.parametrize(
    ("path", "expected_name"),
    [
        (PYTHON_WORKFLOW, "Python Quality"),
        (INFRASTRUCTURE_WORKFLOW, "Infrastructure Quality"),
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


@pytest.mark.parametrize(
    "path",
    [PYTHON_WORKFLOW, INFRASTRUCTURE_WORKFLOW],
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
def test_workflows_have_read_only_permissions(path: Path) -> None:
    """Validation workflows require repository read access only."""
    permissions = extract_top_level_block(
        read_text(path),
        "permissions",
    )

    assert permissions.strip() == "permissions:\n  contents: read"


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

    assert len(references) == 7

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
            match = ACTION_REFERENCE_PATTERN.fullmatch(line)
            assert match is not None, f"Unrecognized action reference in {path}: {line}"
            assert FULL_SHA_PATTERN.fullmatch(match.group("reference"))


def test_every_checkout_disables_persisted_credentials() -> None:
    """Read-only workflows must not retain a writable Git credential."""
    sources = workflow_sources()
    combined = "\n".join(sources.values())

    assert combined.count("actions/checkout@") == 3
    assert combined.count("persist-credentials: false") == 3


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


def test_workflows_contain_no_authenticated_aws_inputs() -> None:
    """Validation must remain independent from AWS identity and state."""
    combined = "\n".join(workflow_sources().values())

    forbidden = (
        "secrets.",
        "vars.",
        "AWS_",
        "CLOUDDOC_TERRAFORM_STATE_BUCKET",
        "CLOUDDOC_EXPECTED_AWS_ACCOUNT_ID",
        "TF_VAR_expected_aws_account_id",
        "id-token:",
        "aws-actions/",
    )

    for value in forbidden:
        assert value not in combined


def test_workflows_contain_no_deployment_or_state_mutation_commands() -> None:
    """Infrastructure quality must never mutate remote infrastructure."""
    combined = "\n".join(workflow_sources().values()).lower()

    forbidden = (
        "terraform plan",
        "terraform apply",
        "terraform destroy",
        "force-unlock",
        "migrate-state",
        "-lock=false",
        "-auto-approve",
        "workflow_run:",
        "environment:",
    )

    for value in forbidden:
        assert value not in combined


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
