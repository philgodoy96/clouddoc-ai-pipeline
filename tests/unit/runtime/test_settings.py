"""Tests for runtime configuration loading."""

import pytest

from clouddoc.runtime import (
    JOBS_TABLE_NAME_ENV_VAR,
    RuntimeConfigurationError,
    RuntimeSettings,
)
from clouddoc.runtime.settings import (
    AI_PROVIDER_ENV_VAR,
    BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR,
    BEDROCK_MODEL_ID_ENV_VAR,
    BEDROCK_TEMPERATURE_ENV_VAR,
    DEFAULT_AI_PROVIDER,
    DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS,
    DEFAULT_BEDROCK_TEMPERATURE,
    DEFAULT_MAX_DOCUMENT_SIZE_BYTES,
    DEFAULT_PROCESSING_LEASE_DURATION_SECONDS,
    DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS,
    DOCUMENTS_BUCKET_NAME_ENV_VAR,
    MAX_DOCUMENT_SIZE_BYTES_ENV_VAR,
    PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR,
    UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR,
)

VALID_JOBS_TABLE_NAME = "clouddoc-document-jobs"
VALID_DOCUMENTS_BUCKET_NAME = "clouddoc-documents"
VALID_BEDROCK_MODEL_ID = "amazon.nova-micro-v1:0"


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
        processing_lease_duration_seconds=DEFAULT_PROCESSING_LEASE_DURATION_SECONDS,
        max_document_size_bytes=DEFAULT_MAX_DOCUMENT_SIZE_BYTES,
    )
    assert settings.ai_provider == DEFAULT_AI_PROVIDER
    assert settings.bedrock_model_id is None
    assert settings.bedrock_max_output_tokens == DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS
    assert settings.bedrock_temperature == DEFAULT_BEDROCK_TEMPERATURE


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
    monkeypatch.delenv(AI_PROVIDER_ENV_VAR, raising=False)
    monkeypatch.delenv(BEDROCK_MODEL_ID_ENV_VAR, raising=False)
    monkeypatch.delenv(BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR, raising=False)
    monkeypatch.delenv(BEDROCK_TEMPERATURE_ENV_VAR, raising=False)

    settings = RuntimeSettings.from_environment()

    assert settings.jobs_table_name == VALID_JOBS_TABLE_NAME
    assert settings.documents_bucket_name == VALID_DOCUMENTS_BUCKET_NAME
    assert (
        settings.upload_url_expiration_seconds == DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS
    )
    assert settings.max_document_size_bytes == DEFAULT_MAX_DOCUMENT_SIZE_BYTES
    assert settings.ai_provider == DEFAULT_AI_PROVIDER
    assert settings.bedrock_model_id is None
    assert settings.bedrock_max_output_tokens == DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS
    assert settings.bedrock_temperature == DEFAULT_BEDROCK_TEMPERATURE


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
    monkeypatch.setenv(
        MAX_DOCUMENT_SIZE_BYTES_ENV_VAR,
        "131072",
    )
    monkeypatch.setenv(AI_PROVIDER_ENV_VAR, "bedrock")
    monkeypatch.setenv(BEDROCK_MODEL_ID_ENV_VAR, "process-model")
    monkeypatch.setenv(BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR, "5000")
    monkeypatch.setenv(BEDROCK_TEMPERATURE_ENV_VAR, "1.0")

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
    assert settings.max_document_size_bytes == DEFAULT_MAX_DOCUMENT_SIZE_BYTES
    assert settings.ai_provider == DEFAULT_AI_PROVIDER
    assert settings.bedrock_model_id is None
    assert settings.bedrock_max_output_tokens == DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS
    assert settings.bedrock_temperature == DEFAULT_BEDROCK_TEMPERATURE


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


def test_missing_processing_lease_duration_uses_default() -> None:
    """Missing lease duration should fall back to the documented default."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.processing_lease_duration_seconds == 300


def test_loads_configured_processing_lease_duration() -> None:
    """A valid configured lease duration should be parsed as an integer."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR: "600"},
        )
    )

    assert settings.processing_lease_duration_seconds == 600


def test_trims_processing_lease_duration() -> None:
    """Surrounding whitespace around a valid lease duration should be accepted."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR: "  600  "},
        )
    )

    assert settings.processing_lease_duration_seconds == 600


@pytest.mark.parametrize(
    "lease_duration",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
        "0",
        "-1",
        "-300",
        "300.0",
        "abc",
        "6a0",
    ],
)
def test_rejects_invalid_processing_lease_duration(
    lease_duration: str,
) -> None:
    """Invalid lease duration values must fail with a stable error message."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=("CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS must be a positive integer"),
    ):
        RuntimeSettings.from_environment(
            _valid_environment(
                **{PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR: lease_duration},
            )
        )


def test_missing_max_document_size_uses_default() -> None:
    """Missing max document size should fall back to the documented default."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.max_document_size_bytes == 65_536


def test_loads_configured_max_document_size() -> None:
    """A valid configured max document size should be parsed as an integer."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{MAX_DOCUMENT_SIZE_BYTES_ENV_VAR: "131072"},
        )
    )

    assert settings.max_document_size_bytes == 131_072


