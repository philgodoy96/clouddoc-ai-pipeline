"""Tests for the deterministic Lambda package builder."""

from __future__ import annotations

import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from scripts import build_lambda_package as builder


def _purge_clouddoc_modules() -> None:
    """Remove temporary CloudDoc modules from the import cache."""
    for module_name in tuple(sys.modules):
        if module_name == "clouddoc" or module_name.startswith("clouddoc."):
            sys.modules.pop(module_name, None)


def _snapshot_clouddoc_modules() -> dict[str, object]:
    """Capture currently loaded CloudDoc modules for later restoration."""
    return {
        module_name: module
        for module_name, module in sys.modules.items()
        if module_name == "clouddoc" or module_name.startswith("clouddoc.")
    }


@pytest.fixture(autouse=True)
def purge_clouddoc_modules() -> Iterator[None]:
    """Isolate temporary handler imports without breaking later suite tests.

    Builder validation may import a fake ``clouddoc`` package from a temp
    tree. Clearing ``sys.modules`` afterwards is required so that package
    does not leak, but the pre-existing real modules must be restored.
    Otherwise later tests can mix objects from the original import with a
    freshly reloaded ``InvalidDomainValueError`` class and fail
    ``pytest.raises`` identity checks.
    """
    preexisting = _snapshot_clouddoc_modules()
    _purge_clouddoc_modules()
    try:
        yield
    finally:
        _purge_clouddoc_modules()
        sys.modules.update(preexisting)


