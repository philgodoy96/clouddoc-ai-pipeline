"""Static contracts for the Terraform authorization bootstrap root."""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP_ROOT = REPOSITORY_ROOT / "infra" / "bootstrap" / "terraform-authorization"
APPLICATION_TERRAFORM_ROOT = REPOSITORY_ROOT / "infra" / "terraform"
STATE_BOOTSTRAP_ROOT = REPOSITORY_ROOT / "infra" / "bootstrap" / "terraform-state"
OIDC_BOOTSTRAP_ROOT = REPOSITORY_ROOT / "infra" / "bootstrap" / "github-oidc"

EXPECTED_BOOTSTRAP_FILES = {
    ".terraform.lock.hcl",
    "data.tf",
    "locals.tf",
    "outputs.tf",
    "policies.tf",
    "providers.tf",
    "roles.tf",
    "terraform.tfvars.example",
    "variables.tf",
    "versions.tf",
}
EXPECTED_TERRAFORM_TEST_FILES = {
    "terraform_authorization.tftest.hcl",
}
EXPECTED_RESOURCES = {
    ("aws_iam_role", "terraform_state"),
    ("aws_iam_role", "terraform_plan"),
    ("aws_iam_role_policy", "terraform_state_access"),
    ("aws_iam_role_policy", "terraform_plan_access"),
}

STATE_POLICY_ACTIONS = {
    "s3:ListBucket",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
}

FORBIDDEN_PLAN_ACTION_PATTERN = re.compile(
    r'"(?:[a-z0-9]+):(?:'
    r"Create|Update|Delete|Put|Set|Tag|Untag|Invoke|Send|Start|Stop|"
    r"PassRole|Attach|Detach|Add|Remove|Publish|Purge|Redrive"
    r')[A-Za-z0-9]*"'
)

PLAN_DATA_PLANE_ACTIONS = {
    "lambda:InvokeFunction",
    "lambda:InvokeAsync",
    "sqs:ReceiveMessage",
    "sqs:SendMessage",
    "sqs:DeleteMessage",
    "sqs:ChangeMessageVisibility",
    "sqs:PurgeQueue",
    "dynamodb:GetItem",
    "dynamodb:BatchGetItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
}


def read_bootstrap_file(relative_path: str) -> str:
    """Read one UTF-8 Terraform authorization bootstrap file."""
    return (BOOTSTRAP_ROOT / relative_path).read_text(encoding="utf-8")


def terraform_source() -> str:
    """Return all root Terraform source as one searchable string."""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(BOOTSTRAP_ROOT.glob("*.tf"))
    )


def extract_policy_document_block(name: str) -> str:
    """Return the HCL body for one named aws_iam_policy_document data source."""
    source = read_bootstrap_file("data.tf")
    header = f'data "aws_iam_policy_document" "{name}"'
    start = source.find(header)
    assert start >= 0, f"missing policy document {name}"

    brace_start = source.find("{", start)
    assert brace_start >= 0, f"missing opening brace for {name}"

    depth = 0
    for index in range(brace_start, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : index]

    raise AssertionError(f"unbalanced braces for policy document {name}")


def quoted_actions(block: str) -> set[str]:
    """Extract quoted IAM action strings from actions lists in one policy body."""
    actions: set[str] = set()
    for match in re.finditer(
        r"actions\s*=\s*\[(.*?)\]",
        block,
        flags=re.DOTALL,
    ):
        actions.update(re.findall(r'"((?:[a-z0-9]+):[A-Za-z0-9]+)"', match.group(1)))
    return actions


def test_bootstrap_root_contains_the_approved_source_files() -> None:
    """The authorization bootstrap root should retain its reviewed source set."""
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
            and path.name != ".terraform"
        )
    }

    assert actual_source_files == EXPECTED_BOOTSTRAP_FILES


def test_bootstrap_contains_only_the_tests_nested_directory() -> None:
    """The root should keep one nested tests directory and no other folders."""
    nested_directories = {
        path.name for path in BOOTSTRAP_ROOT.iterdir() if path.is_dir()
    }
    ignored_directories = {".terraform"}
    assert nested_directories - ignored_directories == {"tests"}

    actual_test_files = {
        path.name for path in (BOOTSTRAP_ROOT / "tests").iterdir() if path.is_file()
    }
    assert actual_test_files == EXPECTED_TERRAFORM_TEST_FILES


