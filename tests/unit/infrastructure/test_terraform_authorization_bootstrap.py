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


def test_application_log_group_arns_use_create_log_group_resource_shape() -> None:
    """Log-group ARNs must end with :* for CreateLogGroup authorization."""
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
    assert all(entry.endswith(":*") for entry in arn_entries)
    assert "local.control_plane_api_access_log_group_name" in list_body
    assert sum("/aws/lambda/" in entry for entry in arn_entries) == 4
    assert (
        'control_plane_api_access_log_group_name = "/aws/apigateway/' in locals_source
    )


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
    ):
        assert expected_resource in api_gateway_body


def test_authorization_security_boundaries_remain_intact_after_apply_fix() -> None:
    """State, plan, data-plane, invocation, and PassRole boundaries must remain."""
    apply_block = extract_policy_document_block("terraform_apply_access")
    plan_block = extract_policy_document_block("terraform_plan_access")
    state_block = extract_policy_document_block("terraform_state_access")
    apply_actions = quoted_actions(apply_block)

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
