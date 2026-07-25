"""Processing attempt and lease representation."""

from dataclasses import dataclass
from datetime import UTC, datetime

from clouddoc.domain.errors import InvalidProcessingAttemptError


@dataclass(frozen=True, slots=True)
class ProcessingAttempt:
    """A bounded claim acquired by one document-processing worker."""

    attempt_id: str
    started_at: datetime
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        """Validate processing attempt invariants."""
        if not self.attempt_id.strip():
            raise InvalidProcessingAttemptError("attempt_id must not be empty")

        _validate_utc_datetime(self.started_at, field_name="started_at")
        _validate_utc_datetime(
            self.lease_expires_at,
            field_name="lease_expires_at",
        )

        if self.lease_expires_at <= self.started_at:
            raise InvalidProcessingAttemptError(
                "lease_expires_at must be later than started_at"
            )

    def is_lease_expired(self, at: datetime) -> bool:
        """Return whether the processing lease has expired at a given time."""
        _validate_utc_datetime(at, field_name="at")
        return at >= self.lease_expires_at


def _validate_utc_datetime(value: datetime, *, field_name: str) -> None:
    """Require a timezone-aware datetime normalized to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidProcessingAttemptError(f"{field_name} must be timezone-aware")

    if value.utcoffset() != UTC.utcoffset(value):
        raise InvalidProcessingAttemptError(f"{field_name} must use UTC")