def test_bootstrap_preserves_the_project_terraform_version_contract() -> None:
    """The authorization root should use the same Terraform and provider ranges."""
    source = read_bootstrap_file("versions.tf")

    assert 'required_version = ">= 1.10.0, < 2.0.0"' in source
    assert 'source  = "hashicorp/aws"' in source
    assert 'version = "~> 5.0"' in source


def test_all_terraform_roots_share_the_reviewed_provider_lock() -> None:
    """Authorization, OIDC, state, and application roots share one lock file."""
    authorization_lock = read_bootstrap_file(".terraform.lock.hcl")
    application_lock = (APPLICATION_TERRAFORM_ROOT / ".terraform.lock.hcl").read_text(
        encoding="utf-8"
    )
    state_lock = (STATE_BOOTSTRAP_ROOT / ".terraform.lock.hcl").read_text(
        encoding="utf-8"
    )
    oidc_lock = (OIDC_BOOTSTRAP_ROOT / ".terraform.lock.hcl").read_text(
        encoding="utf-8"
    )

    assert authorization_lock == application_lock == state_lock == oidc_lock
    assert 'version     = "5.100.0"' in authorization_lock
    assert 'constraints = "~> 5.0"' in authorization_lock


def test_bootstrap_state_remains_local_without_remote_backend() -> None:
    """Authorization bootstrap must keep local state and no remote backend."""
    source = terraform_source().lower()

    assert 'backend "s3"' not in source
    assert "terraform_remote_state" not in source
    assert re.search(r"\bbackend\s*\{", source) is None


def test_bootstrap_hcl_contains_no_static_credential_configuration() -> None:
    """AWS credentials must come from the ambient temporary credential chain."""
    source = terraform_source().lower()

    for assignment in (
        "access_key",
        "secret_key",
        "token",
        "shared_credentials_file",
        "shared_credentials_files",
        "web_identity_token_file",
    ):
        assert re.search(rf"\b{assignment}\s*=", source) is None


def test_bootstrap_hcl_contains_no_profile_assignment() -> None:
    """Shared AWS profiles must not be configured in this bootstrap root."""
    source = terraform_source().lower()

    assert re.search(r"\bprofile\s*=", source) is None


def test_bootstrap_owns_exactly_four_managed_resources() -> None:
    """Authorization bootstrap must manage only the four reviewed IAM resources."""
    source = terraform_source()
    actual_resources = set(
        re.findall(
            r'resource\s+"([^"]+)"\s+"([^"]+)"',
            source,
        )
    )

    assert actual_resources == EXPECTED_RESOURCES
    assert len(actual_resources) == 4


def test_bootstrap_declares_exactly_two_iam_roles() -> None:
    """Exactly two IAM roles should exist for state and plan authorization."""
    roles = {
        name
        for resource_type, name in EXPECTED_RESOURCES
        if resource_type == "aws_iam_role"
    }
    source_roles = set(
        re.findall(r'resource\s+"aws_iam_role"\s+"([^"]+)"', terraform_source())
    )

    assert source_roles == {"terraform_state", "terraform_plan"} == roles


def test_bootstrap_declares_exactly_two_inline_role_policies() -> None:
    """Exactly two inline role policies should attach to the authorization roles."""
    source_policies = set(
        re.findall(
            r'resource\s+"aws_iam_role_policy"\s+"([^"]+)"',
            terraform_source(),
        )
    )

    assert source_policies == {"terraform_state_access", "terraform_plan_access"}


def test_bootstrap_creates_no_customer_managed_policy_or_attachment() -> None:
    """Permissions must remain inline role policies only."""
    source = terraform_source()

    for forbidden in (
        "aws_iam_policy",
        "aws_iam_policy_attachment",
        "aws_iam_role_policy_attachment",
        "aws_iam_user_policy",
    ):
        assert re.search(rf'resource\s+"{forbidden}"', source) is None


