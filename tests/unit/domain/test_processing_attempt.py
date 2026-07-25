"""Tests for processing attempt invariants."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.domain.errors import InvalidProcessingAttemptError
from clouddoc.domain.processing_attempt import ProcessingAttempt


def test_processing_attempt_accepts_valid_utc_lease() -> None:
    """A lease ending after its start should be accepted."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )

    assert attempt.attempt_id == "attempt-001"


def test_processing_attempt_rejects_empty_attempt_id() -> None:
    """A processing attempt must have a non-empty identifier."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="attempt_id must not be empty",
    ):
        ProcessingAttempt(
            attempt_id=" ",
            started_at=started_at,
            lease_expires_at=started_at + timedelta(minutes=5),
        )


@pytest.mark.parametrize(
    "lease_offset",
    [
        timedelta(0),
        timedelta(seconds=-1),
    ],
)
def test_processing_attempt_rejects_non_future_lease(
    lease_offset: timedelta,
) -> None:
    """A lease must expire strictly after the attempt begins."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="lease_expires_at must be later than started_at",
    ):
        ProcessingAttempt(
            attempt_id="attempt-001",
            started_at=started_at,
            lease_expires_at=started_at + lease_offset,
        )


def test_processing_attempt_rejects_naive_datetime() -> None:
    """Processing timestamps must be timezone-aware."""
    started_at = datetime(2026, 7, 25, 12, 0)

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="started_at must be timezone-aware",
    ):
        ProcessingAttempt(
            attempt_id="attempt-001",
            started_at=started_at,
            lease_expires_at=started_at + timedelta(minutes=5),
        )


def test_processing_attempt_rejects_non_utc_datetime() -> None:
    """Processing timestamps must be normalized to UTC."""
    from datetime import timezone

    brasilia_timezone = timezone(timedelta(hours=-3))
    started_at = datetime(
        2026,
        7,
        25,
        9,
        0,
        tzinfo=brasilia_timezone,
    )

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="started_at must use UTC",
    ):
        ProcessingAttempt(
            attempt_id="attempt-001",
            started_at=started_at,
            lease_expires_at=started_at + timedelta(minutes=5),
        )


def test_lease_is_not_expired_before_expiration() -> None:
    """A lease remains active before its expiration timestamp."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )

    assert not attempt.is_lease_expired(started_at + timedelta(minutes=4, seconds=59))


def test_lease_is_expired_at_expiration_boundary() -> None:
    """A lease is expired exactly at its expiration timestamp."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    lease_expires_at = started_at + timedelta(minutes=5)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=lease_expires_at,
    )

    assert attempt.is_lease_expired(lease_expires_at)


def test_processing_attempt_rejects_naive_expiration() -> None:
    """The lease expiration timestamp must be timezone-aware."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    lease_expires_at = datetime(2026, 7, 25, 12, 5)

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="lease_expires_at must be timezone-aware",
    ):
        ProcessingAttempt(
            attempt_id="attempt-001",
            started_at=started_at,
            lease_expires_at=lease_expires_at,
        )


def test_processing_attempt_rejects_non_utc_expiration() -> None:
    """The lease expiration timestamp must use UTC."""
    from datetime import timezone

    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    brasilia_timezone = timezone(timedelta(hours=-3))
    lease_expires_at = datetime(
        2026,
        7,
        25,
        9,
        5,
        tzinfo=brasilia_timezone,
    )

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="lease_expires_at must use UTC",
    ):
        ProcessingAttempt(
            attempt_id="attempt-001",
            started_at=started_at,
            lease_expires_at=lease_expires_at,
        )


def test_is_lease_expired_rejects_naive_comparison_time() -> None:
    """Lease checks must not compare against an ambiguous timestamp."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="at must be timezone-aware",
    ):
        attempt.is_lease_expired(datetime(2026, 7, 25, 12, 5))


def test_is_lease_expired_rejects_non_utc_comparison_time() -> None:
    """Lease checks must compare timestamps normalized to UTC."""
    from datetime import timezone

    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )
    brasilia_timezone = timezone(timedelta(hours=-3))
    comparison_time = datetime(
        2026,
        7,
        25,
        9,
        5,
        tzinfo=brasilia_timezone,
    )

    with pytest.raises(
        InvalidProcessingAttemptError,
        match="at must use UTC",
    ):
        attempt.is_lease_expired(comparison_time)


def test_lease_is_expired_after_expiration_boundary() -> None:
    """A lease remains expired after its exact expiration timestamp."""
    started_at = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
    attempt = ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )

    assert attempt.is_lease_expired(started_at + timedelta(minutes=5, seconds=1))
