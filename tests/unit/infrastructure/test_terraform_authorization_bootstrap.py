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
    "README.md",
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
EXPECTED_TERRAFORM_TEST_FILES = {"terraform_authorization.tftest.hcl"}
EXPECTED_RESOURCES = {
    ("aws_iam_role", "terraform_state"),
    ("aws_iam_role", "terraform_plan"),
    ("aws_iam_role", "terraform_apply"),
    ("aws_iam_role_policy", "terraform_state_access"),
    ("aws_iam_role_policy", "terraform_plan_access"),
    ("aws_iam_role_policy", "terraform_apply_access"),
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
API_GATEWAY_ACCESS_LOG_DELIVERY_ACTIONS = {
    "logs:CreateLogDelivery",
    "logs:DeleteLogDelivery",
    "logs:DescribeResourcePolicies",
    "logs:GetLogDelivery",
    "logs:ListLogDeliveries",
    "logs:PutResourcePolicy",
    "logs:UpdateLogDelivery",
}
FORBIDDEN_APIGATEWAY_NOMINAL_TAG_ACTIONS = {
    "apigateway:TagResource",
    "apigateway:UntagResource",
}
FORBIDDEN_LOGS_DELIVERY_EXTRAS = {
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents",
    "logs:DescribeLogStreams",
    "logs:GetLogEvents",
    "logs:FilterLogEvents",
    "logs:*",
}
FORBIDDEN_APPLY_ACTIONS = {
    "lambda:InvokeFunction",
    "lambda:InvokeAsync",
    "execute-api:Invoke",
    "s3:GetObject",
    "s3:PutObject",
    "s3:DeleteObject",
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:Query",
    "dynamodb:Scan",
    "sqs:SendMessage",
    "sqs:ReceiveMessage",
    "sqs:DeleteMessage",
    "sqs:ChangeMessageVisibility",
    "sqs:PurgeQueue",
    "bedrock:InvokeModel",
    "kms:Decrypt",
    "kms:Encrypt",
    "secretsmanager:GetSecretValue",
    "iam:CreateAccessKey",
    "iam:AttachRolePolicy",
    "iam:CreatePolicy",
}


def read_bootstrap_file(relative_path: str) -> str:
    """Read one UTF-8 Terraform authorization bootstrap file."""
    return (BOOTSTRAP_ROOT / relative_path).read_text(encoding="utf-8")


def terraform_source() -> str:
    """Return all root Terraform source as one searchable string."""
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(BOOTSTRAP_ROOT.glob("*.tf"))
    )


def extract_named_block(source: str, header: str) -> str:
    """Extract one top-level HCL block body by exact header."""
    start = source.find(header)
    assert start >= 0, f"missing block {header}"

    brace_start = source.find("{", start)
    assert brace_start >= 0, f"missing opening brace for {header}"

    depth = 0
    for index in range(brace_start, len(source)):
        character = source[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start + 1 : index]

    raise AssertionError(f"unbalanced braces for {header}")


def extract_policy_document_block(name: str) -> str:
    """Return the HCL body for one named aws_iam_policy_document data source."""
    return extract_named_block(
        terraform_source(),
        f'data "aws_iam_policy_document" "{name}"',
    )


def quoted_actions(block: str) -> set[str]:
    """Extract quoted IAM action strings from one policy body."""
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


def test_bootstrap_owns_exactly_the_reviewed_iam_resources() -> None:
    """Authorization bootstrap must manage only the reviewed IAM resources."""
    actual_resources = set(
        re.findall(
            r'resource\s+"([^"]+)"\s+"([^"]+)"',
            terraform_source(),
        )
    )

    assert actual_resources == EXPECTED_RESOURCES
    assert len(actual_resources) == 6


def test_bootstrap_declares_exactly_three_roles_and_three_inline_policies() -> None:
    """The bootstrap should expose exactly three roles and three inline policies."""
    source = terraform_source()

    assert set(re.findall(r'resource\s+"aws_iam_role"\s+"([^"]+)"', source)) == {
        "terraform_state",
        "terraform_plan",
        "terraform_apply",
    }
    assert set(re.findall(r'resource\s+"aws_iam_role_policy"\s+"([^"]+)"', source)) == {
        "terraform_state_access",
        "terraform_plan_access",
        "terraform_apply_access",
    }


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
        r'terraform_state_role_name\s*=\s*"clouddoc-dev-terraform-state"', locals_source
    )
    assert re.search(
        r'terraform_plan_role_name\s*=\s*"clouddoc-dev-terraform-plan"', locals_source
    )
    assert re.search(
        r'terraform_apply_role_name\s*=\s*"clouddoc-dev-terraform-apply"', locals_source
    )
    assert re.search(r"name\s*=\s*local\.terraform_state_role_name", roles_source)
    assert re.search(r"name\s*=\s*local\.terraform_plan_role_name", roles_source)
    assert re.search(r"name\s*=\s*local\.terraform_apply_role_name", roles_source)


def test_deploy_identity_variable_and_arn_derivation_are_exact() -> None:
    """The deploy identity input and ARN must remain same-account and exact."""
    variables_source = read_bootstrap_file("variables.tf")
    locals_source = read_bootstrap_file("locals.tf")

    assert 'variable "github_deploy_identity_role_name"' in variables_source
    assert 'default     = "clouddoc-dev-github-deploy-identity"' in variables_source
    assert (
        "${var.project_name}-${var.environment}-github-deploy-identity"
        in variables_source
    )
    assert (
        "arn:${data.aws_partition.current.partition}:iam::"
        "${var.aws_account_id}:role/${var.github_deploy_identity_role_name}"
        in " ".join(locals_source.split())
    )