def test_role_names_remain_canonical() -> None:
    """Role names must match the approved development authorization contract."""
    locals_source = read_bootstrap_file("locals.tf")
    roles_source = read_bootstrap_file("roles.tf")

    assert re.search(
        r'terraform_state_role_name\s*=\s*"clouddoc-dev-terraform-state"',
        locals_source,
    )
    assert re.search(
        r'terraform_plan_role_name\s*=\s*"clouddoc-dev-terraform-plan"',
        locals_source,
    )
    assert re.search(
        r"name\s*=\s*local\.terraform_state_role_name",
        roles_source,
    )
    assert re.search(
        r"name\s*=\s*local\.terraform_plan_role_name",
        roles_source,
    )


def test_identity_role_principal_is_constructed_exactly() -> None:
    """Target roles must trust the exact same-account identity-role ARN."""
    locals_source = read_bootstrap_file("locals.tf")
    assume_state = extract_policy_document_block("terraform_state_assume_role")
    assume_plan = extract_policy_document_block("terraform_plan_assume_role")

    assert (
        "arn:${data.aws_partition.current.partition}:iam::"
        "${var.aws_account_id}:role/${var.github_identity_role_name}"
        in " ".join(locals_source.split())
    )
    assert "local.github_identity_role_arn" in assume_state
    assert "local.github_identity_role_arn" in assume_plan
    assert 'type = "AWS"' in assume_state
    assert 'type = "AWS"' in assume_plan
    assert '"sts:AssumeRole"' in assume_state
    assert '"sts:AssumeRole"' in assume_plan


def test_trust_policies_contain_no_wildcard_principal() -> None:
    """Trust principals must remain exact role ARNs without wildcards."""
    for name in ("terraform_state_assume_role", "terraform_plan_assume_role"):
        block = extract_policy_document_block(name)
        assert "*" not in block


def test_trust_policies_contain_no_account_root_principal() -> None:
    """Account-root principals must never be trusted by the target roles."""
    for name in ("terraform_state_assume_role", "terraform_plan_assume_role"):
        block = extract_policy_document_block(name)
        assert ":root" not in block
        assert 'identifiers = ["*"]' not in block.replace(" ", "")


def test_trust_policies_contain_no_federated_principal() -> None:
    """Direct OIDC federation must not appear on the state or plan roles."""
    for name in ("terraform_state_assume_role", "terraform_plan_assume_role"):
        block = extract_policy_document_block(name)
        assert "Federated" not in block
        assert "oidc-provider" not in block
        assert "AssumeRoleWithWebIdentity" not in block


def test_state_policy_contains_only_approved_s3_actions() -> None:
    """State authorization must stay inside the reviewed S3 action set."""
    actions = quoted_actions(extract_policy_document_block("terraform_state_access"))

    assert actions == STATE_POLICY_ACTIONS
    assert all(action.startswith("s3:") for action in actions)


def test_state_object_does_not_receive_delete_object() -> None:
    """The Terraform state object must never be deletable through this role."""
    block = extract_policy_document_block("terraform_state_access")
    state_object_statement = re.search(
        r'sid\s*=\s*"ReadWriteExactStateObject".*?(?=sid\s*=|\Z)',
        block,
        flags=re.DOTALL,
    )

    assert state_object_statement is not None
    statement = state_object_statement.group(0)
    assert '"s3:GetObject"' in statement
    assert '"s3:PutObject"' in statement
    assert '"s3:DeleteObject"' not in statement
    assert "local.terraform_state_object_arn" in statement


def test_lock_object_receives_delete_object() -> None:
    """The S3-native lock object must allow DeleteObject for lock release."""
    block = extract_policy_document_block("terraform_state_access")
    lock_object_statement = re.search(
        r'sid\s*=\s*"ManageExactLockObject".*?(?=sid\s*=|\Z)',
        block,
        flags=re.DOTALL,
    )

    assert lock_object_statement is not None
    statement = lock_object_statement.group(0)
    assert '"s3:DeleteObject"' in statement
    assert "local.terraform_lock_object_arn" in statement


def test_plan_actions_contain_no_wildcards() -> None:
    """Plan authorization actions must be fully explicit."""
    actions = quoted_actions(extract_policy_document_block("terraform_plan_access"))

    assert actions
    assert all("*" not in action for action in actions)


def test_plan_source_contains_no_forbidden_mutation_actions() -> None:
    """Plan authorization must exclude mutation-oriented IAM actions."""
    block = extract_policy_document_block("terraform_plan_access")

    assert FORBIDDEN_PLAN_ACTION_PATTERN.search(block) is None


