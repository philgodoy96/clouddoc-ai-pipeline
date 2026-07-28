"""Unit tests for Terraform deployment request validation."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = REPOSITORY_ROOT / "scripts"
VALIDATOR_PATH = SCRIPTS_ROOT / "validate_terraform_deployment_request.py"


def load_validator_module() -> ModuleType:
    """Load the deployment-request validator script as a module."""

    spec = importlib.util.spec_from_file_location(
        "clouddoc_validate_terraform_deployment_request",
        VALIDATOR_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load validator module: {VALIDATOR_PATH}")

    sys.path.insert(0, str(SCRIPTS_ROOT))
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS_ROOT))
    return module


validator = load_validator_module()

TOKEN = "ghs_test-token-do-not-leak"
REPOSITORY = "philgodoy96/clouddoc-ai-pipeline"
RUN_ID = "123456789"
COMMIT_SHA = "0123456789abcdef0123456789abcdef01234567"
NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=UTC)


class FakeResponse:
    """Minimal urllib response double."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class RecordingOpener:
    """Capture the outbound request and return a canned response."""

    def __init__(self, body: bytes | Exception) -> None:
        self.body = body
        self.requests: list[Request] = []
        self.timeouts: list[float | None] = []

    def __call__(self, request: Request, timeout: float | None = None) -> FakeResponse:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.body, Exception):
            raise self.body
        return FakeResponse(self.body)


def valid_run_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": int(RUN_ID),
        "path": ".github/workflows/terraform-plan.yml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": COMMIT_SHA,
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-07-28T11:00:00Z",
        "repository": {"full_name": REPOSITORY},
        "actor": {"login": "should-not-print"},
        "html_url": "https://github.com/example/should-not-print",
        "workflow_id": 999,
        "sensitive_sentinel": "SECRET-SENTINEL-VALUE",
    }
    payload.update(overrides)
    return payload


def run_main(
    *,
    opener: RecordingOpener,
    argv: list[str] | None = None,
    environ: dict[str, str] | None = None,
    now: datetime = NOW,
) -> int:
    arguments = argv or [
        "--repository",
        REPOSITORY,
        "--run-id",
        RUN_ID,
        "--expected-workflow-path",
        ".github/workflows/terraform-plan.yml",
        "--expected-ref",
        "refs/heads/main",
        "--expected-commit-sha",
        COMMIT_SHA,
        "--expected-event",
        "workflow_dispatch",
        "--maximum-age-hours",
        "24",
    ]
    env = {"GITHUB_TOKEN": TOKEN} if environ is None else environ
    return validator.main(arguments, environ=env, opener=opener, now=now)


@pytest.mark.parametrize(
    "repository",
    [
        REPOSITORY,
        "org/repo",
        "a/b",
    ],
)
def test_valid_repository_is_accepted(repository: str) -> None:
    assert validator.validate_repository(repository) == repository


@pytest.mark.parametrize(
    "repository",
    [
        "/repo",
        "owner/",
        "owner",
        "",
        " owner/repo",
        "owner/repo ",
        "owner /repo",
    ],
)
def test_invalid_repository_is_rejected(repository: str) -> None:
    with pytest.raises(validator.DeploymentRequestError):
        validator.validate_repository(repository)


@pytest.mark.parametrize(
    "run_id",
    ["0", "-1", "01", "1.5", "abc", "", " 1", "1 "],
)
def test_invalid_run_id_is_rejected(run_id: str) -> None:
    with pytest.raises(validator.DeploymentRequestError):
        validator.validate_run_id(run_id)


def test_zero_run_id_is_rejected() -> None:
    with pytest.raises(validator.DeploymentRequestError):
        validator.validate_run_id("0")


@pytest.mark.parametrize(
    "sha",
    [
        "0123456789ABCDEF0123456789abcdef01234567",
        "0123456789abcdef0123456789abcdef0123456",
        "0123456789abcdef0123456789abcdef012345678",
        "gggggggggggggggggggggggggggggggggggggggg",
        "",
        f" {COMMIT_SHA}",
    ],
)
def test_invalid_expected_sha_is_rejected(sha: str) -> None:
    with pytest.raises(validator.DeploymentRequestError):
        validator.validate_commit_sha(sha)


