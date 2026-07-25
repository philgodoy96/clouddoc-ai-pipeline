"""Concrete runtime clock implementation."""

from datetime import UTC, datetime


class SystemClock:
    """Provide the current timezone-aware UTC time."""

    def now(self) -> datetime:
        """Return the current UTC datetime."""
        return datetime.now(UTC)
