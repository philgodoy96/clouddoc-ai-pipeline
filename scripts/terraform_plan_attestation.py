"""Create and validate value-free Terraform deployment attestations."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from summarize_terraform_plan import ACTION_ORDER, SUPPORTED_ACTIONS, _sanitize_address

SCHEMA_VERSION = "1"
ATTESTATION_FILENAME = "terraform-plan-attestation.json"
DESTRUCTIVE_ACTIONS = frozenset({"delete", "replace"})
CHANGE_FIELDS = frozenset(
    {
        "address",
        "module_address",
        "mode",
        "resource_type",
        "resource_name",
        "provider_name",
        "action",
        "action_reason",
        "previous_address",
        "replace_paths",
    }
)
ATTESTATION_FIELDS = frozenset(
    {
        "schema_version",
        "repository",
        "plan_run_id",
        "commit_sha",
        "environment",
        "resource_changes",
        "action_counts",
        "destructive_changes",
        "no_changes",
        "change_set_fingerprint",
    }
)
PATTERNS = {
    "repository": re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
    ),
    "plan_run_id": re.compile(r"^[1-9][0-9]*$"),
    "commit_sha": re.compile(r"^[0-9a-f]{40}$"),
    "environment": re.compile(r"^[a-z][a-z0-9-]{0,62}$"),
    "resource_type": re.compile(r"^[a-z0-9_]+$"),
    "resource_name": re.compile(r"^[A-Za-z0-9_-]+$"),
    "provider_name": re.compile(r"^[A-Za-z0-9._/-]+$"),
    "action_reason": re.compile(r"^[a-z0-9_]+$"),
    "path_segment": re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$"),
    "fingerprint": re.compile(r"^[0-9a-f]{64}$"),
}


class PlanAttestationError(ValueError):
    """Raised when plan JSON or an attestation violates the contract."""


@dataclass(frozen=True, slots=True)
class AttestedResourceChange:
    """One deterministic value-free managed-resource change."""

    address: str
    module_address: str | None
    mode: str
    resource_type: str
    resource_name: str
    provider_name: str
    action: str
    action_reason: str | None
    previous_address: str | None
    replace_paths: tuple[tuple[str | int, ...], ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "address": self.address,
            "module_address": self.module_address,
            "mode": self.mode,
            "resource_type": self.resource_type,
            "resource_name": self.resource_name,
            "provider_name": self.provider_name,
            "action": self.action,
            "action_reason": self.action_reason,
            "previous_address": self.previous_address,
            "replace_paths": [list(path) for path in self.replace_paths],
        }


@dataclass(frozen=True, slots=True)
class TerraformPlanAttestation:
    """A strict value-free Terraform change-set attestation."""

    repository: str
    plan_run_id: str
    commit_sha: str
    environment: str
    resource_changes: tuple[AttestedResourceChange, ...]
    action_counts: Mapping[str, int]
    destructive_changes: bool
    no_changes: bool
    change_set_fingerprint: str
    schema_version: str = SCHEMA_VERSION

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "repository": self.repository,
            "plan_run_id": self.plan_run_id,
            "commit_sha": self.commit_sha,
            "environment": self.environment,
            "resource_changes": [
                resource.to_mapping() for resource in self.resource_changes
            ],
            "action_counts": {
                action: self.action_counts[action] for action in ACTION_ORDER
            },
            "destructive_changes": self.destructive_changes,
            "no_changes": self.no_changes,
            "change_set_fingerprint": self.change_set_fingerprint,
        }


def build_attestation(
    document: Mapping[str, object],
    *,
    repository: str,
    plan_run_id: str,
    commit_sha: str,
    environment: str,
) -> TerraformPlanAttestation:
    """Build an attestation from Terraform plan JSON without reading values."""

    metadata = _validate_context(
        repository=repository,
        plan_run_id=plan_run_id,
        commit_sha=commit_sha,
        environment=environment,
    )
    resources = _resources_from_plan(document)
    counts = _counts(resources)
    destructive = any(counts[action] for action in DESTRUCTIVE_ACTIONS)
    no_changes = not any(
        counts[action] for action in ("create", "update", "delete", "replace")
    )
    fingerprint = _fingerprint(_projection(resources, counts, destructive, no_changes))
    return TerraformPlanAttestation(
        **metadata,
        resource_changes=resources,
        action_counts=counts,
        destructive_changes=destructive,
        no_changes=no_changes,
        change_set_fingerprint=fingerprint,
    )


def parse_attestation(document: Mapping[str, object]) -> TerraformPlanAttestation:
    """Parse and validate a strict attestation JSON document."""

    _exact_fields(document, ATTESTATION_FIELDS, context="attestation")
    if _string(document, "schema_version", "attestation") != SCHEMA_VERSION:
        raise PlanAttestationError("The attestation schema version is unsupported.")

    metadata = _validate_context(
        repository=_string(document, "repository", "attestation"),
        plan_run_id=_string(document, "plan_run_id", "attestation"),
        commit_sha=_string(document, "commit_sha", "attestation"),
        environment=_string(document, "environment", "attestation"),
    )
    raw_resources = document["resource_changes"]
    if not isinstance(raw_resources, list):
        raise PlanAttestationError("Attestation resource_changes must be an array.")
    resources = _sort_resources(
        _resource_from_attestation(value, index)
        for index, value in enumerate(raw_resources)
    )

    counts = _attested_counts(document["action_counts"])
    if counts != _counts(resources):
        raise PlanAttestationError("Attestation action counts do not match resources.")

    destructive = _boolean(document, "destructive_changes", "attestation")
    no_changes = _boolean(document, "no_changes", "attestation")
    if destructive != any(counts[action] for action in DESTRUCTIVE_ACTIONS):
        raise PlanAttestationError(
            "Attestation destructive_changes does not match action counts."
        )
    expected_no_changes = not any(
        counts[action] for action in ("create", "update", "delete", "replace")
    )
    if no_changes != expected_no_changes:
        raise PlanAttestationError(
            "Attestation no_changes does not match action counts."
        )

    fingerprint = _string(document, "change_set_fingerprint", "attestation")
    if not PATTERNS["fingerprint"].fullmatch(fingerprint):
        raise PlanAttestationError("The attestation fingerprint is invalid.")
    expected_fingerprint = _fingerprint(
        _projection(resources, counts, destructive, no_changes)
    )
    if fingerprint != expected_fingerprint:
        raise PlanAttestationError(
            "The attestation fingerprint does not match its data."
        )

    return TerraformPlanAttestation(
        **metadata,
        resource_changes=resources,
        action_counts=counts,
        destructive_changes=destructive,
        no_changes=no_changes,
        change_set_fingerprint=fingerprint,
    )


def load_json_object(path: Path, *, description: str) -> Mapping[str, object]:
    """Load a UTF-8 JSON object from a regular file."""

    if not path.is_file():
        raise PlanAttestationError(f"The {description} path must be a regular file.")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanAttestationError(f"Unable to read the {description} file.") from exc
    except UnicodeError as exc:
        raise PlanAttestationError(f"Unable to decode the {description} file.") from exc
    except json.JSONDecodeError as exc:
        raise PlanAttestationError(
            f"The {description} file is malformed JSON."
        ) from exc
    if not isinstance(document, Mapping):
        raise PlanAttestationError(f"The {description} JSON root must be an object.")
    return document


def read_attestation(path: Path) -> TerraformPlanAttestation:
    """Read and validate an attestation file."""

    return parse_attestation(load_json_object(path, description="attestation"))


def write_attestation(path: Path, value: TerraformPlanAttestation) -> None:
    """Write deterministic canonical attestation JSON."""

    if path.exists() and not path.is_file():
        raise PlanAttestationError(
            "The attestation output path must be a regular file."
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            canonical_json(value.to_mapping()) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise PlanAttestationError("Unable to write the attestation file.") from exc


def validate_attestation_context(
    value: TerraformPlanAttestation,
    *,
    repository: str,
    plan_run_id: str,
    commit_sha: str,
    environment: str,
) -> None:
    """Require exact deployment-context binding."""

    expected = _validate_context(
        repository=repository,
        plan_run_id=plan_run_id,
        commit_sha=commit_sha,
        environment=environment,
    )
    actual = {
        "repository": value.repository,
        "plan_run_id": value.plan_run_id,
        "commit_sha": value.commit_sha,
        "environment": value.environment,
    }
    if actual != expected:
        raise PlanAttestationError(
            "The attestation context does not match the deployment request."
        )


def require_matching_change_sets(
    expected: TerraformPlanAttestation,
    actual: TerraformPlanAttestation,
) -> None:
    """Require equal canonical value-free change-set fingerprints."""

    if expected.change_set_fingerprint != actual.change_set_fingerprint:
        raise PlanAttestationError(
            "The regenerated Terraform change set does not match the reviewed plan."
        )


def canonical_json(value: object) -> str:
    """Serialize JSON deterministically for storage and hashing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _resources_from_plan(
    document: Mapping[str, object],
) -> tuple[AttestedResourceChange, ...]:
    if "resource_changes" not in document:
        raise PlanAttestationError("Terraform plan JSON is missing resource_changes.")
    raw_resources = document["resource_changes"]
    if not isinstance(raw_resources, list):
        raise PlanAttestationError("Terraform resource_changes must be an array.")

    resources: list[AttestedResourceChange] = []
    for index, value in enumerate(raw_resources):
        if not isinstance(value, Mapping):
            raise PlanAttestationError(
                f"Resource change at index {index} must be an object."
            )
        mode = _string(value, "mode", f"resource change at index {index}")
        if mode == "data":
            continue
        if mode != "managed":
            raise PlanAttestationError(
                f"Resource change at index {index} has an unsupported mode."
            )
        details = value.get("change")
        if not isinstance(details, Mapping):
            raise PlanAttestationError(
                f"Resource change at index {index} is missing change metadata."
            )
        action = _action(details.get("actions"), index)
        replace_paths = _replace_paths(details.get("replace_paths", []), index)
        if action != "replace" and replace_paths:
            raise PlanAttestationError(
                f"Resource change at index {index} has unexpected replacement paths."
            )
        resources.append(
            AttestedResourceChange(
                address=_address(value, "address", index),
                module_address=_optional_address(
                    value.get("module_address"), "module_address", index
                ),
                mode=mode,
                resource_type=_patterned(
                    value,
                    "type",
                    "resource_type",
                    f"resource change at index {index}",
                ),
                resource_name=_patterned(
                    value,
                    "name",
                    "resource_name",
                    f"resource change at index {index}",
                ),
                provider_name=_patterned(
                    value,
                    "provider_name",
                    "provider_name",
                    f"resource change at index {index}",
                ),
                action=action,
                action_reason=_optional_patterned(
                    value.get("action_reason"), "action_reason", index
                ),
                previous_address=_optional_address(
                    value.get("previous_address"), "previous_address", index
                ),
                replace_paths=replace_paths,
            )
        )
    return _sort_resources(resources)


