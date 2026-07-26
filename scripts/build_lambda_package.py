"""Build the shared CloudDoc AWS Lambda deployment package."""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REQUIRED_PYTHON: Final = (3, 12)
ZIP_TIMESTAMP: Final = (1980, 1, 1, 0, 0, 0)
FORBIDDEN_TOP_LEVEL: Final = {
    ".git",
    ".github",
    ".venv",
    "docs",
    "infra",
    "src",
    "tests",
}


class PackagingError(RuntimeError):
    """Raised when the Lambda package cannot be built safely."""


@dataclass(frozen=True, slots=True)
class BuildPaths:
    """Filesystem boundaries for the shared Lambda artifact."""

    root: Path
    source_root: Path
    source_package: Path
    lock_file: Path
    staging: Path
    artifact: Path
    checksum: Path

    @classmethod
    def from_root(cls, root: Path) -> BuildPaths:
        resolved = root.resolve()
        artifact = resolved / "artifacts" / "lambda" / "clouddoc-app.zip"

        return cls(
            root=resolved,
            source_root=resolved / "src",
            source_package=resolved / "src" / "clouddoc",
            lock_file=resolved / "requirements" / "lambda.lock.txt",
            staging=resolved / ".lambda-build" / "clouddoc-app",
            artifact=artifact,
            checksum=artifact.with_suffix(".sha256"),
        )


def validate_python_version() -> None:
    """Require the Python minor selected for the Lambda runtime."""
    if sys.version_info[:2] == REQUIRED_PYTHON:
        return

    expected = ".".join(str(part) for part in REQUIRED_PYTHON)
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"

    raise PackagingError(f"Python {expected} is required; found Python {actual}.")


def validate_runtime_lock(lock_file: Path) -> None:
    """Require a fully pinned, hash-verified runtime lock."""
    if not lock_file.is_file():
        raise PackagingError(f"Runtime lock not found: {lock_file}")

    content = lock_file.read_text(encoding="utf-8")

    if "--hash=sha256:" not in content:
        raise PackagingError("Runtime lock must contain SHA-256 hashes.")

    requirement_lines = [
        line.rstrip("\\").strip()
        for line in content.splitlines()
        if (line and not line[0].isspace() and not line.startswith(("#", "--")))
    ]

    if not requirement_lines:
        raise PackagingError("Runtime lock does not contain dependencies.")

    if any("==" not in line for line in requirement_lines):
        raise PackagingError("Every runtime dependency must be exactly pinned.")

    for dependency in ("boto3", "pydantic"):
        dependency_prefix = f"{dependency}=="

        if not any(
            line.lower().startswith(dependency_prefix) for line in requirement_lines
        ):
            raise PackagingError(
                f"Runtime lock is missing direct dependency: {dependency}"
            )


def discover_handler_modules(
    source_package: Path,
) -> tuple[str, ...]:
    """Discover public modules under clouddoc.handlers."""
    handlers_dir = source_package / "handlers"

    if not handlers_dir.is_dir():
        raise PackagingError(f"Handler package not found: {handlers_dir}")

    modules = tuple(
        "clouddoc."
        + (
            path.relative_to(source_package)
            .with_suffix("")
            .as_posix()
            .replace("/", ".")
        )
        for path in sorted(handlers_dir.rglob("*.py"))
        if (path.name != "__init__.py" and not path.stem.startswith("_"))
    )

    if not modules:
        raise PackagingError("No public Lambda handler modules were discovered.")

    return modules


def validate_handler_imports(
    source_root: Path,
    handler_modules: Sequence[str],
) -> None:
    """Import source handlers and require callable Lambda entrypoints."""
    source_root_text = str(source_root)

    sys.path.insert(0, source_root_text)
    importlib.invalidate_caches()

    try:
        for module_name in handler_modules:
            try:
                module = importlib.import_module(module_name)
            except Exception as error:
                raise PackagingError(
                    f"Could not import handler module: {module_name}"
                ) from error

            lambda_handler = getattr(
                module,
                "lambda_handler",
                None,
            )

            if not callable(lambda_handler):
                raise PackagingError(
                    f"Handler lacks callable lambda_handler: {module_name}"
                )
    finally:
        if source_root_text in sys.path:
            sys.path.remove(source_root_text)