def test_trims_max_document_size() -> None:
    """Surrounding whitespace around a valid max document size should be accepted."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{MAX_DOCUMENT_SIZE_BYTES_ENV_VAR: "  131072  "},
        )
    )

    assert settings.max_document_size_bytes == 131_072


@pytest.mark.parametrize(
    "max_document_size",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
        "0",
        "-1",
        "-65536",
        "65536.0",
        "abc",
        "65a536",
        "true",
        "false",
    ],
)
def test_rejects_invalid_max_document_size(
    max_document_size: str,
) -> None:
    """Invalid max document size values must fail with a stable error message."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=("CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES must be a positive integer"),
    ):
        RuntimeSettings.from_environment(
            _valid_environment(
                **{MAX_DOCUMENT_SIZE_BYTES_ENV_VAR: max_document_size},
            )
        )


def test_missing_ai_provider_uses_default() -> None:
    """Missing AI provider should fall back to the documented mock default."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.ai_provider == DEFAULT_AI_PROVIDER


def test_normalizes_configured_mock_ai_provider() -> None:
    """An explicitly configured mock provider should be trimmed and lowercased."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{AI_PROVIDER_ENV_VAR: "  MoCk  "},
        )
    )

    assert settings.ai_provider == "mock"
    assert settings.bedrock_model_id is None


def test_normalizes_configured_bedrock_ai_provider() -> None:
    """An explicitly configured Bedrock provider should be trimmed and lowercased."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{
                AI_PROVIDER_ENV_VAR: "  BeDrOcK  ",
                BEDROCK_MODEL_ID_ENV_VAR: VALID_BEDROCK_MODEL_ID,
            },
        )
    )

    assert settings.ai_provider == "bedrock"
    assert settings.bedrock_model_id == VALID_BEDROCK_MODEL_ID


def test_provider_normalization_preserves_model_id_case_and_content() -> None:
    """Provider normalization should only trim surrounding model ID whitespace."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{
                AI_PROVIDER_ENV_VAR: "bedrock",
                BEDROCK_MODEL_ID_ENV_VAR: "  amazon.nova-micro-v1:0  ",
            },
        )
    )

    assert settings.bedrock_model_id == "amazon.nova-micro-v1:0"


@pytest.mark.parametrize(
    "provider",
    [
        "",
        " ",
        "\t",
        "\n",
        "unknown",
        "nova",
        "mock-provider",
    ],
)
def test_rejects_invalid_ai_provider(provider: str) -> None:
    """Unsupported AI provider values must fail with a stable error message."""
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        RuntimeSettings.from_environment(
            _valid_environment(
                **{AI_PROVIDER_ENV_VAR: provider},
            )
        )

    assert str(exc_info.value) == ("CLOUDDOC_AI_PROVIDER must be one of: bedrock, mock")


def test_mock_provider_allows_missing_bedrock_model_id() -> None:
    """Mock provider without a model ID should load with no model configured."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.ai_provider == "mock"
    assert settings.bedrock_model_id is None


def test_bedrock_provider_requires_model_id() -> None:
    """Bedrock provider without a model ID should fail startup."""
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        RuntimeSettings.from_environment(
            _valid_environment(
                **{AI_PROVIDER_ENV_VAR: "bedrock"},
            )
        )

    assert str(exc_info.value) == (
        "missing required environment variable: CLOUDDOC_BEDROCK_MODEL_ID"
    )


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
    ],
)
def test_rejects_blank_bedrock_model_id_for_mock_provider(model_id: str) -> None:
    """An explicitly blank model ID must fail even when the provider is mock."""
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        RuntimeSettings.from_environment(
            _valid_environment(
                **{
                    AI_PROVIDER_ENV_VAR: "mock",
                    BEDROCK_MODEL_ID_ENV_VAR: model_id,
                },
            )
        )

    assert str(exc_info.value) == "CLOUDDOC_BEDROCK_MODEL_ID must not be empty"


@pytest.mark.parametrize(
    "model_id",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
    ],
)
def test_rejects_blank_bedrock_model_id_for_bedrock_provider(model_id: str) -> None:
    """An explicitly blank model ID must fail when the provider is Bedrock."""
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        RuntimeSettings.from_environment(
            _valid_environment(
                **{
                    AI_PROVIDER_ENV_VAR: "bedrock",
                    BEDROCK_MODEL_ID_ENV_VAR: model_id,
                },
            )
        )

    assert str(exc_info.value) == "CLOUDDOC_BEDROCK_MODEL_ID must not be empty"


def test_trims_bedrock_model_id() -> None:
    """Surrounding whitespace should not become part of the model ID."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{
                AI_PROVIDER_ENV_VAR: "bedrock",
                BEDROCK_MODEL_ID_ENV_VAR: "  amazon.nova-micro-v1:0  ",
            },
        )
    )

    assert settings.bedrock_model_id == "amazon.nova-micro-v1:0"


