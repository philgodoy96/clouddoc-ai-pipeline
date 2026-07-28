"""Unit tests for value-free Terraform deployment attestations."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPOSITORY_ROOT / "scripts"
ATTESTATION_PATH = SCRIPTS_ROOT / "terraform_plan_attestation.py"


def load_attestation_module() -> ModuleType:
    """Load the attestation script with its sibling script import available."""

    spec = importlib.util.spec_from_file_location(
        "clouddoc_terraform_plan_attestation",
        ATTESTATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load attestation module: {ATTESTATION_PATH}")

    sys.path.insert(0, str(SCRIPTS_ROOT))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS_ROOT))
    return module


attestation = load_attestation_module()

REPOSITORY = "philgodoy96/clouddoc-ai-pipeline"
PLAN_RUN_ID = "123456789"
COMMIT_SHA = "a" * 40
ENVIRONMENT = "dev"
PROVIDER = "registry.terraform.io/hashicorp/aws"


def _change(
    address: str = "aws_s3_bucket.documents",
    *,
    resource_type: str = "aws_s3_bucket",
    name: str = "documents",
    actions: list[object] | None = None,
    mode: str = "managed",
    module_address: object = None,
    provider_name: object = PROVIDER,
    action_reason: object = None,
    previous_address: object = None,
    replace_paths: object = None,
    extra_change: dict[str, object] | None = None,
    extra_resource: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build one synthetic Terraform resource change."""

    change: dict[str, object] = {
        "actions": ["create"] if actions is None else actions,
        "replace_paths": [] if replace_paths is None else replace_paths,
        "before": {"secret": "SUPER_SECRET_VALUE"},
        "after": {"password": "DATABASE_PASSWORD"},
        "after_unknown": {"token": "PRIVATE_TOKEN"},
    }
    if extra_change:
        change.update(extra_change)

    resource: dict[str, object] = {
        "address": address,
        "mode": mode,
        "type": resource_type,
        "name": name,
        "provider_name": provider_name,
        "change": change,
    }
    if module_address is not None:
        resource["module_address"] = module_address
    if action_reason is not None:
        resource["action_reason"] = action_reason
    if previous_address is not None:
        resource["previous_address"] = previous_address
    if extra_resource:
        resource.update(extra_resource)
    return resource


def _plan(*changes: object) -> dict[str, object]:
    return {
        "format_version": "1.2",
        "resource_changes": list(changes),
        "configuration": {"secret": "CONFIGURATION_SECRET"},
        "planned_values": {"secret": "PLANNED_VALUE_SECRET"},
        "prior_state": {"secret": "STATE_SECRET"},
    }


def _build(document: dict[str, object]) -> Any:
    return attestation.build_attestation(
        document,
        repository=REPOSITORY,
        plan_run_id=PLAN_RUN_ID,
        commit_sha=COMMIT_SHA,
        environment=ENVIRONMENT,
    )


@pytest.mark.parametrize(
    ("actions", "expected"),
    [
        (["create"], "create"),
        (["update"], "update"),
        (["delete"], "delete"),
        (["no-op"], "no-op"),
        (["delete", "create"], "replace"),
        (["create", "delete"], "replace"),
    ],
)
def test_supported_actions_normalize(actions: list[str], expected: str) -> None:
    result = _build(_plan(_change(actions=actions)))

    assert result.resource_changes[0].action == expected
    assert result.action_counts[expected] == 1
    if expected == "replace":
        assert result.action_counts["create"] == 0
        assert result.action_counts["delete"] == 0


def test_data_sources_are_excluded() -> None:
    result = _build(
        _plan(
            _change(actions=["update"]),
            _change(
                "data.aws_caller_identity.current",
                resource_type="aws_caller_identity",
                name="current",
                actions=["read"],
                mode="data",
            ),
        )
    )

    assert len(result.resource_changes) == 1
    assert result.action_counts["update"] == 1