def test_uppercase_sha_is_rejected() -> None:
    with pytest.raises(validator.DeploymentRequestError):
        validator.validate_commit_sha("0123456789ABCDEF0123456789ABCDEF01234567")


@pytest.mark.parametrize("age", [0, -1, True])
def test_invalid_maximum_age_is_rejected(age: object) -> None:
    with pytest.raises(validator.DeploymentRequestError):
        validator.validate_maximum_age_hours(age)  # type: ignore[arg-type]


def test_missing_token_is_rejected(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(b"{}")
    code = run_main(opener=opener, environ={})
    captured = capsys.readouterr()
    assert code == 1
    assert "GITHUB_TOKEN" in captured.err
    assert TOKEN not in captured.err
    assert opener.requests == []


@pytest.mark.parametrize(
    "api_url",
    [
        "ftp://api.github.com",
        "https://user:pass@api.github.com",
        "https://api.github.com?x=1",
        "https://api.github.com#frag",
        "not-a-url",
        "",
        " https://api.github.com",
    ],
)
def test_malformed_api_url_is_rejected(
    api_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(b"{}")
    code = run_main(
        opener=opener,
        environ={"GITHUB_TOKEN": TOKEN, "GITHUB_API_URL": api_url},
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "API URL" in captured.err or "malformed" in captured.err.lower()
    assert TOKEN not in captured.err
    assert opener.requests == []


def test_http_request_contract(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(json.dumps(valid_run_payload()).encode("utf-8"))
    code = run_main(opener=opener)
    assert code == 0
    assert len(opener.requests) == 1
    request = opener.requests[0]
    assert request.full_url == (
        f"https://api.github.com/repos/{REPOSITORY}/actions/runs/{RUN_ID}"
    )
    assert request.get_method() == "GET"
    assert request.get_header("Accept") == "application/vnd.github+json"
    assert request.get_header("X-github-api-version") == "2026-03-10"
    assert request.get_header("User-agent") == "clouddoc-terraform-deploy-validator"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert opener.timeouts == [10]
    captured = capsys.readouterr()
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    assert "Authorization" not in captured.out
    assert "Authorization" not in captured.err


def test_valid_completed_successful_run_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(json.dumps(valid_run_payload()).encode("utf-8"))
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 0
    assert f"PLAN_RUN_ID={RUN_ID}" in captured.out
    assert f"PLAN_COMMIT_SHA={COMMIT_SHA}" in captured.out
    assert "PLAN_CREATED_AT=2026-07-28T11:00:00Z" in captured.out
    assert TOKEN not in captured.out
    assert "sensitive_sentinel" not in captured.out
    assert "workflow_id" not in captured.out
    assert "SECRET-SENTINEL-VALUE" not in captured.out
    assert "{" not in captured.out


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"id": 999}, "run ID"),
        ({"repository": {"full_name": "other/repo"}}, "repository"),
        ({"repository": "not-an-object"}, "repository"),
        ({"path": ".github/workflows/other.yml"}, "path"),
        ({"event": "push"}, "event"),
        ({"head_branch": "feature"}, "branch"),
        ({"head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, "commit"),
        ({"status": "queued"}, "completed"),
        ({"status": "in_progress"}, "completed"),
        ({"conclusion": "failure"}, "success"),
        ({"conclusion": "cancelled"}, "success"),
        ({"conclusion": None}, "conclusion"),
    ],
)
def test_identity_mismatches_fail(
    overrides: dict[str, Any],
    needle: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(json.dumps(valid_run_payload(**overrides)).encode("utf-8"))
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert needle.lower() in captured.err.lower()
    assert TOKEN not in captured.err
    assert "Traceback" not in captured.err
    assert "SECRET-SENTINEL-VALUE" not in captured.err


def test_missing_repository_object_fails(capsys: pytest.CaptureFixture[str]) -> None:
    payload = valid_run_payload()
    del payload["repository"]
    opener = RecordingOpener(json.dumps(payload).encode("utf-8"))
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "repository" in captured.err.lower()


def test_current_run_passes(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(
        json.dumps(
            valid_run_payload(created_at=NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ).encode("utf-8")
    )
    assert run_main(opener=opener) == 0
    assert "PLAN_RUN_ID=" in capsys.readouterr().out


def test_exactly_maximum_age_boundary_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    created = NOW - timedelta(hours=24)
    opener = RecordingOpener(
        json.dumps(
            valid_run_payload(created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ).encode("utf-8")
    )
    assert run_main(opener=opener) == 0
    assert capsys.readouterr().out


def test_expired_run_fails(capsys: pytest.CaptureFixture[str]) -> None:
    created = NOW - timedelta(hours=24, seconds=1)
    opener = RecordingOpener(
        json.dumps(
            valid_run_payload(created_at=created.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ).encode("utf-8")
    )
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "age" in captured.err.lower()


@pytest.mark.parametrize(
    "created_at",
    [
        "not-a-timestamp",
        "2026-07-28 11:00:00",
        "2026-13-40T99:99:99Z",
    ],
)
def test_malformed_timestamp_fails(
    created_at: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(
        json.dumps(valid_run_payload(created_at=created_at)).encode("utf-8")
    )
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "created_at" in captured.err.lower() or "malformed" in captured.err.lower()


def test_naive_timestamp_fails(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(
        json.dumps(valid_run_payload(created_at="2026-07-28T11:00:00")).encode("utf-8")
    )
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "timezone" in captured.err.lower() or "created_at" in captured.err.lower()


def test_excessive_future_timestamp_fails(capsys: pytest.CaptureFixture[str]) -> None:
    future = NOW + timedelta(minutes=6)
    opener = RecordingOpener(
        json.dumps(
            valid_run_payload(created_at=future.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ).encode("utf-8")
    )
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "future" in captured.err.lower()


def test_permitted_clock_skew_passes(capsys: pytest.CaptureFixture[str]) -> None:
    future = NOW + timedelta(minutes=5)
    opener = RecordingOpener(
        json.dumps(
            valid_run_payload(created_at=future.strftime("%Y-%m-%dT%H:%M:%SZ"))
        ).encode("utf-8")
    )
    assert run_main(opener=opener) == 0
    assert "PLAN_RUN_ID=" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, "401"),
        (403, "403"),
        (404, "404"),
        (429, "429"),
        (500, "500"),
    ],
)
def test_http_errors_fail_concisely(
    status: int,
    needle: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = HTTPError(
        url="https://api.github.com/repos/x/y/actions/runs/1",
        code=status,
        msg="error",
        hdrs=None,
        fp=io.BytesIO(b"{}"),
    )
    opener = RecordingOpener(error)
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert needle in captured.err
    assert TOKEN not in captured.err
    assert "Traceback" not in captured.err
    assert "Authorization" not in captured.err


def test_timeout_fails_concisely(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(TimeoutError())
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "timed out" in captured.err.lower()
    assert TOKEN not in captured.err
    assert "Traceback" not in captured.err


def test_connection_failure_fails_concisely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(URLError("connection refused"))
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "network" in captured.err.lower()
    assert TOKEN not in captured.err
    assert "Traceback" not in captured.err


def test_malformed_json_fails(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(b"{not-json")
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "json" in captured.err.lower()


def test_non_object_json_fails(capsys: pytest.CaptureFixture[str]) -> None:
    opener = RecordingOpener(b'["not", "an", "object"]')
    code = run_main(opener=opener)
    captured = capsys.readouterr()
    assert code == 1
    assert "object" in captured.err.lower()


def test_token_never_appears_in_success_or_failure_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(json.dumps(valid_run_payload()).encode("utf-8"))
    assert run_main(opener=opener) == 0
    success = capsys.readouterr()
    assert TOKEN not in success.out
    assert TOKEN not in success.err

    opener = RecordingOpener(
        HTTPError(
            url="https://api.github.com",
            code=401,
            msg="unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"{}"),
        )
    )
    assert run_main(opener=opener) == 1
    failure = capsys.readouterr()
    assert TOKEN not in failure.out
    assert TOKEN not in failure.err
    assert "Authorization" not in failure.err
    assert "SECRET-SENTINEL-VALUE" not in failure.err
    assert "Traceback" not in failure.err


def test_complete_response_is_never_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    opener = RecordingOpener(json.dumps(valid_run_payload()).encode("utf-8"))
    assert run_main(opener=opener) == 0
    captured = capsys.readouterr()
    assert "should-not-print" not in captured.out
    assert "workflow_id" not in captured.out
    assert "sensitive_sentinel" not in captured.out