def _resource_from_attestation(
    value: object,
    index: int,
) -> AttestedResourceChange:
    if not isinstance(value, Mapping):
        raise PlanAttestationError(
            f"Attested resource change at index {index} must be an object."
        )
    context = f"attested resource change at index {index}"
    _exact_fields(value, CHANGE_FIELDS, context=context)
    action = _string(value, "action", context)
    if action not in ACTION_ORDER:
        raise PlanAttestationError(f"The {context} has an unsupported action.")
    replace_paths = _replace_paths(value["replace_paths"], index)
    if action != "replace" and replace_paths:
        raise PlanAttestationError(f"The {context} has unexpected replacement paths.")
    return AttestedResourceChange(
        address=_attested_address(value["address"], "address", index),
        module_address=_attested_optional_address(
            value["module_address"], "module_address", index
        ),
        mode=_exact_mode(value["mode"], index),
        resource_type=_patterned(value, "resource_type", "resource_type", context),
        resource_name=_patterned(value, "resource_name", "resource_name", context),
        provider_name=_patterned(value, "provider_name", "provider_name", context),
        action=action,
        action_reason=_attested_optional_patterned(
            value["action_reason"], "action_reason", index
        ),
        previous_address=_attested_optional_address(
            value["previous_address"], "previous_address", index
        ),
        replace_paths=replace_paths,
    )


