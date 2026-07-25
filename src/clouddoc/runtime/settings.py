"""Runtime configuration loaded from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

JOBS_TABLE_NAME_ENV_VAR = "CLOUDDOC_JOBS_TABLE_NAME"


class RuntimeConfigurationError(Exception):
    """Raised when required runtime configuration is invalid."""


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Validated configuration required by the CloudDoc runtime."""

    jobs_table_name: str

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

        return cls(
            jobs_table_name=table_name,
        )