def test_empty_plan_is_no_change() -> None:
    result = _build(_plan())

    assert result.resource_changes == ()
    assert result.no_changes is True
    assert result.destructive_changes is False
    assert result.action_counts == {action: 0 for action in attestation.ACTION_ORDER}


def test_no_op_resources_remain_value_free_and_no_change() -> None:
    result = _build(_plan(_change(actions=["no-op"])))

    assert result.no_changes is True
    assert result.action_counts["no-op"] == 1
    assert result.resource_changes[0].action == "no-op"


def test_mixed_plan_counts_and_destructive_classification() -> None:
    result = _build(
        _plan(
            _change("aws_s3_bucket.a", name="a", actions=["create"]),
            _change("aws_s3_bucket.b", name="b", actions=["update"]),
            _change("aws_s3_bucket.c", name="c", actions=["delete"]),
            _change(
                "aws_s3_bucket.d",
                name="d",
                actions=["delete", "create"],
                replace_paths=[["bucket"]],
            ),
            _change("aws_s3_bucket.e", name="e", actions=["no-op"]),
        )
    )

    assert result.action_counts == {
        "create": 1,
        "update": 1,
        "delete": 1,
        "replace": 1,
        "no-op": 1,
    }
    assert result.destructive_changes is True
    assert result.no_changes is False


def test_resource_order_and_fingerprint_are_input_order_independent() -> None:
    first = _change("aws_s3_bucket.z", name="z", actions=["update"])
    second = _change("aws_s3_bucket.a", name="a", actions=["create"])

    forward = _build(_plan(first, second))
    reverse = _build(_plan(second, first))

    assert forward.resource_changes == reverse.resource_changes
    assert forward.change_set_fingerprint == reverse.change_set_fingerprint
    assert forward.to_mapping() == reverse.to_mapping()


def test_addresses_and_address_like_fields_are_sanitized() -> None:
    unsafe = (
        'module.jobs["private"].aws_lambda_function.'
        "customer@example.com/123456789012."
        "123e4567-e89b-12d3-a456-426614174abc\x01."
        "arn:aws:lambda:us-east-1:123456789012:function:test"
    )
    result = _build(
        _plan(
            _change(
                unsafe,
                module_address='module.jobs["private"]',
                previous_address='aws_lambda_function.old["secret"]',
            )
        )
    )
    resource = result.resource_changes[0]

    assert '["<redacted>"]' in resource.address
    assert "<arn>" in resource.address
    assert "<account-id>" in resource.address
    assert "<email>" in resource.address
    assert "<uuid>" in resource.address
    assert "?" in resource.address
    assert resource.module_address == 'module.jobs["<redacted>"]'
    assert resource.previous_address == 'aws_lambda_function.old["<redacted>"]'
    assert "customer@example.com" not in json.dumps(result.to_mapping())
    assert "123456789012" not in json.dumps(result.to_mapping())


def test_plan_values_are_never_attested() -> None:
    result = _build(
        _plan(
            _change(
                extra_change={
                    "sensitive_values": "SENSITIVE_SENTINEL",
                    "private": "PRIVATE_SENTINEL",
                },
                extra_resource={"deposed": "DEPOSED_SENTINEL"},
            )
        )
    )
    payload = attestation.canonical_json(result.to_mapping())

    for secret in (
        "SUPER_SECRET_VALUE",
        "DATABASE_PASSWORD",
        "PRIVATE_TOKEN",
        "CONFIGURATION_SECRET",
        "PLANNED_VALUE_SECRET",
        "STATE_SECRET",
        "SENSITIVE_SENTINEL",
        "PRIVATE_SENTINEL",
        "DEPOSED_SENTINEL",
    ):
        assert secret not in payload


