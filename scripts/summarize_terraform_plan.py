#!/usr/bin/env python3
"""Render a deterministic, value-free summary from Terraform plan JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Render a deterministic, value-free summary from Terraform plan JSON."
        )
    )
    parser.add_argument(
        "plan_json",
        type=Path,
        help="Path to JSON produced by terraform show -json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "Optional Markdown output path. "
            "When omitted, the summary is written to stdout."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Terraform plan summary command."""

    parser = build_argument_parser()
    arguments = parser.parse_args(argv)

    try:
        document = load_plan_json(arguments.plan_json)
        summary = summarize_plan(document)
        markdown = render_markdown(summary)

        if arguments.output is None:
            sys.stdout.write(markdown)
        else:
            write_summary(arguments.output, markdown)
    except PlanSummaryError as exc:
        print(
            f"Terraform plan summary failed: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
