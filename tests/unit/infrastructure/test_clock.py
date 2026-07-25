"""Tests for the concrete runtime clock."""

from datetime import UTC, datetime, timedelta

from clouddoc.application import Clock
from clouddoc.infrastructure import SystemClock


def test_system_clock_satisfies_clock_protocol() -> None:
    """The runtime clock should implement the application port."""
    assert isinstance(SystemClock(), Clock)


def test_system_clock_returns_timezone_aware_utc_datetime() -> None:
    """The runtime clock should return a timezone-aware UTC value."""
    before = datetime.now(UTC)

    result = SystemClock().now()

    after = datetime.now(UTC)

    assert result.tzinfo is UTC
    assert before <= result <= after


def test_system_clock_returns_current_time() -> None:
    """The returned value should remain close to wall-clock time."""
    result = SystemClock().now()
    current_time = datetime.now(UTC)

    assert current_time - result < timedelta(seconds=1)