def test_preserves_bedrock_model_id_internal_characters_and_case() -> None:
    """Model ID internal characters and case must be preserved."""
    model_id = "Amazon.Nova-Micro-V1:0-Custom.TEST"
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{
                AI_PROVIDER_ENV_VAR: "bedrock",
                BEDROCK_MODEL_ID_ENV_VAR: model_id,
            },
        )
    )

    assert settings.bedrock_model_id == model_id


def test_does_not_infer_default_bedrock_model_id() -> None:
    """The runtime must not hard-code or infer a default Bedrock model ID."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{AI_PROVIDER_ENV_VAR: "mock"},
        )
    )

    assert settings.bedrock_model_id is None


def test_missing_bedrock_max_output_tokens_uses_default() -> None:
    """Missing max output tokens should fall back to the documented default."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.bedrock_max_output_tokens == DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS
    assert settings.bedrock_max_output_tokens == 1_200


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1", 1),
        ("  1200  ", 1200),
        ("5000", 5000),
    ],
)
def test_loads_configured_bedrock_max_output_tokens(
    raw_value: str,
    expected: int,
) -> None:
    """Valid configured max output token values should parse as integers."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR: raw_value},
        )
    )

    assert settings.bedrock_max_output_tokens == expected


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        " ",
        "\t",
        "\n",
        "0",
        "-1",
        "5001",
        "1.0",
        "1200.5",
        "1e3",
        "+1",
        "abc",
        "true",
    ],
)
def test_rejects_invalid_bedrock_max_output_tokens(raw_value: str) -> None:
    """Invalid max output token values must fail with a stable error message."""
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        RuntimeSettings.from_environment(
            _valid_environment(
                **{BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR: raw_value},
            )
        )

    assert str(exc_info.value) == (
        "CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS must be an integer between 1 and 5000"
    )


def test_missing_bedrock_temperature_uses_default() -> None:
    """Missing temperature should fall back to the documented default."""
    settings = RuntimeSettings.from_environment(_valid_environment())

    assert settings.bedrock_temperature == DEFAULT_BEDROCK_TEMPERATURE
    assert settings.bedrock_temperature == 0.00001


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("0.00001", 0.00001),
        ("  0.25  ", 0.25),
        ("1", 1.0),
        ("1.0", 1.0),
    ],
)
def test_loads_configured_bedrock_temperature(
    raw_value: str,
    expected: float,
) -> None:
    """Valid configured temperature values should parse as floats."""
    settings = RuntimeSettings.from_environment(
        _valid_environment(
            **{BEDROCK_TEMPERATURE_ENV_VAR: raw_value},
        )
    )

    assert settings.bedrock_temperature == expected


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        " ",
        "\t",
        "\n",
        "0",
        "0.0",
        "-0.1",
        "1.00001",
        "2",
        "nan",
        "NaN",
        "inf",
        "+inf",
        "-inf",
        "Infinity",
        "-Infinity",
        "abc",
    ],
)
def test_rejects_invalid_bedrock_temperature(raw_value: str) -> None:
    """Invalid and non-finite temperatures must fail with a stable error message."""
    with pytest.raises(RuntimeConfigurationError) as exc_info:
        RuntimeSettings.from_environment(
            _valid_environment(
                **{BEDROCK_TEMPERATURE_ENV_VAR: raw_value},
            )
        )

    assert str(exc_info.value) == (
        "CLOUDDOC_BEDROCK_TEMPERATURE must be a finite number between 0.00001 and 1.0"
    )


def test_direct_construction_with_required_fields_receives_ai_defaults() -> None:
    """Direct construction with the original five fields keeps AI defaults."""
    settings = RuntimeSettings(
        jobs_table_name=VALID_JOBS_TABLE_NAME,
        documents_bucket_name=VALID_DOCUMENTS_BUCKET_NAME,
        upload_url_expiration_seconds=DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS,
        processing_lease_duration_seconds=DEFAULT_PROCESSING_LEASE_DURATION_SECONDS,
        max_document_size_bytes=DEFAULT_MAX_DOCUMENT_SIZE_BYTES,
    )

    assert settings.ai_provider == DEFAULT_AI_PROVIDER
    assert settings.bedrock_model_id is None
    assert settings.bedrock_max_output_tokens == DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS
    assert settings.bedrock_temperature == DEFAULT_BEDROCK_TEMPERATURE


def test_settings_are_immutable() -> None:
    """Runtime configuration should not change after startup."""
    settings = RuntimeSettings(
        jobs_table_name=VALID_JOBS_TABLE_NAME,
        documents_bucket_name=VALID_DOCUMENTS_BUCKET_NAME,
        upload_url_expiration_seconds=900,
        processing_lease_duration_seconds=300,
        max_document_size_bytes=65_536,
    )

    with pytest.raises(AttributeError):
        settings.jobs_table_name = "other-table"

    with pytest.raises(AttributeError):
        settings.ai_provider = "bedrock"
