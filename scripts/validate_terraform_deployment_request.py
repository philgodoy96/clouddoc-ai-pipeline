"""Validate a referenced Terraform Plan workflow run before artifact download."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Final

DEFAULT_WORKFLOW_PATH: Final = ".github/workflows/terraform-plan.yml"
DEFAULT_REF: Final = "refs/heads/main"
DEFAULT_EVENT: Final = "workflow_dispatch"
DEFAULT_MAXIMUM_AGE_HOURS: Final = 24
DEFAULT_API_URL: Final = "https://api.github.com"
REQUEST_TIMEOUT_SECONDS: Final = 10
CLOCK_SKEW_ALLOWANCE: Final = timedelta(minutes=5)
API_VERSION: Final = "2026-03-10"
USER_AGENT: Final = "clouddoc-terraform-deploy-validator"

REPOSITORY_PATTERN: Final = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/"
    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$"
)
RUN_ID_PATTERN: Final = re.compile(r"^[1-9][0-9]*$")
COMMIT_SHA_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")


class DeploymentRequestError(ValueError):
    """Raised when a deployment request or GitHub API response is invalid."""


def validate_repository(value: str) -> str:
    """Require an exact owner/repository identifier."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DeploymentRequestError("Repository must be a non-empty owner/name value.")
    if not REPOSITORY_PATTERN.fullmatch(value):
        raise DeploymentRequestError("Repository must be a valid owner/name value.")
    owner, _, name = value.partition("/")
    if not owner or not name:
        raise DeploymentRequestError("Repository must include owner and name.")
    return value


def validate_run_id(value: str) -> int:
    """Require a positive decimal GitHub Actions run ID."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DeploymentRequestError("Run ID must be a positive decimal integer.")
    if not RUN_ID_PATTERN.fullmatch(value):
        raise DeploymentRequestError("Run ID must be a positive decimal integer.")
    return int(value)


def validate_commit_sha(value: str) -> str:
    """Require a lowercase 40-character commit SHA."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DeploymentRequestError(
            "Commit SHA must be a lowercase 40-character hex digest."
        )
    if not COMMIT_SHA_PATTERN.fullmatch(value):
        raise DeploymentRequestError(
            "Commit SHA must be a lowercase 40-character hex digest."
        )
    return value


def validate_maximum_age_hours(value: int) -> int:
    """Require a positive maximum age bound in hours."""
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise DeploymentRequestError("Maximum age hours must be a positive integer.")
    return value