def _write_file(path: Path, content: str = "") -> Path:
    """Create a UTF-8 file and all missing parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _create_fake_repository(root: Path) -> builder.BuildPaths:
    """Create the minimum repository structure required by the builder."""
    paths = builder.BuildPaths.from_root(root)

    _write_file(paths.source_package / "__init__.py")
    _write_file(paths.source_package / "handlers" / "__init__.py")
    _write_file(
        paths.source_package / "handlers" / "create_job.py",
        "def lambda_handler(event, context):\n    return {'statusCode': 201}\n",
    )
    _write_file(
        paths.lock_file,
        "boto3==1.40.0 \\\n"
        "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "pydantic==2.11.0 \\\n"
        "    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n",
    )

    return paths


def _create_fake_runtime_dependencies(staging: Path) -> None:
    """Create dependency fixtures without invoking pip or a network."""
    _write_file(
        staging / "boto3" / "__init__.py",
        "__version__ = '1.40.0'\n",
    )
    _write_file(
        staging / "pydantic" / "__init__.py",
        "__version__ = '2.11.0'\n",
    )
    _write_file(
        staging / "pydantic_core" / "_pydantic_core.so",
        "fixture",
    )


def _create_valid_staging(staging: Path) -> None:
    """Create the minimum valid package-staging layout."""
    _write_file(staging / "clouddoc" / "__init__.py")
    _write_file(staging / "clouddoc" / "handlers" / "create_job.py")
    _write_file(staging / "boto3" / "__init__.py")
    _write_file(staging / "pydantic" / "__init__.py")


def test_validate_runtime_lock_accepts_pinned_hashed_dependencies(
    tmp_path: Path,
) -> None:
    paths = _create_fake_repository(tmp_path)

    builder.validate_runtime_lock(paths.lock_file)


@pytest.mark.parametrize(
    ("content", "expected_message"),
    [
        (
            "boto3==1.40.0\npydantic==2.11.0\n",
            "Runtime lock must contain SHA-256 hashes.",
        ),
        (
            "boto3>=1.40 \\\n"
            "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "pydantic==2.11.0 \\\n"
            "    --hash=sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n",
            "Every runtime dependency must be exactly pinned.",
        ),
        (
            "boto3==1.40.0 \\\n"
            "    --hash=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            "Runtime lock is missing direct dependency: pydantic",
        ),
    ],
)
def test_validate_runtime_lock_rejects_invalid_content(
    tmp_path: Path,
    content: str,
    expected_message: str,
) -> None:
    lock_file = _write_file(tmp_path / "lambda.lock.txt", content)

    with pytest.raises(builder.PackagingError, match=expected_message):
        builder.validate_runtime_lock(lock_file)


def test_discover_handler_modules_returns_sorted_public_modules(
    tmp_path: Path,
) -> None:
    source_package = tmp_path / "clouddoc"

    _write_file(source_package / "handlers" / "__init__.py")
    _write_file(source_package / "handlers" / "process.py")
    _write_file(source_package / "handlers" / "admin" / "reconcile.py")
    _write_file(source_package / "handlers" / "_internal.py")

    assert builder.discover_handler_modules(source_package) == (
        "clouddoc.handlers.admin.reconcile",
        "clouddoc.handlers.process",
    )


def test_validate_handler_imports_requires_callable_entrypoint(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "src"
    source_package = source_root / "clouddoc"

    _write_file(source_package / "__init__.py")
    _write_file(source_package / "handlers" / "__init__.py")
    _write_file(
        source_package / "handlers" / "valid.py",
        "def lambda_handler(event, context):\n    return None\n",
    )

    builder.validate_handler_imports(
        source_root,
        ("clouddoc.handlers.valid",),
    )

    _purge_clouddoc_modules()

    _write_file(
        source_package / "handlers" / "invalid.py",
        "lambda_handler = None\n",
    )

    with pytest.raises(
        builder.PackagingError,
        match="Handler lacks callable lambda_handler",
    ):
        builder.validate_handler_imports(
            source_root,
            ("clouddoc.handlers.invalid",),
        )


def test_reset_build_outputs_removes_stale_content(
    tmp_path: Path,
) -> None:
    paths = builder.BuildPaths.from_root(tmp_path)

    _write_file(paths.staging / "stale.txt", "stale")
    _write_file(paths.artifact, "stale")
    _write_file(paths.checksum, "stale")

    builder.reset_build_outputs(paths)

    assert not paths.staging.exists()
    assert not paths.artifact.exists()
    assert not paths.checksum.exists()


def test_remove_transient_files_removes_caches_and_scripts(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"

    _write_file(staging / "clouddoc" / "handler.py", "content")
    _write_file(
        staging / "clouddoc" / "__pycache__" / "handler.pyc",
        "cache",
    )
    _write_file(staging / "dependency.pyo", "cache")
    _write_file(staging / "bin" / "tool", "script")
    _write_file(staging / "Scripts" / "tool.exe", "script")

    builder.remove_transient_files(staging)

    assert (staging / "clouddoc" / "handler.py").is_file()
    assert not (staging / "clouddoc" / "__pycache__").exists()
    assert not (staging / "dependency.pyo").exists()
    assert not (staging / "bin").exists()
    assert not (staging / "Scripts").exists()


def test_collect_package_files_returns_stable_sorted_order(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    _create_valid_staging(staging)
    _write_file(staging / "zeta.txt", "zeta")
    _write_file(staging / "alpha.txt", "alpha")

    files = builder.collect_package_files(
        staging,
        ("clouddoc.handlers.create_job",),
    )

    names = [path.relative_to(staging).as_posix() for path in files]

    assert names == sorted(names)


def test_collect_package_files_rejects_forbidden_top_level_path(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    _create_valid_staging(staging)
    _write_file(staging / "src" / "unexpected.py")

    with pytest.raises(
        builder.PackagingError,
        match="Package staging contains forbidden paths: src",
    ):
        builder.collect_package_files(
            staging,
            ("clouddoc.handlers.create_job",),
        )


def test_write_deterministic_zip_normalizes_archive_metadata(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    artifact = tmp_path / "artifacts" / "clouddoc-app.zip"

    alpha = _write_file(staging / "alpha.txt", "alpha")
    zeta = _write_file(staging / "zeta.txt", "zeta")
    files = (alpha, zeta)

    builder.write_deterministic_zip(staging, artifact, files)
    first_digest = builder.calculate_sha256(artifact)

    builder.write_deterministic_zip(staging, artifact, files)
    second_digest = builder.calculate_sha256(artifact)

    assert first_digest == second_digest

    with zipfile.ZipFile(artifact) as archive:
        assert archive.namelist() == ["alpha.txt", "zeta.txt"]

        for entry in archive.infolist():
            assert entry.date_time == builder.ZIP_TIMESTAMP
            assert entry.create_system == 3
            assert (entry.external_attr >> 16) & 0o777 == 0o644


def test_build_package_creates_stable_offline_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _create_fake_repository(tmp_path)

    monkeypatch.setattr(
        builder,
        "validate_python_version",
        lambda: None,
    )

    def install_fixture_dependencies(
        build_paths: builder.BuildPaths,
    ) -> None:
        build_paths.staging.mkdir(parents=True, exist_ok=True)
        _create_fake_runtime_dependencies(build_paths.staging)

    monkeypatch.setattr(
        builder,
        "install_runtime_dependencies",
        install_fixture_dependencies,
    )

    first_digest = builder.build_package(paths)

    assert paths.artifact.is_file()
    assert paths.checksum.read_text(encoding="utf-8") == (
        f"{first_digest}  clouddoc-app.zip\n"
    )

    with zipfile.ZipFile(paths.artifact) as archive:
        names = set(archive.namelist())

    assert "clouddoc/__init__.py" in names
    assert "clouddoc/handlers/create_job.py" in names
    assert "boto3/__init__.py" in names
    assert "pydantic/__init__.py" in names
    assert "pydantic_core/_pydantic_core.so" in names
    assert not any(name.startswith("src/") for name in names)
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith((".pyc", ".pyo")) for name in names)

    second_digest = builder.build_package(paths)

    assert second_digest == first_digest
    assert builder.calculate_sha256(paths.artifact) == first_digest