def _sort_resources(
    resources: Sequence[AttestedResourceChange],
) -> tuple[AttestedResourceChange, ...]:
    return tuple(sorted(resources, key=lambda item: canonical_json(item.to_mapping())))


def _counts(resources: Sequence[AttestedResourceChange]) -> dict[str, int]:
    counter = Counter(resource.action for resource in resources)
    return {action: counter.get(action, 0) for action in ACTION_ORDER}


def _projection(
    resources: Sequence[AttestedResourceChange],
    counts: Mapping[str, int],
    destructive: bool,
    no_changes: bool,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "resource_changes": [resource.to_mapping() for resource in resources],
        "action_counts": {action: counts[action] for action in ACTION_ORDER},
        "destructive_changes": destructive,
        "no_changes": no_changes,
    }


def _fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _action(value: object, index: int) -> str:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise PlanAttestationError(
            f"Resource change at index {index} has invalid actions."
        )
    normalized = SUPPORTED_ACTIONS.get(tuple(value))
    if normalized is None:
        raise PlanAttestationError(
            f"Resource change at index {index} has unsupported actions."
        )
    return normalized


def _replace_paths(
    value: object,
    index: int,
) -> tuple[tuple[str | int, ...], ...]:
    if not isinstance(value, list):
        raise PlanAttestationError(
            f"Resource change at index {index} has invalid replacement paths."
        )
    paths: list[tuple[str | int, ...]] = []
    for path in value:
        if not isinstance(path, list) or not path:
            raise PlanAttestationError(
                f"Resource change at index {index} has an invalid replacement path."
            )
        normalized: list[str | int] = []
        for segment in path:
            if isinstance(segment, bool) or not isinstance(segment, (str, int)):
                raise PlanAttestationError(
                    f"Resource change at index {index} has an invalid path segment."
                )
            if isinstance(segment, int):
                if segment < 0:
                    raise PlanAttestationError(
                        f"Resource change at index {index} has an invalid path index."
                    )
                normalized.append(segment)
            elif not segment:
                raise PlanAttestationError(
                    f"Resource change at index {index} has an invalid path segment."
                )
            else:
                normalized.append(
                    segment
                    if PATTERNS["path_segment"].fullmatch(segment)
                    else "<redacted>"
                )
        paths.append(tuple(normalized))
    return tuple(sorted(paths, key=lambda item: canonical_json(list(item))))