def test_state_trust_uses_the_reviewed_two_principal_local() -> None:
    """The state role must trust exactly the plan and deploy identity ARNs."""
    locals_source = read_bootstrap_file("locals.tf")
    assume_state = extract_policy_document_block("terraform_state_assume_role")

    assert "terraform_state_trusted_identity_role_arns = sort([" in locals_source
    assert "local.github_identity_role_arn" in locals_source
    assert "local.github_deploy_identity_role_arn" in locals_source
    assert (
        "identifiers = local.terraform_state_trusted_identity_role_arns" in assume_state
    )


def test_plan_and_apply_trusts_remain_singular_and_same_account() -> None:
    """Plan must trust only the plan identity and apply only the deploy identity."""
    assume_plan = extract_policy_document_block("terraform_plan_assume_role")
    assume_apply = extract_policy_document_block("terraform_apply_assume_role")

    assert "local.github_identity_role_arn" in assume_plan
    assert "local.github_deploy_identity_role_arn" not in assume_plan
    assert "local.github_deploy_identity_role_arn" in assume_apply
    assert "local.github_identity_role_arn" not in assume_apply


def test_trust_policies_exclude_wildcard_root_and_federated_principals() -> None:
    """Authorization trusts must not add wildcard, root, or direct OIDC trust."""
    for name in (
        "terraform_state_assume_role",
        "terraform_plan_assume_role",
        "terraform_apply_assume_role",
    ):
        block = extract_policy_document_block(name)
        assert ":root" not in block
        assert "oidc-provider" not in block
        assert "AssumeRoleWithWebIdentity" not in block
        assert 'type = "Service"' not in block


def test_state_policy_remains_exact() -> None:
    """State authorization must stay inside the reviewed S3 action set."""
    block = extract_policy_document_block("terraform_state_access")
    actions = quoted_actions(block)

    assert actions == STATE_POLICY_ACTIONS
    assert all(action.startswith("s3:") for action in actions)
    assert '"s3:DeleteObject"' not in re.search(
        r'sid\s*=\s*"ReadWriteExactStateObject".*?(?=sid\s*=|\Z)',
        block,
        flags=re.DOTALL,
    ).group(0)
    assert "local.terraform_lock_object_arn" in re.search(
        r'sid\s*=\s*"ManageExactLockObject".*?(?=sid\s*=|\Z)',
        block,
        flags=re.DOTALL,
    ).group(0)


def test_plan_policy_remains_read_only_and_state_free() -> None:
    """Plan authorization must exclude mutation, PassRole, and state access."""
    block = extract_policy_document_block("terraform_plan_access")
    actions = quoted_actions(block)

    assert actions
    assert all("*" not in action for action in actions)
    assert FORBIDDEN_PLAN_ACTION_PATTERN.search(block) is None
    assert "iam:PassRole" not in block
    assert PLAN_DATA_PLANE_ACTIONS.isdisjoint(actions)
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


def test_apply_policy_is_separate_service_specific_and_explicit() -> None:
    """Apply authorization must use a dedicated reviewed policy document."""
    policies_source = read_bootstrap_file("policies.tf")
    roles_source = read_bootstrap_file("roles.tf")
    apply_block = extract_policy_document_block("terraform_apply_access")

    assert 'data "aws_iam_policy_document" "terraform_apply_access"' in policies_source
    assert 'resource "aws_iam_role_policy" "terraform_apply_access"' in policies_source
    assert "aws_iam_role.terraform_apply" in policies_source
    assert "data.aws_iam_policy_document.terraform_apply_access.json" in policies_source
    assert (
        "data.aws_iam_policy_document.terraform_apply_assume_role.json" in roles_source
    )
    assert '"NotAction"' not in apply_block
    assert '"NotResource"' not in apply_block
    assert all("*" not in action for action in quoted_actions(apply_block))


def test_apply_policy_excludes_terraform_state_and_data_plane_actions() -> None:
    """Apply authorization must stay out of Terraform state and application payloads."""
    apply_block = extract_policy_document_block("terraform_apply_access")

    for forbidden in (
        "terraform_state_bucket_name",
        "terraform_state_bucket_arn",
        "terraform_state_object_arn",
        "terraform_lock_object_arn",
        "terraform_state_key",
        "terraform_lock_key",
        "tfstate",
        ".tflock",
    ):
        assert forbidden not in apply_block

    assert FORBIDDEN_APPLY_ACTIONS.isdisjoint(quoted_actions(apply_block))


def test_apply_policy_derives_exact_lambda_role_arns_and_single_passrole() -> None:
    """PassRole must target only the four exact Lambda execution roles."""
    locals_source = read_bootstrap_file("locals.tf")
    apply_block = extract_policy_document_block("terraform_apply_access")

    for expected in (
        (
            "create_job_role_arn              = "
            '"arn:${data.aws_partition.current.partition}:iam::'
            '${var.aws_account_id}:role/${local.create_job_role_name}"'
        ),
        (
            "get_job_role_arn                 = "
            '"arn:${data.aws_partition.current.partition}:iam::'
            '${var.aws_account_id}:role/${local.get_job_role_name}"'
        ),
        (
            "processor_role_arn               = "
            '"arn:${data.aws_partition.current.partition}:iam::'
            '${var.aws_account_id}:role/${local.processor_role_name}"'
        ),
        (
            "dead_letter_reconciler_role_arn  = "
            '"arn:${data.aws_partition.current.partition}:iam::'
            '${var.aws_account_id}:role/${local.dead_letter_reconciler_role_name}"'
        ),
    ):
        assert expected in locals_source

    assert apply_block.count("iam:PassRole") == 1
    assert "resources = local.lambda_execution_role_arns" in apply_block
    assert 'variable = "iam:PassedToService"' in apply_block
    assert '"lambda.amazonaws.com"' in apply_block


