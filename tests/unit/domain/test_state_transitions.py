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


def test_start_processing_rejects_naive_mutation_timestamp() -> None:
    """A claim update must use a timezone-aware timestamp."""
    job = make_job()

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must be timezone-aware",
    ):
        job.start_processing(
            make_attempt(),
            updated_at=datetime(2026, 7, 25, 12, 0),
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.attempts == 0
    assert job.active_attempt is None


def test_start_processing_rejects_non_utc_mutation_timestamp() -> None:
    """A claim update must be normalized to UTC."""
    from datetime import timezone

    job = make_job()
    brasilia_timezone = timezone(timedelta(hours=-3))
    updated_at = datetime(
        2026,
        7,
        25,
        9,
        0,
        1,
        tzinfo=brasilia_timezone,
    )

    with pytest.raises(
        InvalidDomainValueError,
        match="mutation timestamp must use UTC",
    ):
        job.start_processing(
            make_attempt(),
            updated_at=updated_at,
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.attempts == 0
    assert job.active_attempt is None


def test_failed_transition_does_not_mutate_job() -> None:
    """A rejected transition must leave all job state unchanged."""
    job = make_job()
    original_updated_at = job.updated_at

    with pytest.raises(InvalidStateTransitionError):
        job.mark_failed(
            "unsupported_content_type",
            finished_at=BASE_TIME + timedelta(seconds=1),
        )

    assert job.status is JobStatus.PENDING_UPLOAD
    assert job.attempts == 0
    assert job.active_attempt is None
    assert job.processing_result is None
    assert job.error_reason is None
    assert job.updated_at == original_updated_at


def test_failed_success_validation_does_not_complete_job() -> None:
    """Invalid success data must not partially mutate the job."""
    job = make_job()
    attempt = make_attempt()
    processing_at = BASE_TIME + timedelta(seconds=1)

    job.start_processing(
        attempt,
        updated_at=processing_at,
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
    assert job.active_attempt is attempt
    assert job.attempts == 1
    assert job.processing_result is None
    assert job.error_reason is None
    assert job.updated_at == processing_at


def test_failed_reason_validation_does_not_complete_job() -> None:
    """Invalid failure data must not partially mutate the job."""
    job = make_job()
    attempt = make_attempt()
    processing_at = BASE_TIME + timedelta(seconds=1)

    job.start_processing(
        attempt,
        updated_at=processing_at,
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
    assert job.active_attempt is attempt
    assert job.attempts == 1
    assert job.error_reason is None
    assert job.updated_at == processing_at


@pytest.mark.parametrize(
    "terminal_operation",
    [
        "mark_succeeded",
        "mark_failed",
        "mark_dead",
        "release_for_retry",
    ],
)
def test_terminal_job_rejects_all_further_lifecycle_operations(
    terminal_operation: str,
) -> None:
    """A succeeded job must reject every ordinary lifecycle mutation."""
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
        (InvalidStateTransitionError, TerminalJobMutationError),
    ):
        if terminal_operation == "mark_succeeded":
            job.mark_succeeded(
                {"document_type": "invoice"},
                finished_at=BASE_TIME + timedelta(seconds=3),
            )
        elif terminal_operation == "mark_failed":
            job.mark_failed(
                "unexpected_error",
                finished_at=BASE_TIME + timedelta(seconds=3),
            )
        elif terminal_operation == "mark_dead":
            job.mark_dead(
                "retry_exhausted",
                finished_at=BASE_TIME + timedelta(seconds=3),
            )
        else:
            job.release_for_retry(
                updated_at=BASE_TIME + timedelta(seconds=3),
            )

    assert job.status is JobStatus.SUCCEEDED
    assert job.processing_result == {"document_type": "contract"}
    assert job.active_attempt is None
    assert job.attempts == 1


def test_attempt_count_changes_only_after_valid_claim() -> None:
    """Rejected claims must not increment the attempt counter."""
    job = make_job()

    with pytest.raises(InvalidDomainValueError):
        job.start_processing(
            make_attempt(),
            updated_at=BASE_TIME - timedelta(seconds=1),
        )

    assert job.attempts == 0

    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    assert job.attempts == 1


def test_retry_release_preserves_completed_attempt_count() -> None:
    """Releasing a claim must not erase processing-attempt history."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    job.release_for_retry(
        updated_at=BASE_TIME + timedelta(seconds=2),
    )

    assert job.attempts == 1


def test_terminal_completion_preserves_attempt_count() -> None:
    """Completing a job must retain the number of acquired claims."""
    job = make_job()
    job.start_processing(
        make_attempt(),
        updated_at=BASE_TIME + timedelta(seconds=1),
    )

    job.mark_failed(
        "invalid_utf8",
        finished_at=BASE_TIME + timedelta(seconds=2),
    )

    assert job.status is JobStatus.FAILED
    assert job.attempts == 1