@pytest.mark.parametrize(
    "actions",
    [
        ["read"],
        ["create", "update"],
        [],
        [1],
    ],
)
def test_unknown_or_invalid_actions_fail_closed(actions: list[object]) -> None:
    with pytest.raises(attestation.PlanAttestationError):
        _build(_plan(_change(actions=actions)))


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"resource_changes": None},
        {"resource_changes": {}},
        {"resource_changes": "invalid"},
        {"resource_changes": ["invalid"]},
    ],
)
def test_invalid_resource_changes_fail_closed(document: dict[str, object]) -> None:
    with pytest.raises(attestation.PlanAttestationError):
        _build(document)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_mode",
        "invalid_mode",
        "missing_address",
        "missing_type",
        "invalid_type",
        "missing_name",
        "invalid_name",
        "missing_provider",
        "invalid_provider",
        "missing_change",
        "invalid_change",
        "invalid_replace_paths",
        "unexpected_replace_paths",
    ],
)
def test_invalid_resource_fields_fail_closed(mutation: str) -> None:
    resource = _change()
    if mutation == "missing_mode":
        resource.pop("mode")
    elif mutation == "invalid_mode":
        resource["mode"] = "ephemeral"
    elif mutation == "missing_address":
        resource.pop("address")
    elif mutation == "missing_type":
        resource.pop("type")
    elif mutation == "invalid_type":
        resource["type"] = "AWS S3"
    elif mutation == "missing_name":
        resource.pop("name")
    elif mutation == "invalid_name":
        resource["name"] = "bad name"
    elif mutation == "missing_provider":
        resource.pop("provider_name")
    elif mutation == "invalid_provider":
        resource["provider_name"] = "provider secret"
    elif mutation == "missing_change":
        resource.pop("change")
    elif mutation == "invalid_change":
        resource["change"] = "invalid"
    elif mutation == "invalid_replace_paths":
        resource["change"]["replace_paths"] = "invalid"  # type: ignore[index]
    else:
        resource["change"]["replace_paths"] = [["bucket"]]  # type: ignore[index]

    with pytest.raises(attestation.PlanAttestationError):
        _build(_plan(resource))


def test_replace_paths_are_normalized_sorted_and_redacted() -> None:
    result = _build(
        _plan(
            _change(
                actions=["delete", "create"],
                replace_paths=[
                    ["tags", "customer-secret"],
                    ["bucket", 2],
                    ["bucket", 1],
                ],
            )
        )
    )

    assert result.resource_changes[0].replace_paths == (
        ("bucket", 1),
        ("bucket", 2),
        ("tags", "<redacted>"),
    )


@pytest.mark.parametrize(
    ("repository", "run_id", "sha", "environment"),
    [
        ("invalid", PLAN_RUN_ID, COMMIT_SHA, ENVIRONMENT),
        (REPOSITORY, "0", COMMIT_SHA, ENVIRONMENT),
        (REPOSITORY, PLAN_RUN_ID, "A" * 40, ENVIRONMENT),
        (REPOSITORY, PLAN_RUN_ID, COMMIT_SHA, "Dev"),
    ],
)
def test_invalid_context_fails_closed(
    repository: str,
    run_id: str,
    sha: str,
    environment: str,
) -> None:
    with pytest.raises(attestation.PlanAttestationError):
        attestation.build_attestation(
            _plan(),
            repository=repository,
            plan_run_id=run_id,
            commit_sha=sha,
            environment=environment,
        )


def test_attestation_round_trip_is_canonical(tmp_path: Path) -> None:
    built = _build(_plan(_change(actions=["update"])))
    path = tmp_path / "nested" / attestation.ATTESTATION_FILENAME

    attestation.write_attestation(path, built)
    loaded = attestation.read_attestation(path)

    assert loaded == built
    assert path.read_text(encoding="utf-8") == (
        attestation.canonical_json(built.to_mapping()) + "\n"
    )


def test_attestation_rejects_unknown_top_level_field() -> None:
    payload = _build(_plan()).to_mapping()
    payload["unexpected"] = "value"

    with pytest.raises(attestation.PlanAttestationError, match="unexpected schema"):
        attestation.parse_attestation(payload)


def test_attestation_rejects_unknown_resource_field() -> None:
    payload = _build(_plan(_change())).to_mapping()
    payload["resource_changes"][0]["before"] = "SECRET"  # type: ignore[index]

    with pytest.raises(attestation.PlanAttestationError, match="unexpected schema"):
        attestation.parse_attestation(payload)