def test_bootstrap_does_not_attach_broad_aws_managed_policies() -> None:
    """Broad AWS-managed policies must not appear in this root."""
    source = terraform_source()

    for policy_name in ("ReadOnlyAccess", "AdministratorAccess", "PowerUserAccess"):
        assert policy_name not in source


def test_exact_dev_state_and_lock_derivation() -> None:
    """State and lock object keys must follow the committed development contract."""
    locals_source = read_bootstrap_file("locals.tf")
    variables_source = read_bootstrap_file("variables.tf")

    assert 'default     = "clouddoc/dev/terraform.tfstate"' in variables_source
    assert 'terraform_lock_key = "${var.terraform_state_key}.tflock"' in locals_source
    assert "terraform_state_object_arn" in locals_source
    assert "terraform_lock_object_arn" in locals_source


def test_outputs_expose_apply_role_and_trust_boundaries_only() -> None:
    """Outputs must publish identifiers, not policy JSON or credentials."""
    source = read_bootstrap_file("outputs.tf")
    lowered = source.lower()

    for output_name in (
        "terraform_apply_role_name",
        "terraform_apply_role_arn",
        "terraform_apply_role_max_session_duration",
        "github_deploy_identity_role_arn",
        "terraform_state_trusted_identity_role_arns",
        "terraform_apply_trusted_identity_role_arn",
        "lambda_execution_role_arns",
    ):
        assert f'output "{output_name}"' in source

    assert "json" not in lowered
    assert "access_key" not in lowered
    assert "secret" not in lowered
    assert "credential" not in lowered
    assert "session_token" not in lowered


def test_example_tfvars_uses_placeholders_and_only_the_deploy_role_name() -> None:
    """Committed example values must never contain real AWS identifiers or ARNs."""
    source = read_bootstrap_file("terraform.tfvars.example")

    assert 'aws_account_id = "REPLACE_WITH_12_DIGIT_AWS_ACCOUNT_ID"' in source
    assert (
        "terraform_state_bucket_name = "
        '"clouddoc-REPLACE_WITH_12_DIGIT_AWS_ACCOUNT_ID-terraform-state"' in source
    )
    assert (
        'github_deploy_identity_role_name = "clouddoc-dev-github-deploy-identity"'
        in source
    )
    assert "github_identity_role_name" not in source
    assert re.search(r'"\d{12}"', source) is None
    assert "arn:aws:" not in source
    assert "AKIA" not in source
    assert "secret" not in source.lower()


