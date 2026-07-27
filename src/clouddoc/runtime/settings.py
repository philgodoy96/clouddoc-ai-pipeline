"""Runtime configuration loaded from environment variables."""

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

JOBS_TABLE_NAME_ENV_VAR = "CLOUDDOC_JOBS_TABLE_NAME"
DOCUMENTS_BUCKET_NAME_ENV_VAR = "CLOUDDOC_DOCUMENTS_BUCKET_NAME"
UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR = "CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS"
DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS = 900
PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR = "CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS"
DEFAULT_PROCESSING_LEASE_DURATION_SECONDS = 300
MAX_DOCUMENT_SIZE_BYTES_ENV_VAR = "CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES"
DEFAULT_MAX_DOCUMENT_SIZE_BYTES = 65_536

AI_PROVIDER_ENV_VAR = "CLOUDDOC_AI_PROVIDER"
BEDROCK_MODEL_ID_ENV_VAR = "CLOUDDOC_BEDROCK_MODEL_ID"
BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR = "CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS"
BEDROCK_TEMPERATURE_ENV_VAR = "CLOUDDOC_BEDROCK_TEMPERATURE"

DEFAULT_AI_PROVIDER = "mock"
SUPPORTED_AI_PROVIDERS = frozenset({"mock", "bedrock"})

DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS = 1_200
MIN_BEDROCK_MAX_OUTPUT_TOKENS = 1
MAX_BEDROCK_MAX_OUTPUT_TOKENS = 5_000

DEFAULT_BEDROCK_TEMPERATURE = 0.00001
MIN_BEDROCK_TEMPERATURE = 0.00001
MAX_BEDROCK_TEMPERATURE = 1.0

AI_PROVIDER_INVALID_ERROR_MESSAGE = "CLOUDDOC_AI_PROVIDER must be one of: bedrock, mock"
BEDROCK_MODEL_ID_MISSING_ERROR_MESSAGE = (
    "missing required environment variable: CLOUDDOC_BEDROCK_MODEL_ID"
)
BEDROCK_MODEL_ID_EMPTY_ERROR_MESSAGE = "CLOUDDOC_BEDROCK_MODEL_ID must not be empty"
BEDROCK_MAX_OUTPUT_TOKENS_ERROR_MESSAGE = (
    "CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS must be an integer between 1 and 5000"
)
BEDROCK_TEMPERATURE_ERROR_MESSAGE = (
    "CLOUDDOC_BEDROCK_TEMPERATURE must be a finite number between 0.00001 and 1.0"
)


class RuntimeConfigurationError(Exception):
    """Raised when required runtime configuration is invalid."""


def _parse_positive_integer_setting(
    raw_value: str | None,
    environment_variable: str,
    default: int,
) -> int:
    """Parse an optional positive base-10 integer setting."""
    if raw_value is None:
        return default

    stripped = raw_value.strip()

    if not stripped.isdigit():
        raise RuntimeConfigurationError(
            f"{environment_variable} must be a positive integer"
        )

    value = int(stripped, 10)

    if value <= 0:
        raise RuntimeConfigurationError(
            f"{environment_variable} must be a positive integer"
        )

    return value


def _parse_bounded_base10_integer_setting(
    raw_value: str | None,
    *,
    default: int,
    min_value: int,
    max_value: int,
    error_message: str,
) -> int:
    """Parse an optional bounded base-10 integer setting."""
    if raw_value is None:
        return default

    stripped = raw_value.strip()

    if not stripped.isdigit():
        raise RuntimeConfigurationError(error_message)

    value = int(stripped, 10)

    if value < min_value or value > max_value:
        raise RuntimeConfigurationError(error_message)

    return value


