"""Runtime configuration loaded from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

JOBS_TABLE_NAME_ENV_VAR = "CLOUDDOC_JOBS_TABLE_NAME"
DOCUMENTS_BUCKET_NAME_ENV_VAR = "CLOUDDOC_DOCUMENTS_BUCKET_NAME"
UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR = "CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS"
DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS = 900
PROCESSING_LEASE_DURATION_SECONDS_ENV_VAR = "CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS"
DEFAULT_PROCESSING_LEASE_DURATION_SECONDS = 300


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


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated configuration required by the CloudDoc runtime."""

    jobs_table_name: str
    documents_bucket_name: str
    upload_url_expiration_seconds: int
    processing_lease_duration_seconds: int

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

        return cls(
            jobs_table_name=table_name,
            documents_bucket_name=bucket_name,
            upload_url_expiration_seconds=upload_url_expiration_seconds,
            processing_lease_duration_seconds=processing_lease_duration_seconds,
        )
