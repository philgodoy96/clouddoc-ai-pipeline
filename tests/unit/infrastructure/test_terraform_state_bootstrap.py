"""Static contract tests for the Terraform state bootstrap root."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_ROOT = REPOSITORY_ROOT / "infra" / "bootstrap" / "terraform-state"
APPLICATION_TERRAFORM_ROOT = REPOSITORY_ROOT / "infra" / "terraform"

EXPECTED_BOOTSTRAP_FILES = {
    ".terraform.lock.hcl",
    "README.md",
    "data.tf",
    "locals.tf",
    "outputs.tf",
    "providers.tf",
    "s3.tf",
    "terraform.tfvars.example",
    "variables.tf",
    "versions.tf",
}


def read_bootstrap_file(relative_path: str) -> str:
    """Read one UTF-8 bootstrap file."""
    return (BOOTSTRAP_ROOT / relative_path).read_text(encoding="utf-8")


def terraform_source() -> str:
    """Return all bootstrap Terraform source as one searchable string."""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(BOOTSTRAP_ROOT.glob("*.tf"))
    )


def test_bootstrap_root_contains_the_approved_source_files() -> None:
    """The bootstrap root should retain its complete reviewed source set."""
    ignored_local_artifacts = {
        "terraform.tfvars",
        "terraform.tfstate",
        "terraform.tfstate.backup",
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


def test_bootstrap_and_application_roots_share_provider_lock_file() -> None:
    """Both Terraform roots should use the same reviewed provider selection."""
    bootstrap_lock = read_bootstrap_file(".terraform.lock.hcl")
    application_lock = (APPLICATION_TERRAFORM_ROOT / ".terraform.lock.hcl").read_text(
        encoding="utf-8"
    )

    assert bootstrap_lock == application_lock


def test_state_bucket_has_explicit_destroy_protection() -> None:
    """State destruction must require an intentional configuration change."""
    source = read_bootstrap_file("s3.tf")

    bucket_match = re.search(
        r'resource\s+"aws_s3_bucket"\s+"terraform_state"\s*\{'
        r"(?P<body>.*?)"
        r"\n\}",
        source,
        flags=re.DOTALL,
    )

    assert bucket_match is not None
    bucket_body = bucket_match.group("body")

    assert re.search(r"\bforce_destroy\s*=\s*false\b", bucket_body)
    assert re.search(
        r"lifecycle\s*\{.*?\bprevent_destroy\s*=\s*true\b.*?\}",
        bucket_body,
        flags=re.DOTALL,
    )


def test_https_only_policy_denies_insecure_transport() -> None:
    """The state bucket policy must reject all non-TLS S3 operations."""
    source = read_bootstrap_file("s3.tf")

    assert 'sid    = "DenyInsecureTransport"' in source
    assert 'effect = "Deny"' in source
    assert '"s3:*"' in source
    assert 'variable = "aws:SecureTransport"' in source
    assert 'values   = ["false"]' in source
    assert "aws_s3_bucket.terraform_state.arn" in source
    assert '"${aws_s3_bucket.terraform_state.arn}/*"' in source


def test_bootstrap_uses_no_remote_backend_or_dynamodb_locking() -> None:
    """Bootstrap state remains local and application locking is not created here."""
    source = terraform_source().lower()

    assert 'backend "s3"' not in source
    assert "aws_dynamodb" not in source
    assert "dynamodb_table" not in source


def test_bootstrap_hcl_contains_no_static_credential_configuration() -> None:
    """AWS credentials must come from the external authentication chain."""
    source = terraform_source().lower()

    forbidden_assignments = (
        "access_key",
        "secret_key",
        "token",
        "shared_credentials_file",
    )

    for assignment in forbidden_assignments:
        assert re.search(rf"\b{assignment}\s*=", source) is None


def test_example_variables_contain_no_credentials_or_secrets() -> None:
    """The committed example should contain only non-sensitive bootstrap inputs."""
    source = read_bootstrap_file("terraform.tfvars.example").lower()

    assert "aws_region" in source
    assert "project_name" in source
    assert "noncurrent_version_retention_days" in source
    assert "access_key" not in source
    assert "secret_key" not in source
    assert "session_token" not in source