def validate_api_url(value: str) -> str:
    """Require an absolute http(s) API base URL without credentials."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DeploymentRequestError("GitHub API URL is malformed.")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise DeploymentRequestError("GitHub API URL is malformed.")
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise DeploymentRequestError("GitHub API URL is malformed.")
    if parsed.query or parsed.fragment:
        raise DeploymentRequestError("GitHub API URL is malformed.")
    return value.rstrip("/")


def require_token(environ: Mapping[str, str]) -> str:
    """Require GITHUB_TOKEN without logging its value."""
    token = environ.get("GITHUB_TOKEN", "")
    if not isinstance(token, str) or not token.strip():
        raise DeploymentRequestError("GITHUB_TOKEN is required.")
    return token


def build_run_url(api_url: str, repository: str, run_id: int) -> str:
    """Build the workflow-run inspection URL."""
    owner, _, name = repository.partition("/")
    return (
        f"{api_url}/repos/{urllib.parse.quote(owner)}/"
        f"{urllib.parse.quote(name)}/actions/runs/{run_id}"
    )


def fetch_workflow_run(
    *,
    api_url: str,
    repository: str,
    run_id: int,
    token: str,
    opener: object | None = None,
) -> dict[str, object]:
    """GET one workflow run and return the JSON object body."""
    url = build_run_url(api_url, repository, run_id)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )

    urlopen = urllib.request.urlopen if opener is None else opener

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise DeploymentRequestError(
            f"GitHub workflow run lookup failed with HTTP {exc.code}."
        ) from None
    except TimeoutError as exc:
        raise DeploymentRequestError("GitHub workflow run lookup timed out.") from exc
    except urllib.error.URLError as exc:
        raise DeploymentRequestError(
            "GitHub workflow run lookup failed due to a network or URL error."
        ) from exc
    except OSError as exc:
        raise DeploymentRequestError(
            "GitHub workflow run lookup failed due to a network or URL error."
        ) from exc

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentRequestError(
            "GitHub workflow run response was not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise DeploymentRequestError(
            "GitHub workflow run response must be a JSON object."
        )
    return payload


def _require_string(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DeploymentRequestError(f"Workflow run response missing field: {key}.")
    return value


def _require_int(document: Mapping[str, object], key: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DeploymentRequestError(f"Workflow run response missing field: {key}.")
    return value


def _require_mapping(document: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = document.get(key)
    if not isinstance(value, Mapping):
        raise DeploymentRequestError(f"Workflow run response missing field: {key}.")
    return value


def parse_created_at(value: str, *, now: datetime) -> datetime:
    """Parse a timezone-aware UTC workflow timestamp and enforce age bounds helpers."""
    if not isinstance(value, str) or not value.strip():
        raise DeploymentRequestError("Workflow run created_at is malformed.")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise DeploymentRequestError("Workflow run created_at is malformed.") from exc
    if parsed.tzinfo is None:
        raise DeploymentRequestError(
            "Workflow run created_at must be timezone-aware UTC."
        )
    created_at = parsed.astimezone(UTC)
    if created_at - now > CLOCK_SKEW_ALLOWANCE:
        raise DeploymentRequestError(
            "Workflow run created_at is unreasonably in the future."
        )
    return created_at


def validate_workflow_run(
    document: Mapping[str, object],
    *,
    repository: str,
    run_id: int,
    expected_workflow_path: str,
    expected_ref: str,
    expected_commit_sha: str,
    expected_event: str,
    maximum_age_hours: int,
    now: datetime | None = None,
) -> tuple[int, str, str]:
    """Validate one GitHub workflow-run payload against the deployment contract."""
    current_time = datetime.now(UTC) if now is None else now
    if current_time.tzinfo is None:
        raise DeploymentRequestError("Validation clock must be timezone-aware UTC.")
    current_time = current_time.astimezone(UTC)

    actual_id = _require_int(document, "id")
    if actual_id != run_id:
        raise DeploymentRequestError(
            "Workflow run ID does not match the requested run."
        )

    repository_object = _require_mapping(document, "repository")
    full_name = _require_string(repository_object, "full_name")
    if full_name != repository:
        raise DeploymentRequestError("Workflow run repository does not match.")

    path = _require_string(document, "path")
    if path != expected_workflow_path:
        raise DeploymentRequestError("Workflow run path does not match Terraform Plan.")

    event = _require_string(document, "event")
    if event != expected_event:
        raise DeploymentRequestError("Workflow run event does not match.")

    head_branch = _require_string(document, "head_branch")
    if head_branch != "main":
        raise DeploymentRequestError("Workflow run head branch must be main.")

    if expected_ref != "refs/heads/main":
        raise DeploymentRequestError("Expected ref must be refs/heads/main.")

    head_sha = _require_string(document, "head_sha")
    if head_sha != expected_commit_sha:
        raise DeploymentRequestError("Workflow run commit SHA does not match.")

    status = _require_string(document, "status")
    if status != "completed":
        raise DeploymentRequestError("Workflow run is not completed.")

    conclusion = document.get("conclusion")
    if conclusion is None:
        raise DeploymentRequestError("Workflow run conclusion is missing.")
    if not isinstance(conclusion, str) or conclusion != "success":
        raise DeploymentRequestError("Workflow run conclusion must be success.")

    created_at_raw = _require_string(document, "created_at")
    created_at = parse_created_at(created_at_raw, now=current_time)
    age = current_time - created_at
    if age < timedelta(0):
        # Permitted only within the skew window already checked by parse_created_at.
        age = timedelta(0)
    maximum_age = timedelta(hours=maximum_age_hours)
    if age > maximum_age:
        raise DeploymentRequestError("Workflow run exceeds the maximum allowed age.")

    return actual_id, head_sha, created_at.strftime("%Y-%m-%dT%H:%M:%SZ")


def emit_success(run_id: int, commit_sha: str, created_at: str) -> None:
    """Print concise value-free success lines for workflow capture."""
    print(f"PLAN_RUN_ID={run_id}")
    print(f"PLAN_COMMIT_SHA={commit_sha}")
    print(f"PLAN_CREATED_AT={created_at}")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a referenced Terraform Plan workflow run "
            "before artifact download."
        )
    )
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--expected-workflow-path",
        default=DEFAULT_WORKFLOW_PATH,
    )
    parser.add_argument("--expected-ref", default=DEFAULT_REF)
    parser.add_argument("--expected-commit-sha", required=True)
    parser.add_argument("--expected-event", default=DEFAULT_EVENT)
    parser.add_argument(
        "--maximum-age-hours",
        type=int,
        default=DEFAULT_MAXIMUM_AGE_HOURS,
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    opener: object | None = None,
    now: datetime | None = None,
) -> int:
    """Validate one referenced plan workflow run."""
    arguments = build_argument_parser().parse_args(argv)
    current_environ = os.environ if environ is None else environ

    try:
        repository = validate_repository(arguments.repository)
        run_id = validate_run_id(arguments.run_id)
        commit_sha = validate_commit_sha(arguments.expected_commit_sha)
        maximum_age_hours = validate_maximum_age_hours(arguments.maximum_age_hours)
        token = require_token(current_environ)
        api_url = validate_api_url(
            current_environ.get("GITHUB_API_URL", DEFAULT_API_URL)
        )
        document = fetch_workflow_run(
            api_url=api_url,
            repository=repository,
            run_id=run_id,
            token=token,
            opener=opener,
        )
        validated_run_id, validated_sha, created_at = validate_workflow_run(
            document,
            repository=repository,
            run_id=run_id,
            expected_workflow_path=arguments.expected_workflow_path,
            expected_ref=arguments.expected_ref,
            expected_commit_sha=commit_sha,
            expected_event=arguments.expected_event,
            maximum_age_hours=maximum_age_hours,
            now=now,
        )
    except DeploymentRequestError as exc:
        print(f"Terraform deployment request validation failed: {exc}", file=sys.stderr)
        return 1

    emit_success(validated_run_id, validated_sha, created_at)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