def test_plan_source_contains_no_state_object_or_key_references() -> None:
    """The plan role must not receive Terraform state or lock access."""
    block = extract_policy_document_block("terraform_plan_access")

    for forbidden in (
        "terraform_state_object_arn",
        "terraform_lock_object_arn",
        "terraform_state_key",
        "terraform_lock_key",
        "terraform_state_bucket",
        "tfstate",
        ".tflock",
    ):
        assert forbidden not in block


def test_bootstrap_does_not_attach_broad_aws_managed_policies() -> None:
    """Broad AWS-managed policies must not appear in this root."""
    source = terraform_source()

    for policy_name in (
        "ReadOnlyAccess",
        "AdministratorAccess",
        "PowerUserAccess",
    ):
        assert policy_name not in source


def test_bootstrap_does_not_grant_pass_role() -> None:
    """iam:PassRole must remain absent from authorization policies."""
    source = terraform_source()

    assert "iam:PassRole" not in source
    assert "PassRole" not in extract_policy_document_block("terraform_plan_access")


def test_bootstrap_does_not_grant_lambda_invocation() -> None:
    """Plan authorization must not invoke application Lambda functions."""
    plan_block = extract_policy_document_block("terraform_plan_access")

    assert "lambda:Invoke" not in plan_block
    assert "InvokeFunction" not in plan_block


def test_bootstrap_does_not_grant_sqs_data_plane_actions() -> None:
    """Plan authorization must not read or mutate SQS message payloads."""
    plan_actions = quoted_actions(
        extract_policy_document_block("terraform_plan_access")
    )

    forbidden = {
        action
        for action in plan_actions
        if action
        in {
            "sqs:ReceiveMessage",
            "sqs:SendMessage",
            "sqs:DeleteMessage",
            "sqs:ChangeMessageVisibility",
            "sqs:PurgeQueue",
            "sqs:StartMessageMoveTask",
        }
    }
    assert forbidden == set()


def test_bootstrap_does_not_grant_dynamodb_item_reads() -> None:
    """Plan authorization must stay on DynamoDB table metadata only."""
    plan_actions = quoted_actions(
        extract_policy_document_block("terraform_plan_access")
    )

    forbidden = {
        action
        for action in plan_actions
        if action
        in {
            "dynamodb:GetItem",
            "dynamodb:BatchGetItem",
            "dynamodb:Query",
            "dynamodb:Scan",
        }
    }
    assert forbidden == set()
    assert PLAN_DATA_PLANE_ACTIONS.isdisjoint(plan_actions)


def test_exact_dev_state_and_lock_derivation() -> None:
    """State and lock object keys must follow the committed development contract."""
    locals_source = read_bootstrap_file("locals.tf")
    variables_source = read_bootstrap_file("variables.tf")

    assert (
        'default     = "clouddoc/dev/terraform.tfstate"' in variables_source
        or 'default = "clouddoc/dev/terraform.tfstate"' in variables_source
    )
    assert 'terraform_lock_key = "${var.terraform_state_key}.tflock"' in locals_source
    assert "local.terraform_state_object_arn" in locals_source or (
        "terraform_state_object_arn" in locals_source
    )
    assert "local.terraform_lock_object_arn" in locals_source or (
        "terraform_lock_object_arn" in locals_source
    )


def test_example_tfvars_uses_placeholders_only() -> None:
    """Committed example values must never contain real AWS identifiers."""
    source = read_bootstrap_file("terraform.tfvars.example")

    assert 'aws_account_id = "REPLACE_WITH_12_DIGIT_AWS_ACCOUNT_ID"' in source
    assert (
        "terraform_state_bucket_name = "
        '"clouddoc-REPLACE_WITH_12_DIGIT_AWS_ACCOUNT_ID-terraform-state"' in source
    )
    assert re.search(r'"\d{12}"', source) is None
    assert "arn:aws:" not in source
    assert "AKIA" not in source
    assert "secret" not in source.lower()


def test_outputs_do_not_expose_policy_json_or_credentials() -> None:
    """Outputs must expose operational identifiers only."""
    source = read_bootstrap_file("outputs.tf").lower()

    assert "policy" not in source
    assert "json" not in source
    assert "access_key" not in source
    assert "secret" not in source
    assert "credential" not in source
    assert "session_token" not in source
