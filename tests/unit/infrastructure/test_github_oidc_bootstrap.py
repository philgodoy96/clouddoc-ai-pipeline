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
    ("aws_iam_role", "github_dev_deploy_identity"),
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
IDENTITY_WORKFLOW_REF = (
    "philgodoy96/clouddoc-ai-pipeline/.github/workflows/"
    "reusable-aws-identity.yml@refs/heads/main"
)
TERRAFORM_PLAN_WORKFLOW_REF = (
    "philgodoy96/clouddoc-ai-pipeline/.github/workflows/"
    "reusable-terraform-plan.yml@refs/heads/main"
)
TERRAFORM_DEPLOY_WORKFLOW_REF = (
    "philgodoy96/clouddoc-ai-pipeline/.github/workflows/"
    "reusable-terraform-deploy.yml@refs/heads/main"
)


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
    """Authentication bootstrap must own only the reviewed identity resources."""
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
    """Both GitHub trust policies must be explicit and wildcard-free."""
    source = read_bootstrap_file("data.tf")

    actual_claims = set(
        re.findall(
            r'variable\s*=\s*"\$\{local\.github_oidc_host\}:([^"]+)"',
            source,
        )
    )

    assert actual_claims == EXPECTED_TRUST_CLAIMS
    assert len(actual_claims) == 8
    assert source.count('test     = "StringEquals"') == 16
    assert source.count('"sts:AssumeRoleWithWebIdentity"') == 2
    assert source.count("${local.github_oidc_host}:job_workflow_ref") == 2
    assert "values = local.github_trusted_workflow_refs" in source
    assert "${local.github_oidc_host}:sub" in source
    assert "local.github_oidc_subject" in source
    assert "local.github_deploy_subject" in source
    assert "StringLike" not in source
    assert '"*"' not in source
    assert '"?"' not in source
    assert "job_workflow_sha" not in source
    assert "pull_request" not in source
    assert "refs/pull/" not in source
    assert "refs/tags/" not in source


def test_oidc_subject_is_built_from_reviewed_identity_variables() -> None:
    """Both exact ID-qualified subjects must come from Terraform variables."""
    locals_source = re.sub(r"\s+", "", read_bootstrap_file("locals.tf"))
    expected_subject = (
        'github_oidc_subject="repo:${var.github_repository_owner}'
        "@${var.github_repository_owner_id}/${var.github_repository_name}"
        '@${var.github_repository_id}:environment:${var.github_environment}"'
    )
    expected_deploy_subject = (
        'github_deploy_subject="repo:${var.github_repository_owner}'
        "@${var.github_repository_owner_id}/${var.github_repository_name}"
        '@${var.github_repository_id}:environment:${var.github_deploy_environment}"'
    )

    assert expected_subject in locals_source
    assert expected_deploy_subject in locals_source
    assert "job_workflow_sha" not in locals_source


def test_trusted_workflow_refs_local_contains_exactly_both_variables() -> None:
    """Canonical allowlist must include exactly the identity and plan workflow refs."""
    locals_source = re.sub(r"\s+", "", read_bootstrap_file("locals.tf"))

    assert "github_trusted_workflow_refs=sort([" in locals_source
    assert "var.github_identity_workflow_ref" in locals_source
    assert "var.github_terraform_plan_workflow_ref" in locals_source
    assert locals_source.count("var.github_identity_workflow_ref") == 1
    assert locals_source.count("var.github_terraform_plan_workflow_ref") == 1
    assert "var.github_terraform_deploy_workflow_ref" not in locals_source


def test_identity_role_has_no_authorization_policy() -> None:
    """Both identity roles must remain authentication-only."""
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
        "arn:aws:iam::aws:policy/",
        "administratoraccess",
        "readonlyaccess",
        "poweruseraccess",
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
    assert 'github_deploy_environment    = "dev-deploy"' in source
    assert 'github_ref                   = "refs/heads/main"' in source
    assert f'github_identity_workflow_ref = "{IDENTITY_WORKFLOW_REF}"' in source
    assert (
        f'github_terraform_plan_workflow_ref = "{TERRAFORM_PLAN_WORKFLOW_REF}"'
    ) in source
    assert (
        f'github_terraform_deploy_workflow_ref = "{TERRAFORM_DEPLOY_WORKFLOW_REF}"'
    ) in source
    assert re.search(r'=\s*"[0-9]{5,}"', source) is None
    assert "arn:aws:iam::" not in source

    lowered = source.lower()
    assert "access_key" not in lowered
    assert "secret_key" not in lowered
    assert "session_token" not in lowered