def test_attestation_rejects_tampered_fingerprint() -> None:
    payload = _build(_plan(_change())).to_mapping()
    payload["change_set_fingerprint"] = "0" * 64

    with pytest.raises(attestation.PlanAttestationError, match="does not match"):
        attestation.parse_attestation(payload)


def test_attestation_rejects_tampered_counts_and_flags() -> None:
    counts = _build(_plan(_change())).to_mapping()
    counts["action_counts"]["create"] = 2  # type: ignore[index]
    with pytest.raises(attestation.PlanAttestationError, match="counts"):
        attestation.parse_attestation(counts)

    flags = _build(_plan(_change(actions=["delete"]))).to_mapping()
    flags["destructive_changes"] = False
    with pytest.raises(attestation.PlanAttestationError, match="destructive"):
        attestation.parse_attestation(flags)


def test_attestation_context_requires_exact_match() -> None:
    built = _build(_plan())

    attestation.validate_attestation_context(
        built,
        repository=REPOSITORY,
        plan_run_id=PLAN_RUN_ID,
        commit_sha=COMMIT_SHA,
        environment=ENVIRONMENT,
    )

    with pytest.raises(attestation.PlanAttestationError, match="does not match"):
        attestation.validate_attestation_context(
            built,
            repository=REPOSITORY,
            plan_run_id="987654321",
            commit_sha=COMMIT_SHA,
            environment=ENVIRONMENT,
        )


def test_change_set_comparison_uses_fingerprint() -> None:
    expected = _build(_plan(_change(actions=["create"])))
    matching = _build(_plan(_change(actions=["create"])))
    changed = _build(_plan(_change(actions=["update"])))

    attestation.require_matching_change_sets(expected, matching)
    with pytest.raises(attestation.PlanAttestationError, match="does not match"):
        attestation.require_matching_change_sets(expected, changed)


def test_load_json_object_rejects_invalid_inputs(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    directory = tmp_path / "directory"
    directory.mkdir()
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")

    for path in (missing, directory, malformed, array):
        with pytest.raises(attestation.PlanAttestationError):
            attestation.load_json_object(path, description="test JSON")


def test_generate_cli_writes_value_free_attestation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / attestation.ATTESTATION_FILENAME
    plan_path.write_text(json.dumps(_plan(_change())), encoding="utf-8")

    exit_code = attestation.main(
        [
            "generate",
            str(plan_path),
            "--repository",
            REPOSITORY,
            "--plan-run-id",
            PLAN_RUN_ID,
            "--commit-sha",
            COMMIT_SHA,
            "--environment",
            ENVIRONMENT,
            "--output",
            str(output_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""
    assert attestation.read_attestation(output_path).repository == REPOSITORY
    assert "SUPER_SECRET_VALUE" not in output_path.read_text(encoding="utf-8")


def test_validate_cli_accepts_exact_context(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / attestation.ATTESTATION_FILENAME
    attestation.write_attestation(path, _build(_plan()))

    exit_code = attestation.main(
        [
            "validate",
            str(path),
            "--repository",
            REPOSITORY,
            "--plan-run-id",
            PLAN_RUN_ID,
            "--commit-sha",
            COMMIT_SHA,
            "--environment",
            ENVIRONMENT,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_cli_failure_is_concise_and_does_not_leak_secrets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "plan.json"
    path.write_text('{"secret":"SUPER_SECRET_VALUE"}', encoding="utf-8")

    exit_code = attestation.main(
        [
            "generate",
            str(path),
            "--repository",
            REPOSITORY,
            "--plan-run-id",
            PLAN_RUN_ID,
            "--commit-sha",
            COMMIT_SHA,
            "--environment",
            ENVIRONMENT,
            "--output",
            str(tmp_path / "output.json"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "Terraform plan attestation failed:" in captured.err
    assert "Traceback" not in captured.err
    assert "SUPER_SECRET_VALUE" not in captured.err