def _attested_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise PlanAttestationError("Attestation action_counts must be an object.")
    _exact_fields(value, frozenset(ACTION_ORDER), context="action_counts")
    counts: dict[str, int] = {}
    for action in ACTION_ORDER:
        count = value[action]
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise PlanAttestationError(
                "Attestation action counts must be non-negative integers."
            )
        counts[action] = count
    return counts


def _validate_context(**values: str) -> dict[str, str]:
    for field, value in values.items():
        if not PATTERNS[field].fullmatch(value):
            raise PlanAttestationError(f"The {field} value is invalid.")
    return values


def _exact_fields(
    value: Mapping[str, object],
    expected: frozenset[str],
    *,
    context: str,
) -> None:
    if frozenset(value) != expected:
        raise PlanAttestationError(f"The {context} has an unexpected schema.")


def _string(value: Mapping[str, object], key: str, context: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip() or result != result.strip():
        raise PlanAttestationError(f"The {context} has an invalid {key}.")
    return result


def _boolean(value: Mapping[str, object], key: str, context: str) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise PlanAttestationError(f"The {context} has an invalid {key}.")
    return result


def _patterned(
    value: Mapping[str, object],
    key: str,
    pattern: str,
    context: str,
) -> str:
    result = _string(value, key, context)
    if not PATTERNS[pattern].fullmatch(result):
        raise PlanAttestationError(f"The {context} has an invalid {key}.")
    return result


def _address(
    value: Mapping[str, object],
    key: str,
    index: int,
) -> str:
    return _sanitize_address(_string(value, key, f"resource change at index {index}"))


def _optional_address(value: object, field: str, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise PlanAttestationError(
            f"Resource change at index {index} has an invalid {field}."
        )
    return _sanitize_address(value)


def _attested_address(value: object, field: str, index: int) -> str:
    result = _attested_optional_address(value, field, index)
    if result is None:
        raise PlanAttestationError(
            f"Attested resource change at index {index} has an invalid {field}."
        )
    return result


def _attested_optional_address(
    value: object,
    field: str,
    index: int,
) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or value != _sanitize_address(value)
    ):
        raise PlanAttestationError(
            f"Attested resource change at index {index} has an invalid {field}."
        )
    return value


def _optional_patterned(value: object, pattern: str, index: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not PATTERNS[pattern].fullmatch(value):
        raise PlanAttestationError(
            f"Resource change at index {index} has an invalid {pattern}."
        )
    return value


def _attested_optional_patterned(
    value: object,
    pattern: str,
    index: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not PATTERNS[pattern].fullmatch(value):
        raise PlanAttestationError(
            f"Attested resource change at index {index} has an invalid {pattern}."
        )
    return value


def _exact_mode(value: object, index: int) -> str:
    if value != "managed":
        raise PlanAttestationError(
            f"Attested resource change at index {index} has an invalid mode."
        )
    return "managed"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or validate a value-free Terraform plan attestation."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("plan_json", type=Path)
    _context_arguments(generate)
    generate.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("attestation", type=Path)
    _context_arguments(validate)
    return parser


def _context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True)
    parser.add_argument("--plan-run-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--environment", required=True)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        if arguments.command == "generate":
            document = load_json_object(
                arguments.plan_json,
                description="Terraform plan JSON",
            )
            value = build_attestation(
                document,
                repository=arguments.repository,
                plan_run_id=arguments.plan_run_id,
                commit_sha=arguments.commit_sha,
                environment=arguments.environment,
            )
            write_attestation(arguments.output, value)
        else:
            value = read_attestation(arguments.attestation)
            validate_attestation_context(
                value,
                repository=arguments.repository,
                plan_run_id=arguments.plan_run_id,
                commit_sha=arguments.commit_sha,
                environment=arguments.environment,
            )
    except PlanAttestationError as exc:
        print(f"Terraform plan attestation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