def reset_build_outputs(paths: BuildPaths) -> None:
    """Remove stale staging and generated artifacts."""
    for path in (
        paths.staging,
        paths.artifact,
        paths.checksum,
    ):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def install_runtime_dependencies(paths: BuildPaths) -> None:
    """Install locked Linux x86_64 wheels into staging."""
    paths.staging.mkdir(
        parents=True,
        exist_ok=True,
    )

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-compile",
        "--no-warn-script-location",
        "--require-hashes",
        "--only-binary=:all:",
        "--platform",
        "manylinux2014_x86_64",
        "--implementation",
        "cp",
        "--python-version",
        "3.12",
        "--abi",
        "cp312",
        "--target",
        str(paths.staging),
        "--requirement",
        str(paths.lock_file),
    ]

    try:
        subprocess.run(
            command,
            cwd=paths.root,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        raise PackagingError(
            "Failed to install locked Lambda runtime dependencies."
        ) from error


def copy_application(paths: BuildPaths) -> None:
    """Copy src/clouddoc to clouddoc at the package root."""
    if not paths.source_package.is_dir():
        raise PackagingError(f"Application package not found: {paths.source_package}")

    destination = paths.staging / "clouddoc"

    if destination.exists():
        raise PackagingError(f"Unexpected package collision in staging: {destination}")

    shutil.copytree(
        paths.source_package,
        destination,
    )


def remove_transient_files(staging: Path) -> None:
    """Remove caches and console scripts from staging."""
    for cache_dir in staging.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir)

    for pattern in (
        "*.pyc",
        "*.pyo",
        ".DS_Store",
        "Thumbs.db",
    ):
        for path in staging.rglob(pattern):
            if path.is_file() or path.is_symlink():
                path.unlink()

    for directory_name in (
        "bin",
        "Scripts",
    ):
        directory = staging / directory_name

        if directory.is_dir():
            shutil.rmtree(directory)


def collect_package_files(
    staging: Path,
    handler_modules: Sequence[str],
) -> tuple[Path, ...]:
    """Validate package layout and return files in archive order."""
    required_paths = [
        staging / "clouddoc" / "__init__.py",
        staging / "boto3" / "__init__.py",
        staging / "pydantic" / "__init__.py",
    ]

    required_paths.extend(
        staging / Path(*module_name.split(".")).with_suffix(".py")
        for module_name in handler_modules
    )

    missing_paths = [
        path.relative_to(staging).as_posix()
        for path in required_paths
        if not path.is_file()
    ]

    if missing_paths:
        raise PackagingError(
            "Package staging is missing required files: " + ", ".join(missing_paths)
        )

    top_level_names = {path.name for path in staging.iterdir()}

    forbidden_paths = sorted(top_level_names.intersection(FORBIDDEN_TOP_LEVEL))

    if forbidden_paths:
        raise PackagingError(
            "Package staging contains forbidden paths: " + ", ".join(forbidden_paths)
        )

    files = tuple(
        sorted(
            (path for path in staging.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(staging).as_posix(),
        )
    )

    if not files:
        raise PackagingError("Package staging is empty.")

    for path in files:
        relative_path = path.relative_to(staging)

        if path.is_symlink():
            raise PackagingError(f"Package contains symlink: {relative_path}")

        if "__pycache__" in relative_path.parts or path.suffix in {".pyc", ".pyo"}:
            raise PackagingError(f"Package contains cache data: {relative_path}")

    return files


def write_deterministic_zip(
    staging: Path,
    artifact: Path,
    files: Sequence[Path],
) -> None:
    """Write a ZIP with stable order, timestamps, and permissions."""
    artifact.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_artifact = artifact.parent / f".{artifact.name}.tmp"

    temporary_artifact.unlink(
        missing_ok=True,
    )

    try:
        with zipfile.ZipFile(
            temporary_artifact,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in files:
                archive_name = path.relative_to(staging).as_posix()

                zip_info = zipfile.ZipInfo(
                    archive_name,
                    ZIP_TIMESTAMP,
                )

                zip_info.compress_type = zipfile.ZIP_DEFLATED
                zip_info.create_system = 3
                zip_info.external_attr = (0o100644 & 0xFFFF) << 16

                archive.writestr(
                    zip_info,
                    path.read_bytes(),
                    compress_type=(zipfile.ZIP_DEFLATED),
                    compresslevel=9,
                )

        os.replace(
            temporary_artifact,
            artifact,
        )
    except Exception:
        temporary_artifact.unlink(
            missing_ok=True,
        )
        raise


def calculate_sha256(path: Path) -> str:
    """Calculate a file SHA-256 digest."""
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def build_package(paths: BuildPaths) -> str:
    """Build the shared Lambda deployment artifact."""
    validate_python_version()
    validate_runtime_lock(paths.lock_file)

    handler_modules = discover_handler_modules(paths.source_package)

    validate_handler_imports(
        paths.source_root,
        handler_modules,
    )

    reset_build_outputs(paths)

    install_runtime_dependencies(paths)
    copy_application(paths)
    remove_transient_files(paths.staging)

    package_files = collect_package_files(
        paths.staging,
        handler_modules,
    )

    write_deterministic_zip(
        paths.staging,
        paths.artifact,
        package_files,
    )

    digest = calculate_sha256(paths.artifact)

    paths.checksum.write_text(
        f"{digest}  {paths.artifact.name}\n",
        encoding="utf-8",
        newline="\n",
    )

    return digest


def main() -> int:
    """Build the package from the repository root."""
    repository_root = Path(__file__).resolve().parents[1]

    paths = BuildPaths.from_root(repository_root)

    try:
        digest = build_package(paths)
    except (
        OSError,
        PackagingError,
    ) as error:
        print(
            f"Lambda packaging failed: {error}",
            file=sys.stderr,
        )
        return 1

    print(f"Artifact: {paths.artifact}")
    print(f"Checksum: {paths.checksum}")
    print(f"Size: {paths.artifact.stat().st_size} bytes")
    print(f"SHA-256: {digest}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