def test_role_and_workflow_defaults_remain_narrow() -> None:
    """Defaults should stay pinned to the reviewed roles and workflows."""
    variables = read_bootstrap_file("variables.tf")
    locals_source = read_bootstrap_file("locals.tf")
    outputs = read_bootstrap_file("outputs.tf")

    assert 'variable "github_deploy_environment"' in variables
    assert 'variable "github_identity_workflow_ref"' in variables
    assert 'variable "github_terraform_plan_workflow_ref"' in variables
    assert 'variable "github_terraform_deploy_workflow_ref"' in variables
    assert 'default     = "dev"' in variables
    assert 'default     = "dev-deploy"' in variables
    assert 'default     = "refs/heads/main"' in variables
    assert f'default     = "{IDENTITY_WORKFLOW_REF}"' in variables
    assert f'default     = "{TERRAFORM_PLAN_WORKFLOW_REF}"' in variables
    assert f'default     = "{TERRAFORM_DEPLOY_WORKFLOW_REF}"' in variables
    assert "reusable-aws-identity.yml@refs/heads/main" in variables
    assert "reusable-terraform-plan.yml@refs/heads/main" in variables
    assert "reusable-terraform-deploy.yml@refs/heads/main" in variables
    assert "*" not in IDENTITY_WORKFLOW_REF
    assert "*" not in TERRAFORM_PLAN_WORKFLOW_REF
    assert "*" not in TERRAFORM_DEPLOY_WORKFLOW_REF
    assert "?" not in IDENTITY_WORKFLOW_REF
    assert "?" not in TERRAFORM_PLAN_WORKFLOW_REF
    assert "?" not in TERRAFORM_DEPLOY_WORKFLOW_REF
    assert "refs/pull/" not in variables
    assert "refs/tags/" not in variables
    assert "var.role_max_session_duration == 3600" in variables
    assert (
        '"${var.project_name}-${var.github_environment}-github-identity"'
        in locals_source
    )
    assert (
        '"${var.project_name}-${var.github_environment}-github-deploy-identity"'
        in locals_source
    )
    assert 'output "github_identity_workflow_ref"' in outputs
    assert 'output "github_deploy_environment"' in outputs
    assert 'output "github_terraform_deploy_workflow_ref"' in outputs
    assert 'output "github_deploy_identity_role_name"' in outputs
    assert 'output "github_deploy_identity_role_arn"' in outputs
    assert 'output "github_deploy_identity_role_max_session_duration"' in outputs
    assert 'output "github_deploy_trusted_repository_identity"' in outputs
    assert 'output "github_trusted_workflow_refs"' in outputs
    assert "value       = local.github_trusted_workflow_refs" in outputs
    assert "value       = var.github_identity_workflow_ref" in outputs


def test_existing_identity_trust_remains_unchanged_and_deploy_trust_is_separate() -> (
    None
):
    """Existing trust stays intact while deployment trust stays isolated."""
    source = read_bootstrap_file("data.tf")

    assert 'data "aws_iam_policy_document" "github_identity_assume_role"' in source
    assert (
        'data "aws_iam_policy_document" "github_deploy_identity_assume_role"' in source
    )
    assert "values = local.github_trusted_workflow_refs" in source
    assert (
        "values = [\n        var.github_terraform_deploy_workflow_ref,\n      ]"
        in source
    )
    assert source.count('variable = "${local.github_oidc_host}:job_workflow_ref"') == 2
    assert source.count(IDENTITY_WORKFLOW_REF) == 0
    assert source.count(TERRAFORM_PLAN_WORKFLOW_REF) == 0


def test_deploy_role_and_outputs_expose_only_the_reviewed_contract() -> None:
    """Deployment role and outputs should expose only the reviewed public contract."""
    roles = read_bootstrap_file("roles.tf")
    outputs = read_bootstrap_file("outputs.tf")

    assert 'resource "aws_iam_role" "github_dev_deploy_identity"' in roles
    assert "name = local.github_deploy_identity_role_name" in roles
    assert (
        "data.aws_iam_policy_document.github_deploy_identity_assume_role.json" in roles
    )
    assert "max_session_duration = var.role_max_session_duration" in roles
    assert "managed_policy_arns" not in roles
    assert "inline_policy" not in roles

    assert 'output "github_deploy_identity_role_name"' in outputs
    assert 'output "github_deploy_identity_role_arn"' in outputs
    assert 'output "github_deploy_identity_role_max_session_duration"' in outputs
    assert 'output "github_deploy_environment"' in outputs
    assert 'output "github_terraform_deploy_workflow_ref"' in outputs
    assert 'output "github_deploy_trusted_repository_identity"' in outputs
    assert "environment         = var.github_deploy_environment" in outputs
