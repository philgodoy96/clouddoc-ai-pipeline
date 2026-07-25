"""Tests for runtime configuration loading."""

import pytest

from clouddoc.runtime import (
    JOBS_TABLE_NAME_ENV_VAR,
    RuntimeConfigurationError,
    RuntimeSettings,
)
from clouddoc.runtime.settings import (
    DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS,
    DOCUMENTS_BUCKET_NAME_ENV_VAR,
    UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR,
)

VALID_JOBS_TABLE_NAME = "clouddoc-document-jobs"
VALID_DOCUMENTS_BUCKET_NAME = "clouddoc-documents"


def _valid_environment(
    **overrides: str,
) -> dict[str, str]:
    environment = {
        JOBS_TABLE_NAME_ENV_VAR: VALID_JOBS_TABLE_NAME,
        DOCUMENTS_BUCKET_NAME_ENV_VAR: VALID_DOCUMENTS_BUCKET_NAME,
    }
    environment.update(overrides)
    return environment


def test_loads_jobs_table_name_from_environment_mapping() -> None:
    """A valid environment mapping should produce runtime settings."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings == RuntimeSettings(
        jobs_table_name=VALID_JOBS_TABLE_NAME,
        documents_bucket_name=VALID_DOCUMENTS_BUCKET_NAME,
        upload_url_expiration_seconds=DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS,
    )


def test_trims_jobs_table_name() -> None:
    """Surrounding whitespace should not become part of the table name."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{
                JOBS_TABLE_NAME_ENV_VAR: ("  clouddoc-document-jobs  "),
            }
        )
    )

    assert settings.jobs_table_name == "clouddoc-document-jobs"


def test_loads_documents_bucket_name_from_environment_mapping() -> None:
    """A valid documents bucket name should load successfully."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.documents_bucket_name == VALID_DOCUMENTS_BUCKET_NAME


def test_trims_documents_bucket_name() -> None:
    """Surrounding whitespace should not become part of the bucket name."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{
                DOCUMENTS_BUCKET_NAME_ENV_VAR: ("  clouddoc-documents  "),
            }
        )
    )

    assert settings.documents_bucket_name == "clouddoc-documents"


def test_reads_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default loader should read the process environment."""
    monkeypatch.setenv(
        JOBS_TABLE_NAME_ENV_VAR,
        VALID_JOBS_TABLE_NAME,
    )
    monkeypatch.setenv(
        DOCUMENTS_BUCKET_NAME_ENV_VAR,
        VALID_DOCUMENTS_BUCKET_NAME,
    )

    settings = RuntimeSettings.from_environment()

    assert settings.jobs_table_name == VALID_JOBS_TABLE_NAME
    assert settings.documents_bucket_name == VALID_DOCUMENTS_BUCKET_NAME
    assert (
        settings.upload_url_expiration_seconds == DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS
    )


def test_explicit_environment_mapping_isolated_from_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit mapping should be the complete configuration source."""
    monkeypatch.setenv(
        JOBS_TABLE_NAME_ENV_VAR,
        "process-table",
    )
    monkeypatch.setenv(
        DOCUMENTS_BUCKET_NAME_ENV_VAR,
        "process-bucket",
    )
    monkeypatch.setenv(
        UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR,
        "1200",
    )

    settings = RuntimeSettings.from_environment(
        {
            JOBS_TABLE_NAME_ENV_VAR: "explicit-table",
            DOCUMENTS_BUCKET_NAME_ENV_VAR: "explicit-bucket",
        }
    )

    assert settings.jobs_table_name == "explicit-table"
    assert settings.documents_bucket_name == "explicit-bucket"
    assert (
        settings.upload_url_expiration_seconds == DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS
    )


def test_rejects_missing_jobs_table_name() -> None:
    """Startup should fail when the required table setting is absent."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=("missing required environment variable: CLOUDDOC_JOBS_TABLE_NAME"),
    ):
        RuntimeSettings.from_environment({})


def test_rejects_missing_documents_bucket_name() -> None:
    """Startup should fail when the required bucket setting is absent."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=("missing required environment variable: CLOUDDOC_DOCUMENTS_BUCKET_NAME"),
    ):
        RuntimeSettings.from_environment(
            {
                JOBS_TABLE_NAME_ENV_VAR: VALID_JOBS_TABLE_NAME,
            }
        )


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
            _valid_environment(
                **{JOBS_TABLE_NAME_ENV_VAR: table_name},
            )
        )


@pytest.mark.parametrize(
    "bucket_name",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
    ],
)
def test_rejects_blank_documents_bucket_name(
    bucket_name: str,
) -> None:
    """A configured bucket name must contain non-whitespace content."""
    with pytest.raises(
        RuntimeConfigurationError,
        match="CLOUDDOC_DOCUMENTS_BUCKET_NAME must not be empty",
    ):
        RuntimeSettings.from_environment(
            _valid_environment(
                **{DOCUMENTS_BUCKET_NAME_ENV_VAR: bucket_name},
            )
        )


def test_missing_upload_url_expiration_uses_default() -> None:
    """Missing expiration should fall back to the documented default."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.upload_url_expiration_seconds == 900


def test_loads_configured_upload_url_expiration() -> None:
    """A valid configured expiration should be parsed as an integer."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR: "600"},
        )
    )

    assert settings.upload_url_expiration_seconds == 600


def test_trims_upload_url_expiration() -> None:
    """Surrounding whitespace around a valid expiration should be accepted."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR: "  600  "},
        )
    )

    assert settings.upload_url_expiration_seconds == 600


@pytest.mark.parametrize(
    "expiration",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
        "0",
        "-1",
        "-900",
        "900.0",
        "abc",
        "6a0",
    ],
)
def test_rejects_invalid_upload_url_expiration(
    expiration: str,
) -> None:
    """Invalid expiration values must fail with a stable error message."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=("CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS must be a positive integer"),
    ):
        RuntimeSettings.from_environment(
            _valid_environment(
                **{UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR: expiration},
            )
        )


def test_settings_are_immutable() -> None:
    """Runtime configuration should not change after startup."""
    settings = RuntimeSettings(
        jobs_table_name=VALID_JOBS_TABLE_NAME,
        documents_bucket_name=VALID_DOCUMENTS_BUCKET_NAME,
        upload_url_expiration_seconds=900,
    )

    with pytest.raises(AttributeError):
        settings.jobs_table_name = "other-table"
