"""Static contracts for the GitHub OIDC Terraform bootstrap root."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_ROOT = REPOSITORY_ROOT / "infra" / "bootstrap" / "github-oidc"
APPLICATION_TERRAFORM_ROOT = REPOSITORY_ROOT / "infra" / "terraform"
STATE_BOOTSTRAP_ROOT = REPOSITORY_ROOT / "infra" / "bootstrap" / "terraform-state"

EXPECTED_BOOTSTRAP_FILES = {
    ".terraform.lock.hcl",
    "README.md",
    "data.tf",
    "locals.tf",
    "oidc.tf",
    "outputs.tf",
    "providers.tf",
    "roles.tf",
    "terraform.tfvars.example",
    "variables.tf",
    "versions.tf",
}
EXPECTED_TERRAFORM_TEST_FILES = {
    "github_oidc.tftest.hcl",
}
EXPECTED_RESOURCES = {
    ("aws_iam_openid_connect_provider", "github_actions"),
    ("aws_iam_role", "github_dev_identity"),
}
EXPECTED_TRUST_CLAIMS = {
    "aud",
    "sub",
    "repository",
    "repository_id",
    "repository_owner_id",
    "ref",
    "environment",
    "job_workflow_ref",
}


def read_bootstrap_file(relative_path: str) -> str:
    """Read one UTF-8 GitHub OIDC bootstrap file."""
    return (BOOTSTRAP_ROOT / relative_path).read_text(encoding="utf-8")


def terraform_source() -> str:
    """Return all root Terraform source as one searchable string."""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(BOOTSTRAP_ROOT.glob("*.tf"))
    )


def test_bootstrap_root_contains_the_approved_source_files() -> None:
    """The OIDC bootstrap root should retain its reviewed source set."""
    ignored_local_artifacts = {
        "github-oidc-bootstrap.tfplan",
        "terraform.tfstate",
        "terraform.tfstate.backup",
        "terraform.tfvars",
    }
    actual_source_files = {
        path.name
        for path in BOOTSTRAP_ROOT.iterdir()
        if (
            path.is_file()
            and path.name not in ignored_local_artifacts
            and path.suffix != ".tfplan"
        )
    }

    assert actual_source_files == EXPECTED_BOOTSTRAP_FILES


def test_bootstrap_contains_the_approved_terraform_test_file() -> None:
    """The bootstrap root should keep one focused mocked test suite."""
    tests_root = BOOTSTRAP_ROOT / "tests"
    actual_test_files = {path.name for path in tests_root.iterdir() if path.is_file()}

    assert actual_test_files == EXPECTED_TERRAFORM_TEST_FILES


def test_all_terraform_roots_share_the_reviewed_provider_lock() -> None:
    """Application and bootstrap roots should share cross-platform hashes."""
    oidc_lock = read_bootstrap_file(".terraform.lock.hcl")
    application_lock = (APPLICATION_TERRAFORM_ROOT / ".terraform.lock.hcl").read_text(
        encoding="utf-8"
    )
    state_lock = (STATE_BOOTSTRAP_ROOT / ".terraform.lock.hcl").read_text(
        encoding="utf-8"
    )

    assert oidc_lock == application_lock == state_lock

    platform_hashes = re.findall(r'"h1:[^"]+"', oidc_lock)
    assert len(platform_hashes) == 2
    assert 'version     = "5.100.0"' in oidc_lock
    assert 'constraints = "~> 5.0"' in oidc_lock


def test_bootstrap_preserves_the_project_terraform_version_contract() -> None:
    """The trust root should use the same Terraform and provider ranges."""
    source = read_bootstrap_file("versions.tf")

    assert 'required_version = ">= 1.10.0, < 2.0.0"' in source
    assert 'source  = "hashicorp/aws"' in source
    assert 'version = "~> 5.0"' in source


def test_bootstrap_owns_only_the_oidc_provider_and_identity_role() -> None:
    """Authentication bootstrap must not grow application resources."""
    source = terraform_source()
    actual_resources = set(
        re.findall(
            r'resource\s+"([^"]+)"\s+"([^"]+)"',
            source,
        )
    )

    assert actual_resources == EXPECTED_RESOURCES


def test_bootstrap_state_remains_local_and_independent() -> None:
    """The trust substrate must not depend on application remote state."""
    source = terraform_source().lower()

    assert 'backend "s3"' not in source
    assert "terraform_remote_state" not in source
    assert "aws_s3_bucket" not in source
    assert "dynamodb_table" not in source


def test_trust_policy_uses_only_exact_approved_claims() -> None:
    """The GitHub trust policy must be explicit and wildcard-free."""
    source = read_bootstrap_file("data.tf")

    actual_claims = set(
        re.findall(
            r'variable\s*=\s*"\$\{local\.github_oidc_host\}:([^"]+)"',
            source,
        )
    )

    assert actual_claims == EXPECTED_TRUST_CLAIMS
    assert source.count('test     = "StringEquals"') == 8
    assert source.count('"sts:AssumeRoleWithWebIdentity"') == 1
    assert "${local.github_oidc_host}:sub" in source
    assert "local.github_oidc_subject" in source
    assert "StringLike" not in source
    assert '"*"' not in source
    assert '"?"' not in source
    assert "job_workflow_sha" not in source
    assert "pull_request" not in source


def test_oidc_subject_is_built_from_reviewed_identity_variables() -> None:
    """The exact ID-qualified subject must come from Terraform variables."""
    locals_source = re.sub(r"\s+", "", read_bootstrap_file("locals.tf"))
    expected_subject = (
        'github_oidc_subject="repo:${var.github_repository_owner}'
        "@${var.github_repository_owner_id}/${var.github_repository_name}"
        '@${var.github_repository_id}:environment:${var.github_environment}"'
    )

    assert expected_subject in locals_source
    assert "job_workflow_sha" not in locals_source


def test_identity_role_has_no_authorization_policy() -> None:
    """The verification role must remain authentication-only."""
    source = terraform_source().lower()

    forbidden = (
        'resource "aws_iam_policy"',
        'resource "aws_iam_role_policy"',
        'resource "aws_iam_role_policy_attachment"',
        'resource "aws_iam_policy_attachment"',
        "managed_policy_arns",
        "permissions_boundary",
        "inline_policy",
        "policy_arn",
    )

    for value in forbidden:
        assert value not in source


def test_bootstrap_hcl_contains_no_static_credential_configuration() -> None:
    """AWS credentials must come from an external human session."""
    source = terraform_source().lower()

    forbidden_assignments = (
        "access_key",
        "secret_key",
        "token",
        "profile",
        "shared_credentials_file",
    )

    for assignment in forbidden_assignments:
        assert re.search(rf"\b{assignment}\s*=", source) is None


def test_example_variables_keep_identifiers_as_placeholders() -> None:
    """The committed example must not contain credentials or invented IDs."""
    source = read_bootstrap_file("terraform.tfvars.example")

    assert (
        'github_repository_id       = "REPLACE_WITH_GITHUB_REPOSITORY_ID"'
    ) in source
    assert (
        'github_repository_owner_id = "REPLACE_WITH_GITHUB_REPOSITORY_OWNER_ID"'
    ) in source
    assert 'github_environment           = "dev"' in source
    assert 'github_ref                   = "refs/heads/main"' in source

    lowered = source.lower()
    assert "access_key" not in lowered
    assert "secret_key" not in lowered
    assert "session_token" not in lowered


def test_role_and_workflow_defaults_remain_narrow() -> None:
    """Defaults should target one role, branch, environment, and workflow."""
    variables = read_bootstrap_file("variables.tf")
    locals_source = read_bootstrap_file("locals.tf")

    assert 'default     = "dev"' in variables
    assert 'default     = "refs/heads/main"' in variables
    assert "reusable-aws-identity.yml@refs/heads/main" in variables
    assert "var.role_max_session_duration == 3600" in variables
    assert (
        '"${var.project_name}-${var.github_environment}-github-identity"'
        in locals_source
    )