def _parse_bounded_finite_float_setting(
    raw_value: str | None,
    *,
    default: float,
    min_value: float,
    max_value: float,
    error_message: str,
) -> float:
    """Parse an optional bounded finite float setting."""
    if raw_value is None:
        return default

    stripped = raw_value.strip()

    if not stripped:
        raise RuntimeConfigurationError(error_message)

    try:
        value = float(stripped)
    except ValueError as exc:
        raise RuntimeConfigurationError(error_message) from exc

    if not math.isfinite(value) or value < min_value or value > max_value:
        raise RuntimeConfigurationError(error_message)

    return value


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated configuration required by the CloudDoc runtime."""

    jobs_table_name: str
    documents_bucket_name: str
    upload_url_expiration_seconds: int
    processing_lease_duration_seconds: int
    max_document_size_bytes: int
    ai_provider: str = DEFAULT_AI_PROVIDER
    bedrock_model_id: str | None = None
    bedrock_max_output_tokens: int = DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS
    bedrock_temperature: float = DEFAULT_BEDROCK_TEMPERATURE

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "RuntimeSettings":
        """Load and validate runtime settings from an environment mapping."""
        source = environment if environment is not None else os.environ

        raw_table_name = source.get(JOBS_TABLE_NAME_ENV_VAR)

        if raw_table_name is None:
            raise RuntimeConfigurationError(
                f"missing required environment variable: {JOBS_TABLE_NAME_ENV_VAR}"
            )

        table_name = raw_table_name.strip()

        if not table_name:
            raise RuntimeConfigurationError(
                f"{JOBS_TABLE_NAME_ENV_VAR} must not be empty"
            )

        raw_bucket_name = source.get(DOCUMENTS_BUCKET_NAME_ENV_VAR)

        if raw_bucket_name is None:
            raise RuntimeConfigurationError(
                "missing required environment variable: "
                f"{DOCUMENTS_BUCKET_NAME_ENV_VAR}"
            )

        bucket_name = raw_bucket_name.strip()

        if not bucket_name:
            raise RuntimeConfigurationError(
                f"{DOCUMENTS_BUCKET_NAME_ENV_VAR} must not be empty"
            )

        upload_url_expiration_seconds = _parse_positive_integer_setting(
            source.get(UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR),
            UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR,
            DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS,
        )
        processing_lease_duration_seconds = _parse_positive_integer_setting(
            source.get(PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR),
            PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR,
            DEFAULT_PROCESSING_LEASE_DURATION_SECONDS,
        )
        max_document_size_bytes = _parse_positive_integer_setting(
            source.get(MAX_DOCUMENT_SIZE_BYTES_ENV_VAR),
            MAX_DOCUMENT_SIZE_BYTES_ENV_VAR,
            DEFAULT_MAX_DOCUMENT_SIZE_BYTES,
        )

        raw_ai_provider = source.get(AI_PROVIDER_ENV_VAR)
        if raw_ai_provider is None:
            ai_provider = DEFAULT_AI_PROVIDER
        else:
            normalized_ai_provider = raw_ai_provider.strip().lower()
            if normalized_ai_provider not in SUPPORTED_AI_PROVIDERS:
                raise RuntimeConfigurationError(AI_PROVIDER_INVALID_ERROR_MESSAGE)
            ai_provider = normalized_ai_provider

        raw_bedrock_model_id = source.get(BEDROCK_MODEL_ID_ENV_VAR)
        if raw_bedrock_model_id is None:
            if ai_provider == "bedrock":
                raise RuntimeConfigurationError(BEDROCK_MODEL_ID_MISSING_ERROR_MESSAGE)
            bedrock_model_id = None
        else:
            stripped_model_id = raw_bedrock_model_id.strip()
            if not stripped_model_id:
                raise RuntimeConfigurationError(BEDROCK_MODEL_ID_EMPTY_ERROR_MESSAGE)
            bedrock_model_id = stripped_model_id

        bedrock_max_output_tokens = _parse_bounded_base10_integer_setting(
            source.get(BEDROCK_MAX_OUTPUT_TOKENS_ENV_VAR),
            default=DEFAULT_BEDROCK_MAX_OUTPUT_TOKENS,
            min_value=MIN_BEDROCK_MAX_OUTPUT_TOKENS,
            max_value=MAX_BEDROCK_MAX_OUTPUT_TOKENS,
            error_message=BEDROCK_MAX_OUTPUT_TOKENS_ERROR_MESSAGE,
        )

        bedrock_temperature = _parse_bounded_finite_float_setting(
            source.get(BEDROCK_TEMPERATURE_ENV_VAR),
            default=DEFAULT_BEDROCK_TEMPERATURE,
            min_value=MIN_BEDROCK_TEMPERATURE,
            max_value=MAX_BEDROCK_TEMPERATURE,
            error_message=BEDROCK_TEMPERATURE_ERROR_MESSAGE,
        )

        return cls(
            jobs_table_name=table_name,
            documents_bucket_name=bucket_name,
            upload_url_expiration_seconds=upload_url_expiration_seconds,
            processing_lease_duration_seconds=processing_lease_duration_seconds,
            max_document_size_bytes=max_document_size_bytes,
            ai_provider=ai_provider,
            bedrock_model_id=bedrock_model_id,
            bedrock_max_output_tokens=bedrock_max_output_tokens,
            bedrock_temperature=bedrock_temperature,
        )