def test_apply_policy_uses_valid_s3_lifecycle_and_put_control_plane_actions() -> None:
    """Apply S3 auth must use valid lifecycle and Put* control-plane actions."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    actions = quoted_actions(apply_block)

    assert "s3:GetLifecycleConfiguration" in actions
    assert "s3:GetBucketLifecycleConfiguration" not in actions
    assert "s3:PutLifecycleConfiguration" in actions
    assert {
        "s3:DeleteBucketEncryption",
        "s3:DeleteBucketOwnershipControls",
        "s3:DeleteBucketTagging",
        "s3:DeleteBucketPublicAccessBlock",
    }.isdisjoint(actions)
    assert {
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketPublicAccessBlock",
        "s3:PutBucketTagging",
        "s3:PutEncryptionConfiguration",
        "s3:PutLifecycleConfiguration",
    }.issubset(actions)


def test_plan_policy_uses_valid_s3_lifecycle_configuration_action() -> None:
    """Plan S3 auth must use GetLifecycleConfiguration on the documents bucket only."""
    plan_block = extract_policy_document_block("terraform_plan_access")
    apply_block = extract_policy_document_block("terraform_apply_access")
    actions = quoted_actions(plan_block)
    statement = re.search(
        r'sid\s*=\s*"ReadDocumentsBucketConfiguration".*?(?=sid\s*=|\Z)',
        plan_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    statement_body = statement.group(0)
    statement_actions = quoted_actions(statement_body)

    assert "s3:GetLifecycleConfiguration" in actions
    assert "s3:GetBucketLifecycleConfiguration" not in actions
    assert "s3:GetLifecycleConfiguration" in statement_actions
    assert "s3:GetBucketLifecycleConfiguration" not in statement_actions
    assert "local.documents_bucket_arn" in statement_body
    assert '"*"' not in re.search(
        r"resources\s*=\s*\[.*?\]",
        statement_body,
        flags=re.DOTALL,
    ).group(0)
    assert FORBIDDEN_PLAN_ACTION_PATTERN.search(plan_block) is None
    assert "iam:PassRole" not in plan_block
    for forbidden in (
        "terraform_state_object_arn",
        "terraform_lock_object_arn",
        "terraform_state_key",
        "terraform_lock_key",
        "terraform_state_bucket",
        "tfstate",
        ".tflock",
    ):
        assert forbidden not in plan_block
    assert "s3:GetLifecycleConfiguration" in quoted_actions(apply_block)
    assert "s3:GetBucketLifecycleConfiguration" not in quoted_actions(apply_block)
    assert "s3:PutLifecycleConfiguration" in quoted_actions(apply_block)


def test_application_log_group_arns_remain_bare_tagging_form() -> None:
    """Tagging ARNs must be bare log-group names without a trailing :*."""
    locals_source = read_bootstrap_file("locals.tf")
    match = re.search(
        r"application_log_group_arns\s*=\s*\[(.*?)\]",
        locals_source,
        flags=re.DOTALL,
    )
    assert match is not None
    list_body = match.group(1)
    arn_entries = re.findall(r'"([^"]+)"', list_body)

    assert len(arn_entries) == 5
    assert all(not entry.endswith(":*") for entry in arn_entries)
    assert "*" not in arn_entries
    assert all(":log-group:" in entry for entry in arn_entries)
    assert sum("/aws/lambda/" in entry for entry in arn_entries) == 4
    assert "local.control_plane_api_access_log_group_name" in list_body
    assert (
        'control_plane_api_access_log_group_name = "/aws/apigateway/' in locals_source
    )


def test_application_log_group_management_arns_derive_suffixed_form() -> None:
    """Management ARNs must append :* from the bare tagging local only."""
    locals_source = read_bootstrap_file("locals.tf")
    apply_block = extract_policy_document_block("terraform_apply_access")
    plan_block = extract_policy_document_block("terraform_plan_access")

    assert "application_log_group_management_arns" in locals_source
    assert re.search(
        r"application_log_group_management_arns\s*=\s*\[\s*"
        r"for\s+arn\s+in\s+local\.application_log_group_arns\s*:\s*"
        r'"\$\{arn\}:\*"\s*\]',
        locals_source,
        flags=re.DOTALL,
    )
    assert '"*"' not in re.search(
        r"application_log_group_management_arns\s*=\s*\[.*?\]",
        locals_source,
        flags=re.DOTALL,
    ).group(0)

    plan_tags = re.search(
        r'sid\s*=\s*"ReadCloudWatchLogGroupTags".*?(?=sid\s*=|\Z)',
        plan_block,
        flags=re.DOTALL,
    )
    assert plan_tags is not None
    plan_tags_body = plan_tags.group(0)
    assert '"logs:ListTagsForResource"' in plan_tags_body
    assert "resources = local.application_log_group_arns" in plan_tags_body
    assert "application_log_group_management_arns" not in plan_tags_body
    assert quoted_actions(plan_tags_body) == {"logs:ListTagsForResource"}
    assert 'resources = ["*"]' not in plan_tags_body

    manage_logs = re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroups".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert manage_logs is not None
    manage_logs_body = manage_logs.group(0)
    assert "resources = local.application_log_group_management_arns" in manage_logs_body
    assert "resources = local.application_log_group_arns" not in manage_logs_body
    assert 'resources = ["*"]' not in manage_logs_body
    assert quoted_actions(manage_logs_body) == {
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:DeleteRetentionPolicy",
        "logs:PutRetentionPolicy",
    }
    assert "logs:ListTagsForResource" not in quoted_actions(manage_logs_body)
    assert "logs:TagResource" not in quoted_actions(manage_logs_body)
    assert "logs:UntagResource" not in quoted_actions(manage_logs_body)

    manage_tags = re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroupTags".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert manage_tags is not None
    manage_tags_body = manage_tags.group(0)
    assert "resources = local.application_log_group_arns" in manage_tags_body
    assert "application_log_group_management_arns" not in manage_tags_body
    assert 'resources = ["*"]' not in manage_tags_body
    assert quoted_actions(manage_tags_body) == {
        "logs:ListTagsForResource",
        "logs:TagResource",
        "logs:UntagResource",
    }


def test_apply_cloudwatch_log_group_statements_keep_bare_versus_management_arns() -> (
    None
):
    """Apply must separate management (:*) from tagging (bare) log-group ARNs."""
    apply_block = extract_policy_document_block("terraform_apply_access")

    manage_logs_body = re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroups".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    ).group(0)
    manage_tags_body = re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroupTags".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    ).group(0)

    assert "resources = local.application_log_group_management_arns" in manage_logs_body
    assert "resources = local.application_log_group_arns" in manage_tags_body
    assert 'resources = ["*"]' not in manage_logs_body
    assert 'resources = ["*"]' not in manage_tags_body
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*\]', manage_logs_body) is None
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*\]', manage_tags_body) is None
    assert "logs:ListTagsForResource" not in quoted_actions(manage_logs_body)
    assert {"logs:TagResource", "logs:UntagResource"}.isdisjoint(
        quoted_actions(manage_logs_body)
    )
    assert quoted_actions(manage_tags_body) == {
        "logs:ListTagsForResource",
        "logs:TagResource",
        "logs:UntagResource",
    }


def test_apply_policy_includes_encoded_api_gateway_tag_resource() -> None:
    """Tagged CreateApi must authorize the encoded /v2/apis/* tag resource."""
    locals_source = read_bootstrap_file("locals.tf")
    apply_block = extract_policy_document_block("terraform_apply_access")
    api_gateway_statement = re.search(
        r'sid\s*=\s*"ManageApiGatewayV2ControlPlane".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert api_gateway_statement is not None
    api_gateway_body = api_gateway_statement.group(0)

    assert "application_apigateway_api_tag_resource" in locals_source
    assert "%2Fv2%2Fapis%2F*" in locals_source
    assert "local.application_apigateway_api_tag_resource" in api_gateway_body
    assert 'resources = ["*"]' not in api_gateway_body
    assert 'resources = ["*"]' not in re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroups".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    ).group(0)
    assert 'resources = ["*"]' not in re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroupTags".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    ).group(0)
    for expected_resource in (
        "local.application_apigateway_apis_resource",
        "local.application_apigateway_api_resource_prefix",
        "local.application_apigateway_integrations_resource",
        "local.application_apigateway_integration_resource_prefix",
        "local.application_apigateway_routes_resource",
        "local.application_apigateway_route_resource_prefix",
        "local.application_apigateway_stages_resource",
        "local.application_apigateway_stage_resource_prefix",
        "local.application_apigateway_api_tag_resource",
        "local.application_apigateway_stage_tag_resource",
    ):
        assert expected_resource in api_gateway_body


def test_encoded_api_gateway_stage_tag_resource_is_exact() -> None:
    """Stage TagResource must use the encoded /v2/apis/*/stages/* tag shape."""
    locals_source = read_bootstrap_file("locals.tf")
    apply_block = extract_policy_document_block("terraform_apply_access")
    api_gateway_body = re.search(
        r'sid\s*=\s*"ManageApiGatewayV2ControlPlane".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    ).group(0)

    assert "application_apigateway_stage_tag_resource" in locals_source
    assert "%2Fv2%2Fapis%2F*%2Fstages%2F*" in locals_source, (
        "stage tag local must encode /v2/apis/*/stages/*"
    )
    assert "application_apigateway_api_tag_resource" in locals_source
    assert "%2Fv2%2Fapis%2F*" in locals_source
    assert "local.application_apigateway_api_tag_resource" in api_gateway_body
    assert "local.application_apigateway_stage_tag_resource" in api_gateway_body
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*\]', api_gateway_body) is None
    assert "/tags/*" not in api_gateway_body
    assert quoted_actions(api_gateway_body) == {
        "apigateway:DELETE",
        "apigateway:GET",
        "apigateway:PATCH",
        "apigateway:POST",
    }
    assert "apigateway:PUT" not in quoted_actions(api_gateway_body)
    assert "execute-api:Invoke" not in quoted_actions(api_gateway_body)


def test_complete_tagged_api_gateway_stage_creation_uses_put_on_stages_and_tag() -> (
    None
):
    """Tagged CreateStage needs PUT on Stages collection and Stage tag."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    put_body = re.search(
        r'sid\s*=\s*"CompleteTaggedApiGatewayV2StageCreation".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    manage_body = re.search(
        r'sid\s*=\s*"ManageApiGatewayV2ControlPlane".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert put_body is not None
    assert manage_body is not None
    put_statement = put_body.group(0)
    manage_statement = manage_body.group(0)

    assert quoted_actions(put_statement) == {"apigateway:PUT"}
    assert "apigateway:PUT" not in quoted_actions(manage_statement)
    assert quoted_actions(manage_statement) == {
        "apigateway:DELETE",
        "apigateway:GET",
        "apigateway:PATCH",
        "apigateway:POST",
    }
    assert "local.application_apigateway_stages_resource" in put_statement
    assert "local.application_apigateway_stage_tag_resource" in put_statement
    assert "local.application_apigateway_api_tag_resource" not in put_statement
    assert "/tags/*" not in put_statement
    assert "application_apigateway_stage_resource_prefix" not in put_statement
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', put_statement) is None
    assert "execute-api:Invoke" not in quoted_actions(put_statement)
    assert "condition" not in put_statement
    assert len(re.findall(r"local\.application_apigateway_\w+", put_statement)) == 2
    resources_match = re.search(
        r"resources\s*=\s*\[(.*?)\]",
        put_statement,
        flags=re.DOTALL,
    )
    assert resources_match is not None
    resources_body = resources_match.group(1)
    assert resources_body.index(
        "application_apigateway_stages_resource"
    ) < resources_body.index("application_apigateway_stage_tag_resource")


def test_apply_policy_excludes_invalid_apigateway_nominal_tag_actions() -> None:
    """Stage tagging must use HTTP-method actions only, not nominal TagResource."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    apply_actions = quoted_actions(apply_block)

    assert "ManageApiGatewayV2StageTags" not in apply_block
    assert FORBIDDEN_APIGATEWAY_NOMINAL_TAG_ACTIONS.isdisjoint(apply_actions)


def test_manage_api_gateway_access_log_delivery_statement_is_exact() -> None:
    """HTTP API access logging needs CloudWatch Logs delivery control-plane actions."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    delivery_body = re.search(
        r'sid\s*=\s*"ManageApiGatewayAccessLogDelivery".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    log_groups_body = re.search(
        r'sid\s*=\s*"ManageCloudWatchLogGroups".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert delivery_body is not None
    assert log_groups_body is not None
    delivery_statement = delivery_body.group(0)
    log_groups_statement = log_groups_body.group(0)

    assert quoted_actions(delivery_statement) == API_GATEWAY_ACCESS_LOG_DELIVERY_ACTIONS
    assert (
        re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', delivery_statement)
        is not None
    )
    assert "condition" not in delivery_statement
    assert FORBIDDEN_LOGS_DELIVERY_EXTRAS.isdisjoint(quoted_actions(delivery_statement))
    assert "logs:CreateLogGroup" in quoted_actions(log_groups_statement)
    assert "logs:CreateLogGroup" not in quoted_actions(delivery_statement)
    assert "local.application_log_group_management_arns" in log_groups_statement
    assert "local.application_log_group_management_arns" not in delivery_statement


def test_api_gateway_http_method_statements_remain_exact_after_tag_removal() -> None:
    """Control plane and tagged Stage creation keep the reviewed HTTP-method model."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    manage_body = re.search(
        r'sid\s*=\s*"ManageApiGatewayV2ControlPlane".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    put_body = re.search(
        r'sid\s*=\s*"CompleteTaggedApiGatewayV2StageCreation".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert manage_body is not None
    assert put_body is not None
    manage_statement = manage_body.group(0)
    put_statement = put_body.group(0)

    assert quoted_actions(manage_statement) == {
        "apigateway:DELETE",
        "apigateway:GET",
        "apigateway:PATCH",
        "apigateway:POST",
    }
    assert quoted_actions(put_statement) == {"apigateway:PUT"}
    assert "local.application_apigateway_stages_resource" in put_statement
    assert "local.application_apigateway_stage_tag_resource" in put_statement
    assert FORBIDDEN_APIGATEWAY_NOMINAL_TAG_ACTIONS.isdisjoint(
        quoted_actions(apply_block)
    )


def test_lambda_permission_lifecycle_covers_control_plane_functions() -> None:
    """Add/Get/Remove must cover create-job and get-job without InvokeFunction."""
    locals_source = read_bootstrap_file("locals.tf")
    apply_block = extract_policy_document_block("terraform_apply_access")
    permissions_body = re.search(
        r'sid\s*=\s*"ManageLambdaPermissions".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert permissions_body is not None
    body = permissions_body.group(0)

    assert quoted_actions(body) == {
        "lambda:AddPermission",
        "lambda:GetPolicy",
        "lambda:RemovePermission",
    }
    assert "resources = local.application_lambda_function_arns" in body
    assert "create_job_function_name" in locals_source
    assert "get_job_function_name" in locals_source
    function_arns = re.search(
        r"application_lambda_function_arns\s*=\s*\[(.*?)\]",
        locals_source,
        flags=re.DOTALL,
    )
    assert function_arns is not None
    arns_body = function_arns.group(1)
    assert "create_job_function_name" in arns_body
    assert "get_job_function_name" in arns_body
    assert "processor_function_name" in arns_body
    assert "dead_letter_reconciler_function_name" in arns_body
    assert arns_body.count("function:${local.") == 4
    assert "lambda:InvokeFunction" not in quoted_actions(apply_block)
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is None


def test_cloudwatch_dashboard_lifecycle_is_exact_and_untagged() -> None:
    """Dashboard Get/Put/Delete uses the exact ARN; ListDashboards stays on *."""
    application_observability = (
        APPLICATION_TERRAFORM_ROOT / "observability.tf"
    ).read_text(encoding="utf-8")
    dashboard_resource = extract_named_block(
        application_observability,
        'resource "aws_cloudwatch_dashboard" "operations"',
    )
    assert "tags" not in dashboard_resource

    apply_block = extract_policy_document_block("terraform_apply_access")
    list_body = re.search(
        r'sid\s*=\s*"ListCloudWatchDashboards".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    manage_body = re.search(
        r'sid\s*=\s*"ManageCloudWatchDashboard".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert list_body is not None
    assert manage_body is not None
    list_statement = list_body.group(0)
    manage_statement = manage_body.group(0)

    assert quoted_actions(list_statement) == {"cloudwatch:ListDashboards"}
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', list_statement) is not None
    assert "condition" not in list_statement
    assert quoted_actions(manage_statement) == {
        "cloudwatch:DeleteDashboards",
        "cloudwatch:GetDashboard",
        "cloudwatch:PutDashboard",
    }
    assert "local.operations_dashboard_arn" in manage_statement
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', manage_statement) is None
    assert {
        "cloudwatch:ListTagsForResource",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource",
    }.isdisjoint(quoted_actions(manage_statement))


def test_cloudwatch_alarm_lifecycle_and_wildcard_reads_are_separated() -> None:
    """Alarm CRUD/tagging uses the alarm ARN prefix; metric describe stays on *."""
    application_observability = (
        APPLICATION_TERRAFORM_ROOT / "observability.tf"
    ).read_text(encoding="utf-8")
    alarm_resource = extract_named_block(
        application_observability,
        'resource "aws_cloudwatch_metric_alarm" "control_plane_5xx"',
    )
    assert "tags" in alarm_resource
    assert "alarm_actions" not in alarm_resource
    assert "ok_actions" not in alarm_resource
    assert "insufficient_data_actions" not in alarm_resource

    apply_block = extract_policy_document_block("terraform_apply_access")
    describe_body = re.search(
        r'sid\s*=\s*"DescribeCloudWatchAlarmMetrics".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    manage_body = re.search(
        r'sid\s*=\s*"ManageCloudWatchAlarms".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert describe_body is not None
    assert manage_body is not None
    describe_statement = describe_body.group(0)
    manage_statement = manage_body.group(0)

    assert quoted_actions(describe_statement) == {
        "cloudwatch:DescribeAlarmsForMetric",
    }
    assert (
        re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', describe_statement)
        is not None
    )
    assert "condition" not in describe_statement
    assert quoted_actions(manage_statement) == {
        "cloudwatch:DeleteAlarms",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:ListTagsForResource",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource",
    }
    assert "local.application_alarm_arn_prefix" in manage_statement
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', manage_statement) is None
    assert {
        "cloudwatch:SetAlarmState",
        "cloudwatch:EnableAlarmActions",
        "cloudwatch:DisableAlarmActions",
    }.isdisjoint(quoted_actions(apply_block))


def test_event_source_mapping_function_arns_are_exactly_two_consumers() -> None:
    """Event-source mapping FunctionArn must target only the two SQS consumers."""
    locals_source = read_bootstrap_file("locals.tf")
    local_block = extract_named_block(locals_source, "locals")
    mapping_functions = re.search(
        r"application_lambda_event_source_mapping_function_arns\s*=\s*sort\(\[(.*?)\]\)",
        local_block,
        flags=re.DOTALL,
    )
    assert mapping_functions is not None
    mapping_body = mapping_functions.group(1)

    assert "processor_function_name" in mapping_body
    assert "dead_letter_reconciler_function_name" in mapping_body
    assert "create_job_function_name" not in mapping_body
    assert "get_job_function_name" not in mapping_body
    assert "event-source-mapping" not in mapping_body
    assert ":sqs:" not in mapping_body
    assert "function:*" not in mapping_body
    assert mapping_body.count("function:${local.") == 2


def test_event_source_mapping_arn_prefix_is_restored_for_tag_apis_only() -> None:
    """Mapping ARN prefix must be account/region-scoped for tag APIs only."""
    locals_source = read_bootstrap_file("locals.tf")
    local_block = extract_named_block(locals_source, "locals")
    prefix_match = re.search(
        r"application_lambda_event_source_mapping_arn_prefix\s*=\s*\((.*?)\)",
        local_block,
        flags=re.DOTALL,
    )
    assert prefix_match is not None
    prefix_body = prefix_match.group(1)

    assert "event-source-mapping:*" in prefix_body
    assert "data.aws_partition.current.partition" in prefix_body
    assert "var.aws_region" in prefix_body
    assert "var.aws_account_id" in prefix_body
    assert ":function:" not in prefix_body
    assert ":sqs:" not in prefix_body
    assert '"*"' not in prefix_body
    assert "application_lambda_event_source_mapping_function_arns" in locals_source

    plan_block = extract_policy_document_block("terraform_plan_access")
    apply_block = extract_policy_document_block("terraform_apply_access")
    plan_tags = re.search(
        r'sid\s*=\s*"ReadLambdaEventSourceMappingTags".*?(?=sid\s*=|\Z)',
        plan_block,
        flags=re.DOTALL,
    )
    apply_tags = re.search(
        r'sid\s*=\s*"ManageLambdaEventSourceMappingTags".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    apply_mutate = re.search(
        r'sid\s*=\s*"ManageLambdaEventSourceMappings".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert plan_tags is not None
    assert apply_tags is not None
    assert apply_mutate is not None
    assert (
        "local.application_lambda_event_source_mapping_arn_prefix" in plan_tags.group(0)
    )
    assert (
        "local.application_lambda_event_source_mapping_arn_prefix"
        in apply_tags.group(0)
    )
    assert (
        "local.application_lambda_event_source_mapping_arn_prefix"
        not in apply_mutate.group(0)
    )


def test_plan_get_event_source_mapping_uses_service_required_star() -> None:
    """Plan GetEventSourceMapping must use Resource * with no conditions."""
    plan_block = extract_policy_document_block("terraform_plan_access")
    statement = re.search(
        r'sid\s*=\s*"ReadLambdaEventSourceMappings".*?(?=sid\s*=|\Z)',
        plan_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    body = statement.group(0)

    assert quoted_actions(body) == {"lambda:GetEventSourceMapping"}
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is not None
    assert "condition" not in body
    assert "application_lambda_event_source_mapping_arn_prefix" not in body
    assert FORBIDDEN_PLAN_ACTION_PATTERN.search(plan_block) is None
    assert "iam:PassRole" not in plan_block
    assert PLAN_DATA_PLANE_ACTIONS.isdisjoint(quoted_actions(plan_block))
    for forbidden in (
        "terraform_state_bucket_arn",
        "terraform_state_object_arn",
        "terraform_lock_object_arn",
    ):
        assert forbidden not in plan_block


def test_plan_list_tags_uses_only_event_source_mapping_arn_prefix() -> None:
    """Plan ListTags for mappings must use only the mapping ARN prefix."""
    plan_block = extract_policy_document_block("terraform_plan_access")
    statement = re.search(
        r'sid\s*=\s*"ReadLambdaEventSourceMappingTags".*?(?=sid\s*=|\Z)',
        plan_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    body = statement.group(0)

    assert quoted_actions(body) == {"lambda:ListTags"}
    assert (
        "resources = [\n      local.application_lambda_event_source_mapping_arn_prefix,"
        in body
        or "local.application_lambda_event_source_mapping_arn_prefix" in body
    )
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is None
    assert "condition" not in body
    assert "lambda:TagResource" not in quoted_actions(body)
    assert "lambda:UntagResource" not in quoted_actions(body)
    assert "lambda:CreateEventSourceMapping" not in quoted_actions(body)
    assert ":function:" not in body
    assert ":sqs:" not in body
    assert FORBIDDEN_PLAN_ACTION_PATTERN.search(plan_block) is None
    assert "iam:PassRole" not in plan_block
    assert PLAN_DATA_PLANE_ACTIONS.isdisjoint(quoted_actions(plan_block))
    for forbidden in (
        "terraform_state_bucket_arn",
        "terraform_state_object_arn",
        "terraform_lock_object_arn",
    ):
        assert forbidden not in plan_block


def test_apply_list_event_source_mappings_uses_star_without_conditions() -> None:
    """Apply ListEventSourceMappings must use Resource * with no conditions."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    statement = re.search(
        r'sid\s*=\s*"ListLambdaEventSourceMappings".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    body = statement.group(0)

    assert quoted_actions(body) == {"lambda:ListEventSourceMappings"}
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is not None
    assert "condition" not in body


def test_apply_get_event_source_mapping_uses_star_without_conditions() -> None:
    """Apply GetEventSourceMapping must use Resource * with no conditions."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    statement = re.search(
        r'sid\s*=\s*"ReadLambdaEventSourceMapping".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    body = statement.group(0)

    assert quoted_actions(body) == {"lambda:GetEventSourceMapping"}
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is not None
    assert "condition" not in body


def test_apply_event_source_mapping_mutation_uses_function_arn_condition() -> None:
    """Create/Delete/Update mappings must use * constrained by FunctionArn."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    statement = re.search(
        r'sid\s*=\s*"ManageLambdaEventSourceMappings".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    body = statement.group(0)

    assert quoted_actions(body) == {
        "lambda:CreateEventSourceMapping",
        "lambda:DeleteEventSourceMapping",
        "lambda:UpdateEventSourceMapping",
    }
    assert "lambda:GetEventSourceMapping" not in quoted_actions(body)
    assert "lambda:ListEventSourceMappings" not in quoted_actions(body)
    assert "lambda:ListTags" not in quoted_actions(body)
    assert "lambda:TagResource" not in quoted_actions(body)
    assert "lambda:UntagResource" not in quoted_actions(body)
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is not None
    assert body.count("condition") == 1
    assert 'test     = "ArnLike"' in body or 'test = "ArnLike"' in body
    assert 'variable = "lambda:FunctionArn"' in body
    assert (
        "values = local.application_lambda_event_source_mapping_function_arns" in body
    )
    assert "application_lambda_event_source_mapping_arn_prefix" not in body
    assert "create_job" not in body
    assert "get_job" not in body
    assert "lambda:InvokeFunction" not in quoted_actions(apply_block)
    assert {
        "sqs:ReceiveMessage",
        "sqs:SendMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:PurgeQueue",
    }.isdisjoint(quoted_actions(apply_block))


def test_apply_event_source_mapping_tags_use_mapping_arn_prefix() -> None:
    """Apply mapping tag APIs must use ListTags/Tag/Untag on the mapping ARN prefix."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    statement = re.search(
        r'sid\s*=\s*"ManageLambdaEventSourceMappingTags".*?(?=sid\s*=|\Z)',
        apply_block,
        flags=re.DOTALL,
    )
    assert statement is not None
    body = statement.group(0)

    assert quoted_actions(body) == {
        "lambda:ListTags",
        "lambda:TagResource",
        "lambda:UntagResource",
    }
    assert "lambda:GetEventSourceMapping" not in quoted_actions(body)
    assert "lambda:CreateEventSourceMapping" not in quoted_actions(body)
    assert "lambda:UpdateEventSourceMapping" not in quoted_actions(body)
    assert "lambda:DeleteEventSourceMapping" not in quoted_actions(body)
    assert "local.application_lambda_event_source_mapping_arn_prefix" in body
    assert re.search(r'resources\s*=\s*\[\s*"\*"\s*,?\s*\]', body) is None
    assert "condition" not in body
    assert ":function:" not in body
    assert ":sqs:" not in body
    assert "application_lambda_function_arns" not in body
    assert "application_sqs_queue_arns" not in body


def test_authorization_security_boundaries_remain_intact_after_apply_fix() -> None:
    """State, plan, data-plane, invocation, and PassRole boundaries must remain."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    plan_block = extract_policy_document_block("terraform_plan_access")
    state_block = extract_policy_document_block("terraform_state_access")
    apply_actions = quoted_actions(apply_block)
    locals_source = read_bootstrap_file("locals.tf")

    assert quoted_actions(state_block) == STATE_POLICY_ACTIONS
    assert FORBIDDEN_PLAN_ACTION_PATTERN.search(plan_block) is None
    assert "iam:PassRole" not in plan_block
    assert FORBIDDEN_APPLY_ACTIONS.isdisjoint(apply_actions)
    assert apply_block.count("iam:PassRole") == 1
    assert "resources = local.lambda_execution_role_arns" in apply_block
    assert 'variable = "iam:PassedToService"' in apply_block
    assert '"lambda.amazonaws.com"' in apply_block
    for forbidden in (
        "terraform_state_bucket_arn",
        "terraform_state_object_arn",
        "terraform_lock_object_arn",
        "tfstate",
        ".tflock",
    ):
        assert forbidden not in apply_block
    assert "aws_iam_policy_attachment" not in terraform_source()
    assert "permissions_boundary" not in terraform_source().lower()
    assert "bedrock:InvokeModel" not in apply_actions
    assert "lambda:InvokeFunction" not in apply_actions
    assert PLAN_DATA_PLANE_ACTIONS.isdisjoint(quoted_actions(plan_block))
    assert PLAN_DATA_PLANE_ACTIONS.isdisjoint(apply_actions)
    assert "s3:GetLifecycleConfiguration" in apply_actions
    assert "s3:GetBucketLifecycleConfiguration" not in apply_actions
    assert "application_apigateway_api_tag_resource" in locals_source
    assert "application_apigateway_stage_tag_resource" in locals_source
    assert "application_log_group_arns" in locals_source
    assert "application_log_group_management_arns" in locals_source
    assert "ReadLambdaEventSourceMapping" in apply_block
    assert "CompleteTaggedApiGatewayV2StageCreation" in apply_block
    assert "ManageApiGatewayAccessLogDelivery" in apply_block
    assert "ManageLambdaEventSourceMappingTags" in apply_block
    assert "ReadLambdaEventSourceMappingTags" in plan_block
    assert "application_lambda_event_source_mapping_function_arns" in locals_source
    assert "application_lambda_event_source_mapping_arn_prefix" in locals_source
    assert (
        len(re.findall(r"function:\$\{local\.\w+_function_name\}", locals_source)) >= 4
    )
    mapping_local = re.search(
        r"application_lambda_event_source_mapping_function_arns\s*=\s*sort\(\[(.*?)\]\)",
        locals_source,
        flags=re.DOTALL,
    )
    assert mapping_local is not None
    assert "create_job_function_name" not in mapping_local.group(1)
    assert "get_job_function_name" not in mapping_local.group(1)
