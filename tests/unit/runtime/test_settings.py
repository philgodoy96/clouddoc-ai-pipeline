"""Tests for runtime configuration loading."""

import pytest

from clouddoc.runtime import (
    JOBS_TABLE_NAME_ENV_VAR,
    RuntimeConfigurationError,
    RuntimeSettings,
)


def test_loads_jobs_table_name_from_environment_mapping() -> None:
    """A valid environment mapping should produce runtime settings."""
    settings = RuntimeSettings.from_environment(
        {
            JOBS_TABLE_NAME_ENV_VAR: "clouddoc-document-jobs",
        }
    )

    assert settings == RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
    )


def test_trims_jobs_table_name() -> None:
    """Surrounding whitespace should not become part of the table name."""
    settings = RuntimeSettings.from_environment(
        {
            JOBS_TABLE_NAME_ENV_VAR: ("  clouddoc-document-jobs  "),
        }
    )

    assert settings.jobs_table_name == "clouddoc-document-jobs"


def test_reads_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default loader should read the process environment."""
    monkeypatch.setenv(
        JOBS_TABLE_NAME_ENV_VAR,
        "clouddoc-document-jobs",
    )

    settings = RuntimeSettings.from_environment()

    assert settings.jobs_table_name == "clouddoc-document-jobs"


def test_explicit_environment_mapping_isolated_from_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit mapping should be the complete configuration source."""
    monkeypatch.setenv(
        JOBS_TABLE_NAME_ENV_VAR,
        "process-table",
    )

    settings = RuntimeSettings.from_environment(
        {
            JOBS_TABLE_NAME_ENV_VAR: "explicit-table",
        }
    )

    assert settings.jobs_table_name == "explicit-table"


def test_rejects_missing_jobs_table_name() -> None:
    """Startup should fail when the required table setting is absent."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=("missing required environment variable: CLOUDDOC_JOBS_TABLE_NAME"),
    ):
        RuntimeSettings.from_environment({})


@pytest.mark.parametrize(
    "table_name",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
    ],
)
def test_rejects_blank_jobs_table_name(
    table_name: str,
) -> None:
    """A configured table name must contain non-whitespace content."""
    with pytest.raises(
        RuntimeConfigurationError,
        match="CLOUDDOC_JOBS_TABLE_NAME must not be empty",
    ):
        RuntimeSettings.from_environment(
            {
                JOBS_TABLE_NAME_ENV_VAR: table_name,
            }
        )


def test_settings_are_immutable() -> None:
    """Runtime configuration should not change after startup."""
    settings = RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
    )

    with pytest.raises(AttributeError):
        settings.jobs_table_name = "other-table"
