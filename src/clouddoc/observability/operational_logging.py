"""Structured operational logging contracts and implementations."""

from __future__ import annotations

import logging
import math
from typing import Protocol, runtime_checkable

DEFAULT_OPERATIONAL_SERVICE = "clouddoc"

type OperationalFieldValue = str | int | float | bool | None

_ALLOWED_OPERATIONAL_FIELD_NAMES = frozenset(
    {
        "batch_size",
        "correlation_id",
        "duration_ms",
        "error_code",
        "exception_type",
        "failed_record_count",
        "failure_reason",
        "input_tokens",
        "job_id",
        "model_id",
        "operation",
        "outcome",
        "output_tokens",
        "processed_record_count",
        "processing_attempt_id",
        "provider_error_code",
        "provider_latency_ms",
        "provider_name",
        "provider_request_id",
        "request_id",
        "retryable",
        "sqs_message_id",
        "status_code",
        "stop_reason",
        "total_tokens",
    }
)


@runtime_checkable
class OperationalLogger(Protocol):
    """Emit safe, structured operational events."""

    def info(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Emit an informational operational event."""
        ...

    def warning(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Emit a warning operational event."""
        ...

    def error(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Emit an error operational event."""
        ...


class StandardOperationalLogger:
    """Emit flat structured events through the Python logging library."""

    def __init__(
        self,
        *,
        component: str,
        service: str = DEFAULT_OPERATIONAL_SERVICE,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize a component-scoped operational logger."""
        self._component = _require_non_empty_label(
            component,
            field_name="component",
        )
        self._service = _require_non_empty_label(
            service,
            field_name="service",
        )
        self._logger = (
            logger
            if logger is not None
            else logging.getLogger(f"{self._service}.{self._component}")
        )

    def info(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Emit an informational operational event."""
        self._emit(
            level=logging.INFO,
            event_name=event_name,
            fields=fields,
        )

    def warning(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Emit a warning operational event."""
        self._emit(
            level=logging.WARNING,
            event_name=event_name,
            fields=fields,
        )

    def error(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Emit an error operational event."""
        self._emit(
            level=logging.ERROR,
            event_name=event_name,
            fields=fields,
        )

    def _emit(
        self,
        *,
        level: int,
        event_name: str,
        fields: dict[str, OperationalFieldValue],
    ) -> None:
        """Emit one event without allowing logging failures to affect work."""
        normalized_event_name = _normalize_event_name(event_name)
        if normalized_event_name is None or not self._logger.isEnabledFor(level):
            return

        safe_fields, dropped_field_count = _select_safe_fields(fields)
        extra: dict[str, object] = {
            "component": self._component,
            "event_name": normalized_event_name,
            "service": self._service,
            **safe_fields,
        }
        if dropped_field_count:
            extra["dropped_field_count"] = dropped_field_count

        try:
            self._logger.log(
                level,
                normalized_event_name,
                extra=extra,
            )
        except Exception:
            # Operational telemetry must never change a business outcome.
            return


class NullOperationalLogger:
    """Discard operational events without side effects."""

    def info(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Discard an informational event."""

    def warning(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Discard a warning event."""

    def error(
        self,
        event_name: str,
        **fields: OperationalFieldValue,
    ) -> None:
        """Discard an error event."""


def _require_non_empty_label(
    value: str,
    *,
    field_name: str,
) -> str:
    """Normalize a required logger identity label."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")

    return value.strip()


def _normalize_event_name(event_name: str) -> str | None:
    """Normalize a valid event name or reject it without raising."""
    if not isinstance(event_name, str):
        return None

    normalized_event_name = event_name.strip()
    return normalized_event_name or None


def _select_safe_fields(
    fields: dict[str, OperationalFieldValue],
) -> tuple[dict[str, OperationalFieldValue], int]:
    """Retain only approved flat fields with JSON-safe scalar values."""
    safe_fields: dict[str, OperationalFieldValue] = {}
    dropped_field_count = 0

    for field_name, value in fields.items():
        if (
            field_name not in _ALLOWED_OPERATIONAL_FIELD_NAMES
            or not _is_safe_field_value(value)
        ):
            dropped_field_count += 1
            continue

        safe_fields[field_name] = value

    return safe_fields, dropped_field_count


def _is_safe_field_value(value: object) -> bool:
    """Return whether a value is a flat JSON-safe operational scalar."""
    if value is None or isinstance(value, (str, bool, int)):
        return True

    return isinstance(value, float) and math.isfinite(value)
