"""Tests for document job lifecycle transitions."""

from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.errors import (
    InvalidDomainValueError,
    InvalidStateTransitionError,
    TerminalJobMutationError,
)
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt
from clouddoc.domain.state_transitions import is_transition_allowed

BASE_TIME = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def make_job() -> DocumentJob:
    """Create a valid pending-upload job for transition tests."""
    return DocumentJob(
        job_id="job-001",
        correlation_context=CorrelationContext(
            request_id="request-001",
            correlation_id="correlation-001",
        ),
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def make_attempt(
    *,
    attempt_id: str = "attempt-001",
    started_at: datetime = BASE_TIME,
) -> ProcessingAttempt:
    """Create a valid processing attempt."""
    return ProcessingAttempt(
        attempt_id=attempt_id,
        started_at=started_at,
        lease_expires_at=started_at + timedelta(minutes=5),
    )


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        (JobStatus.PENDING_UPLOAD, JobStatus.PROCESSING),
        (JobStatus.PROCESSING, JobStatus.PENDING_UPLOAD),
        (JobStatus.PROCESSING, JobStatus.SUCCEEDED),
        (JobStatus.PROCESSING, JobStatus.FAILED),
        (JobStatus.PROCESSING, JobStatus.DEAD),
    ],
)
def test_allowed_state_transitions(
    current_status: JobStatus,
    target_status: JobStatus,
) -> None:
    """The transition table should expose approved lifecycle moves."""
    assert is_transition_allowed(current_status, target_status)


@pytest.mark.parametrize(
    ("current_status", "target_status"),
    [
        (JobStatus.PENDING_UPLOAD, JobStatus.SUCCEEDED),
        (JobStatus.PENDING_UPLOAD, JobStatus.FAILED),
        (JobStatus.PENDING_UPLOAD, JobStatus.DEAD),
        (JobStatus.SUCCEEDED, JobStatus.PROCESSING),
        (JobStatus.FAILED, JobStatus.PROCESSING),
        (JobStatus.DEAD, JobStatus.PROCESSING),
    ],
)
def test_disallowed_state_transitions(
    current_status: JobStatus,
    target_status: JobStatus,
) -> None:
    """The transition table should reject unsupported lifecycle moves."""
    assert not is_transition_allowed(current_status, target_status)


def test_start_processing_acquires_attempt() -> None:
    """A pending job should acquire an active processing attempt."""
    job = make_job()
    attempt = make_attempt()

    job.start_processing(
        attempt,
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    assert job.status is JobStatus.PROCESSING
    assert job.active_attempt is attempt
    assert job.attempts == 1
    assert job.updated_at == BASE_TIME + timedelta(seconds=1)


def test_retry_release_returns_job_to_pending_upload() -> None:
    """A retryable failure should release the active processing claim."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    job.release_for_retry(
        updated_at=BASE_TIME + timedelta(seconds=2),
    )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.active_attempt is None
    assert job.attempts == 1
    assert job.processing_result is None
    assert job.error_reason is None


def test_second_processing_attempt_increments_attempt_count() -> None:
    """A later valid claim should increment the attempt counter."""
    job = make_job()
    job.start_processing(
        make_attempt(attempt_id="attempt-001"),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    job.release_for_retry(
        updated_at=BASE_TIME + timedelta(seconds=2),
    )

    second_attempt = make_attempt(
        attempt_id="attempt-002",
        started_at=BASE_TIME + timedelta(seconds=3),
    )
    job.start_processing(
        second_attempt,
        updated_at=BASE_TIME + timedelta(seconds=3),
    )

    assert job.status is JobStatus.PROCESSING
    assert job.active_attempt is second_attempt
    assert job.attempts == 2


def test_mark_succeeded_completes_active_attempt() -> None:
    """A processing job should accept a successful result."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    result = {"document_type": "contract"}

    job.mark_succeeded(
        result,
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    assert job.status is JobStatus.SUCCEEDED
    assert job.processing_result == result
    assert job.error_reason is None
    assert job.active_attempt is None


def test_mark_failed_records_terminal_reason() -> None:
    """A processing job should retain a normalized failure reason."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    job.mark_failed(
        "  unsupported_content_type  ",
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    assert job.status is JobStatus.FAILED
    assert job.processing_result is None
    assert job.error_reason == "unsupported_content_type"
    assert job.active_attempt is None


def test_mark_dead_records_retry_exhaustion() -> None:
    """A processing job should support retry-exhausted completion."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    job.mark_dead(
        "retry_exhausted",
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    assert job.status is JobStatus.DEAD
    assert job.error_reason == "retry_exhausted"
    assert job.active_attempt is None


def test_completion_requires_active_attempt() -> None:
    """A job cannot complete without first acquiring processing work."""
    job = make_job()

    with pytest.raises(
        InvalidStateTransitionError,
        match="job must have an active processing attempt",
    ):
        job.mark_succeeded(
            {"document_type": "contract"},
            finished_at=BASE_TIME + timedelta(seconds=1),
        )


def test_retry_release_requires_active_attempt() -> None:
    """A job cannot release a claim that does not exist."""
    job = make_job()

    with pytest.raises(
        InvalidStateTransitionError,
        match="job must have an active processing attempt",
    ):
        job.release_for_retry(
            updated_at=BASE_TIME + timedelta(seconds=1),
        )


def test_success_rejects_none_result() -> None:
    """A successful job must contain an accepted result."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="processing result must not be None",
    ):
        job.mark_succeeded(
            None,
            finished_at=BASE_TIME + timedelta(seconds=2),
        )

    assert job.status is JobStatus.PROCESSING
    assert job.active_attempt is not None


def test_terminal_failure_rejects_empty_reason() -> None:
    """A terminal failure must contain a normalized error reason."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="error reason must not be empty",
    ):
        job.mark_failed(
            " ",
            finished_at=BASE_TIME + timedelta(seconds=2),
        )

    assert job.status is JobStatus.PROCESSING
    assert job.active_attempt is not None


def test_terminal_job_rejects_further_processing() -> None:
    """Ordinary processing must not reactivate a terminal job."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )
    job.mark_succeeded(
        {"document_type": "contract"},
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    with pytest.raises(
        TerminalJobMutationError,
        match="terminal job cannot transition",
    ):
        job.start_processing(
            make_attempt(
                attempt_id="attempt-002",
                started_at=BASE_TIME + timedelta(seconds=3),
            ),
            updated_at=BASE_TIME + timedelta(seconds=3),
        )

    assert job.status is JobStatus.SUCCEEDED
    assert job.attempts == 1


def test_transition_rejects_timestamp_before_last_update() -> None:
    """Lifecycle timestamps must never move backward."""
    job = make_job()

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must not be earlier than updated_at",
    ):
        job.start_processing(
            make_attempt(),
            updated_at=BASE_TIME - timedelta(seconds=1),
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.attempts == 0
    assert job.active_attempt is None


def test_completion_cannot_precede_processing_update() -> None:
    """A completion timestamp cannot predate the claim update."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=2),
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must not be earlier than updated_at",
    ):
        job.mark_succeeded(
            {"document_type": "contract"},
            finished_at=BASE_TIME + timedelta(seconds=1),
        )

    assert job.status is JobStatus.PROCESSING
    assert job.active_attempt is not None
