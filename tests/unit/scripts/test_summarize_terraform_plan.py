#!/usr/bin/env python3
"""Render a deterministic, value-free summary from Terraform plan JSON."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ACTION_ORDER = (
    "create",
    "update",
    "delete",
    "replace",
    "no-op",
)

ACTION_LABELS = {
    "create": "Create",
    "update": "Update",
    "delete": "Delete",
    "replace": "Replace",
    "no-op": "No-op",
}

SUPPORTED_ACTIONS = {
    ("create",): "create",
    ("update",): "update",
    ("delete",): "delete",
    ("no-op",): "no-op",
    ("delete", "create"): "replace",
    ("create", "delete"): "replace",
}

RESOURCE_TYPE_PATTERN = re.compile(r"^[a-z0-9_]+$")
STRING_INDEX_PATTERN = re.compile(r'\["(?:\\.|[^"\\])*"\]')
ACCOUNT_ID_PATTERN = re.compile(r"(?<!\d)\d{12}(?!\d)")
ARN_PATTERN = re.compile(
    r"arn:(?:aws|aws-us-gov|aws-cn):[^\s\]\)\"']+",
)
EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
    r"(?![A-Za-z0-9._%+-])",
)
UUID_PATTERN = re.compile(
    r"(?i)(?<![0-9a-f])"
    r"[0-9a-f]{8}-"
    r"[0-9a-f]{4}-"
    r"[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-"
    r"[0-9a-f]{12}"
    r"(?![0-9a-f])",
)
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


class PlanSummaryError(ValueError):
    """Raised when Terraform plan JSON violates the summary contract."""


@dataclass(frozen=True, slots=True)
class PlannedResource:
    """A sanitized managed-resource action."""

    address: str
    resource_type: str
    action: str


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """A deterministic summary of managed Terraform resource changes."""

    resources: tuple[PlannedResource, ...]
    counts: Mapping[str, int]
    has_changes: bool


def load_plan_json(path: Path) -> Mapping[str, object]:
    """Load and validate the top-level Terraform plan JSON document."""

    try:
        raw_document = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PlanSummaryError("Unable to read the Terraform plan JSON file.") from exc

    try:
        document = json.loads(raw_document)
    except json.JSONDecodeError as exc:
        raise PlanSummaryError("The Terraform plan JSON file is malformed.") from exc

    if not isinstance(document, Mapping):
        raise PlanSummaryError("The Terraform plan JSON root must be an object.")

    return document


def summarize_plan(document: Mapping[str, object]) -> PlanSummary:
    """Summarize managed-resource changes without reading resource values."""

    if "resource_changes" not in document:
        raise PlanSummaryError("The Terraform plan JSON is missing resource_changes.")

    raw_changes = document["resource_changes"]

    if not isinstance(raw_changes, list):
        raise PlanSummaryError("Terraform resource_changes must be an array.")

    resources: list[PlannedResource] = []

    for index, raw_change in enumerate(raw_changes):
        if not isinstance(raw_change, Mapping):
            raise PlanSummaryError(
                f"Resource change at index {index} must be an object."
            )

        mode = raw_change.get("mode", "managed")

        if mode == "data":
            continue

        if mode != "managed":
            raise PlanSummaryError(
                f"Resource change at index {index} has an unsupported mode."
            )

        address = _required_string(
            raw_change,
            "address",
            context=f"resource change at index {index}",
        )
        resource_type = _required_string(
            raw_change,
            "type",
            context=f"resource change at index {index}",
        )

        if not RESOURCE_TYPE_PATTERN.fullmatch(resource_type):
            raise PlanSummaryError(
                f"Resource change at index {index} has an invalid type."
            )

        raw_change_details = raw_change.get("change")

        if not isinstance(raw_change_details, Mapping):
            raise PlanSummaryError(
                f"Resource change at index {index} is missing change metadata."
            )

        raw_actions = raw_change_details.get("actions")

        if not isinstance(raw_actions, list):
            raise PlanSummaryError(
                f"Resource change at index {index} has invalid actions."
            )

        actions = _validate_actions(raw_actions, index=index)
        normalized_action = SUPPORTED_ACTIONS.get(actions)

        if normalized_action is None:
            raise PlanSummaryError(
                f"Resource change at index {index} has unsupported actions."
            )

        resources.append(
            PlannedResource(
                address=_sanitize_address(address),
                resource_type=resource_type,
                action=normalized_action,
            )
        )

    ordered_resources = tuple(
        sorted(
            resources,
            key=lambda item: (
                item.address,
                item.resource_type,
                ACTION_ORDER.index(item.action),
            ),
        )
    )

    action_counter = Counter(resource.action for resource in ordered_resources)
    counts = {action: action_counter.get(action, 0) for action in ACTION_ORDER}
    has_changes = any(
        counts[action] > 0 for action in ("create", "update", "delete", "replace")
    )

    return PlanSummary(
        resources=ordered_resources,
        counts=counts,
        has_changes=has_changes,
    )


def render_markdown(summary: PlanSummary) -> str:
    """Render the plan summary as deterministic GitHub-flavored Markdown."""

    result = (
        "Changes detected" if summary.has_changes else "No managed-resource changes"
    )

    lines = [
        "## Terraform Plan Summary",
        "",
        f"**Result:** {result}",
        "",
        "| Action | Count |",
        "| --- | ---: |",
    ]

    for action in ACTION_ORDER:
        lines.append(f"| {ACTION_LABELS[action]} | {summary.counts[action]} |")

    lines.extend(
        [
            "",
            "### Managed resources",
            "",
        ]
    )

    if not summary.resources:
        lines.append("_No managed resource changes were reported._")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| Action | Resource type | Address |",
            "| --- | --- | --- |",
        ]
    )

    for resource in summary.resources:
        lines.append(
            "| "
            f"{ACTION_LABELS[resource.action]} | "
            f"{_markdown_code(resource.resource_type)} | "
            f"{_markdown_code(resource.address)} |"
        )

    lines.append("")
    return "\n".join(lines)


def write_summary(path: Path, markdown: str) -> None:
    """Write a sanitized summary to a caller-selected file."""

    if path.exists() and not path.is_file():
        raise PlanSummaryError("The summary output path must be a regular file.")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise PlanSummaryError("Unable to write the Terraform plan summary.") from exc


def _required_string(
    value: Mapping[str, object],
    key: str,
    *,
    context: str,
) -> str:
    raw_value = value.get(key)

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise PlanSummaryError(f"The {context} is missing a valid {key}.")

    return raw_value


def _validate_actions(
    raw_actions: list[object],
    *,
    index: int,
) -> tuple[str, ...]:
    if not raw_actions:
        raise PlanSummaryError(f"Resource change at index {index} has no actions.")

    actions: list[str] = []

    for raw_action in raw_actions:
        if not isinstance(raw_action, str) or not raw_action:
            raise PlanSummaryError(
                f"Resource change at index {index} has invalid actions."
            )
        actions.append(raw_action)

    return tuple(actions)


def _sanitize_address(address: str) -> str:
    sanitized = CONTROL_CHARACTER_PATTERN.sub("?", address)
    sanitized = STRING_INDEX_PATTERN.sub('["<redacted>"]', sanitized)
    sanitized = ARN_PATTERN.sub("<arn>", sanitized)
    sanitized = EMAIL_PATTERN.sub("<email>", sanitized)
    sanitized = ACCOUNT_ID_PATTERN.sub("<account-id>", sanitized)
    sanitized = UUID_PATTERN.sub("<uuid>", sanitized)
    return sanitized


def _markdown_code(value: str) -> str:
    safe_value = value.replace("`", "'")
    safe_value = safe_value.replace("|", r"\|")
    return f"`{safe_value}`"


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PRODUCTION_SUMMARIZER_PATH = REPOSITORY_ROOT / "scripts" / "summarize_terraform_plan.py"


def _load_production_module():
    spec = importlib.util.spec_from_file_location(
        "clouddoc_terraform_plan_summarize",
        PRODUCTION_SUMMARIZER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {PRODUCTION_SUMMARIZER_PATH}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


production = _load_production_module()

PROD_ACTION_ORDER: tuple[str, ...] = production.ACTION_ORDER
PROD_ACTION_LABELS: dict[str, str] = production.ACTION_LABELS
ProductionPlanSummaryError = production.PlanSummaryError


def _managed_change(
    *,
    address: str,
    resource_type: str,
    actions: list[object],
    change_fields: dict[str, Any] | None = None,
    mode: str = "managed",
) -> dict[str, Any]:
    return {
        "address": address,
        "mode": mode,
        "type": resource_type,
        "change": {
            "actions": actions,
            **({} if change_fields is None else change_fields),
        },
    }


def _plan(resource_changes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"resource_changes": resource_changes}


def _write_json(tmp_path: Path, name: str, document: Any) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")
    return path


def _write_plan_with_invalid_utf8(tmp_path: Path) -> Path:
    path = tmp_path / "bad_utf8.json"
    path.write_bytes(b"\xff\xfe\xfa")
    return path


def _extract_managed_resource_rows(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    header = "| Action | Resource type | Address |"
    if header not in lines:
        return []

    start_index = lines.index(header)
    rows: list[str] = []
    for line in lines[start_index + 2 :]:
        if not line.strip():
            break
        rows.append(line)
    return rows


def _code(value: str) -> str:
    return production._markdown_code(value)  # type: ignore[attr-defined]


def _sanitize(value: str) -> str:
    return production._sanitize_address(value)  # type: ignore[attr-defined]


def _row(action: str, resource_type: str, address: str) -> str:
    return (
        f"| {PROD_ACTION_LABELS[action]} | "
        f"{_code(resource_type)} | "
        f"{_code(_sanitize(address))} |"
    )


@pytest.mark.parametrize(
    ("terraform_actions", "expected_action"),
    [
        (["create"], "create"),
        (["update"], "update"),
        (["delete"], "delete"),
        (["no-op"], "no-op"),
        (["delete", "create"], "replace"),
        (["create", "delete"], "replace"),
    ],
)
def test_action_normalization_all_supported_combos(
    terraform_actions: list[str],
    expected_action: str,
) -> None:
    document = _plan(
        [
            _managed_change(
                address="aws_instance.example",
                resource_type="aws_instance",
                actions=terraform_actions,
            )
        ]
    )
    summary = production.summarize_plan(document)

    for action in PROD_ACTION_ORDER:
        expected_count = 1 if action == expected_action else 0
        assert summary.counts[action] == expected_count

    assert len(summary.resources) == 1
    assert summary.resources[0].action == expected_action

    markdown = production.render_markdown(summary)
    assert f"| {PROD_ACTION_LABELS[expected_action]} | 1 |" in markdown

    resource_rows = _extract_managed_resource_rows(markdown)
    assert len(resource_rows) == 1
    assert resource_rows[0].startswith(f"| {PROD_ACTION_LABELS[expected_action]} |")


def test_mode_managed_included_data_excluded_from_counts_and_rows() -> None:
    managed = _managed_change(
        address="managed_address",
        resource_type="aws_instance",
        actions=["create"],
    )
    data_source = _managed_change(
        address="data_address",
        resource_type="aws_instance",
        actions=["delete"],
        mode="data",
    )
    document = _plan([data_source, managed])

    summary = production.summarize_plan(document)
    assert summary.counts == {
        "create": 1,
        "update": 0,
        "delete": 0,
        "replace": 0,
        "no-op": 0,
    }
    assert summary.has_changes is True

    markdown = production.render_markdown(summary)
    assert "managed_address" in markdown
    assert "data_address" not in markdown
    assert len(_extract_managed_resource_rows(markdown)) == 1


def test_empty_and_noop_plans() -> None:
    empty_document = _plan([])
    empty_summary = production.summarize_plan(empty_document)
    assert empty_summary.resources == ()
    assert all(empty_summary.counts[action] == 0 for action in PROD_ACTION_ORDER)
    assert empty_summary.has_changes is False

    empty_markdown = production.render_markdown(empty_summary)
    assert "**Result:** No managed-resource changes" in empty_markdown
    assert "_No managed resource changes were reported._" in empty_markdown
    assert "| Action | Resource type | Address |" not in empty_markdown

    no_op_document = _plan(
        [
            _managed_change(
                address="noop_address",
                resource_type="aws_kms_key",
                actions=["no-op"],
            )
        ]
    )
    no_op_summary = production.summarize_plan(no_op_document)
    assert no_op_summary.counts["no-op"] == 1
    assert no_op_summary.has_changes is False

    no_op_markdown = production.render_markdown(no_op_summary)
    assert "**Result:** No managed-resource changes" in no_op_markdown
    assert len(_extract_managed_resource_rows(no_op_markdown)) == 1
    assert "| No-op |" in no_op_markdown


def test_mixed_plan_counts_and_row_ordering() -> None:
    data_source = _managed_change(
        address="data_address_should_not_render",
        resource_type="aws_instance",
        actions=["create"],
        mode="data",
    )
    replace = _managed_change(
        address="d_replace",
        resource_type="aws_lambda_function",
        actions=["delete", "create"],
    )
    create = _managed_change(
        address="a_create",
        resource_type="aws_instance",
        actions=["create"],
    )
    delete = _managed_change(
        address="c_delete",
        resource_type="aws_s3_bucket",
        actions=["delete"],
    )
    update = _managed_change(
        address="b_update",
        resource_type="aws_security_group",
        actions=["update"],
    )
    no_op = _managed_change(
        address="e_no-op",
        resource_type="aws_kms_key",
        actions=["no-op"],
    )

    document = _plan([data_source, replace, create, delete, update, no_op])
    summary = production.summarize_plan(document)
    assert summary.counts == {
        "create": 1,
        "update": 1,
        "delete": 1,
        "replace": 1,
        "no-op": 1,
    }
    assert summary.has_changes is True

    markdown = production.render_markdown(summary)
    assert "data_address_should_not_render" not in markdown

    resource_rows = _extract_managed_resource_rows(markdown)
    assert resource_rows == [
        _row("create", "aws_instance", "a_create"),
        _row("update", "aws_security_group", "b_update"),
        _row("delete", "aws_s3_bucket", "c_delete"),
        _row("replace", "aws_lambda_function", "d_replace"),
        _row("no-op", "aws_kms_key", "e_no-op"),
    ]


def test_deterministic_ordering_independent_of_input_order() -> None:
    base_resources = [
        _managed_change(
            address="shared_addr",
            resource_type="aws_instance",
            actions=["delete"],
        ),
        _managed_change(
            address="shared_addr",
            resource_type="aws_instance",
            actions=["create"],
        ),
        _managed_change(
            address="other_update",
            resource_type="aws_security_group",
            actions=["update"],
        ),
        _managed_change(
            address="other_replace",
            resource_type="aws_lambda_function",
            actions=["create", "delete"],
        ),
        _managed_change(
            address="other_no-op",
            resource_type="aws_kms_key",
            actions=["no-op"],
        ),
    ]

    document_1 = _plan([base_resources[0], base_resources[2], base_resources[1]])
    document_1["resource_changes"].extend(base_resources[3:])
    document_2 = _plan(list(reversed(base_resources)))

    summary_1 = production.summarize_plan(document_1)
    summary_2 = production.summarize_plan(document_2)
    assert summary_1.resources == summary_2.resources
    assert production.render_markdown(summary_1) == production.render_markdown(
        summary_2
    )

    shared = [
        r.action
        for r in summary_1.resources
        if r.address == _sanitize("shared_addr") and r.resource_type == "aws_instance"
    ]
    assert shared == ["create", "delete"]


def test_address_sanitization_all_patterns_in_markdown() -> None:
    control_address = "bad\x01char"
    string_index_address = 'aws_instance.example["SECRET_INDEX"]'
    arn_address = "arn:aws:iam::123456789012:role/demo-role"
    account_id_address = "acct-123456789012-end"
    email_address = "user@example.com"
    # Use a UUID whose last segment is not all digits, so the account-id
    # sanitizer does not preempt the UUID sanitizer (sanitizers run in order).
    uuid_address = "id-123e4567-e89b-12d3-a456-42661417400a"

    document = _plan(
        [
            _managed_change(
                address=string_index_address,
                resource_type="aws_instance",
                actions=["create"],
            ),
            _managed_change(
                address=arn_address,
                resource_type="aws_iam_role",
                actions=["update"],
            ),
            _managed_change(
                address=account_id_address,
                resource_type="aws_s3_bucket",
                actions=["delete"],
            ),
            _managed_change(
                address=email_address,
                resource_type="aws_kms_key",
                actions=["create"],
            ),
            _managed_change(
                address=uuid_address,
                resource_type="aws_lambda_function",
                actions=["no-op"],
            ),
            _managed_change(
                address=control_address,
                resource_type="aws_security_group",
                actions=["create"],
            ),
        ]
    )

    markdown = production.render_markdown(production.summarize_plan(document))

    assert '["<redacted>"]' in markdown
    assert "SECRET_INDEX" not in markdown

    assert "<arn>" in markdown
    assert "arn:aws:" not in markdown

    assert "<account-id>" in markdown
    assert "123456789012" not in markdown

    assert "<email>" in markdown
    assert "user@example.com" not in markdown

    assert "<uuid>" in markdown
    assert "123e4567-e89b-12d3-a456-42661417400a" not in markdown

    assert "bad?char" in markdown
    assert "\x01" not in markdown


def test_sensitive_values_never_rendered_in_markdown_and_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinels = ["SUPER_SECRET_VALUE", "DATABASE_PASSWORD", "PRIVATE_TOKEN"]
    change_fields = {
        "before": sentinels[0],
        "after": sentinels[1],
        "after_unknown": sentinels[2],
        "sensitive_values": [sentinels[0], sentinels[1]],
        "private": sentinels[2],
        "configuration": {"k": sentinels[0]},
        "provider_config": {"p": sentinels[1]},
    }
    document = _plan(
        [
            _managed_change(
                address="safe_address",
                resource_type="aws_instance",
                actions=["create"],
                change_fields=change_fields,
            )
        ]
    )

    expected_markdown = production.render_markdown(production.summarize_plan(document))
    for sentinel in sentinels:
        assert sentinel not in expected_markdown

    plan_path = _write_json(tmp_path, "plan.json", document)

    capsys.readouterr()
    exit_code = production.main([str(plan_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == expected_markdown
    for sentinel in sentinels:
        assert sentinel not in captured.out

    out_path = tmp_path / "summary.md"
    capsys.readouterr()
    exit_code = production.main([str(plan_path), "--output", str(out_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert out_path.is_file()
    written = out_path.read_text(encoding="utf-8")
    assert written == expected_markdown
    for sentinel in sentinels:
        assert sentinel not in written


@pytest.mark.parametrize(
    ("terraform_actions", "expected_message"),
    [
        (["read"], "has unsupported actions"),
        (["create", "update"], "has unsupported actions"),
        ([], "has no actions"),
    ],
)
def test_unknown_action_combinations_fail_closed(
    terraform_actions: list[object],
    expected_message: str,
) -> None:
    document = _plan(
        [
            _managed_change(
                address="aws_instance.example",
                resource_type="aws_instance",
                actions=terraform_actions,
            )
        ]
    )
    with pytest.raises(ProductionPlanSummaryError, match=expected_message):
        production.summarize_plan(document)


def test_resource_changes_contract_fail_closed() -> None:
    invalid_cases: list[tuple[dict[str, Any], str]] = [
        ({}, "missing resource_changes"),
        ({"resource_changes": None}, "must be an array"),
        ({"resource_changes": {}}, "must be an array"),
        ({"resource_changes": "not-a-list"}, "must be an array"),
        ({"resource_changes": ["not-an-object"]}, "must be an object"),
    ]
    for document, message in invalid_cases:
        with pytest.raises(ProductionPlanSummaryError, match=message):
            production.summarize_plan(document)


def test_invalid_resource_change_fields_fail_closed() -> None:
    invalid_changes: list[tuple[dict[str, Any], str]] = [
        (
            {
                "mode": "managed",
                "type": "aws_instance",
                "change": {"actions": ["create"]},
            },
            "missing a valid address",
        ),
        (
            {
                "address": 123,
                "mode": "managed",
                "type": "aws_instance",
                "change": {"actions": ["create"]},
            },
            "missing a valid address",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "change": {"actions": ["create"]},
            },
            "missing a valid type",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "type": 123,
                "change": {"actions": ["create"]},
            },
            "missing a valid type",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": 123,
                "type": "aws_instance",
                "change": {"actions": ["create"]},
            },
            "unsupported mode",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "type": "aws_instance",
            },
            "missing change metadata",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "type": "aws_instance",
                "change": "not-a-map",
            },
            "missing change metadata",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "type": "aws_instance",
                "change": {},
            },
            "invalid actions",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "type": "aws_instance",
                "change": {"actions": "create"},
            },
            "invalid actions",
        ),
        (
            {
                "address": "aws_instance.example",
                "mode": "managed",
                "type": "aws_instance",
                "change": {"actions": [123]},
            },
            "invalid actions",
        ),
    ]
    for invalid_change, expected_message in invalid_changes:
        with pytest.raises(ProductionPlanSummaryError, match=expected_message):
            production.summarize_plan(_plan([invalid_change]))


def test_json_file_loading_contract(tmp_path: Path) -> None:
    valid_document = _plan([])
    valid_path = _write_json(tmp_path, "valid.json", valid_document)
    loaded = production.load_plan_json(valid_path)
    assert isinstance(loaded, dict)
    assert list(loaded.keys()) == ["resource_changes"]

    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text("{not-json", encoding="utf-8", newline="\n")
    with pytest.raises(ProductionPlanSummaryError, match="malformed"):
        production.load_plan_json(malformed_path)

    non_object_path = _write_json(tmp_path, "non_object.json", ["x"])
    with pytest.raises(ProductionPlanSummaryError, match="root must be an object"):
        production.load_plan_json(non_object_path)

    missing_path = tmp_path / "missing.json"
    with pytest.raises(
        ProductionPlanSummaryError,
        match="Unable to read the Terraform plan JSON file",
    ):
        production.load_plan_json(missing_path)

    as_directory_path = tmp_path / "a_directory.json"
    as_directory_path.mkdir()
    with pytest.raises(
        ProductionPlanSummaryError,
        match="Unable to read the Terraform plan JSON file",
    ):
        production.load_plan_json(as_directory_path)

    bad_utf8_path = _write_plan_with_invalid_utf8(tmp_path)
    with pytest.raises(UnicodeDecodeError):
        production.load_plan_json(bad_utf8_path)


def test_output_file_behavior_valid_and_invalid_targets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _plan(
        [
            _managed_change(
                address="out_address",
                resource_type="aws_instance",
                actions=["create"],
            )
        ]
    )
    plan_path = _write_json(tmp_path, "plan.json", document)

    expected_markdown = production.render_markdown(production.summarize_plan(document))

    out_path = tmp_path / "summary.md"
    capsys.readouterr()
    exit_code = production.main([str(plan_path), "--output", str(out_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert out_path.is_file()
    assert out_path.read_text(encoding="utf-8") == expected_markdown

    out_dir = tmp_path / "out_dir"
    out_dir.mkdir()
    capsys.readouterr()
    exit_code = production.main([str(plan_path), "--output", str(out_dir)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Terraform plan summary failed:" in captured.err
    assert "must be a regular file" in captured.err
    assert "Traceback" not in captured.err

    parent_file = tmp_path / "parent_is_file"
    parent_file.write_text("not-a-dir", encoding="utf-8", newline="\n")
    invalid_out = parent_file / "summary.md"
    capsys.readouterr()
    exit_code = production.main([str(plan_path), "--output", str(invalid_out)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Terraform plan summary failed:" in captured.err
    assert "Unable to write the Terraform plan summary" in captured.err
    assert "Traceback" not in captured.err


def test_cli_stdout_behavior_success(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = _plan(
        [
            _managed_change(
                address="stdout_address",
                resource_type="aws_instance",
                actions=["create"],
            )
        ]
    )
    plan_path = _write_json(tmp_path, "plan.json", document)

    expected_markdown = production.render_markdown(production.summarize_plan(document))

    capsys.readouterr()
    exit_code = production.main([str(plan_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == expected_markdown


@pytest.mark.parametrize(
    "case",
    ["malformed_json", "unknown_actions", "invalid_input_path"],
)
def test_cli_failure_behavior_no_traceback_no_secret_leakage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    secret = "SUPER_SECRET_VALUE"
    if case == "malformed_json":
        plan_path = tmp_path / "bad.json"
        plan_path.write_text("{not-json", encoding="utf-8", newline="\n")
    elif case == "unknown_actions":
        document = _plan(
            [
                _managed_change(
                    address="safe_address",
                    resource_type="aws_instance",
                    actions=["read"],
                    change_fields={"before": secret, "after": secret},
                )
            ]
        )
        plan_path = _write_json(tmp_path, "plan.json", document)
    else:
        plan_path = tmp_path / "does_not_exist.json"

    capsys.readouterr()
    exit_code = production.main([str(plan_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Terraform plan summary failed:" in captured.err
    assert "Traceback" not in captured.err
    assert secret not in captured.err


def test_type_contracts() -> None:
    document = _plan(
        [
            _managed_change(
                address="type_contract_addr",
                resource_type="aws_instance",
                actions=["create"],
            )
        ]
    )
    summary = production.summarize_plan(document)
    assert isinstance(summary.resources, tuple)
    assert isinstance(summary.resources[0], production.PlannedResource)
    assert summary.has_changes is True

    frozen = summary.resources[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        frozen.action = "update"  # type: ignore[misc]
