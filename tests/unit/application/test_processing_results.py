"""Tests for processing-start continuation results."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.application import (
    ProcessingStartOutcome,
    ProcessingStartResult,
)
from clouddoc.domain import ProcessingAttempt

STARTED_AT = datetime(
    2026,
    7,
    26,
    12,
    0,
    tzinfo=UTC,
)
LEASE_EXPIRES_AT = STARTED_AT + timedelta(minutes=5)


def make_attempt() -> ProcessingAttempt:
    """Create one deterministic processing attempt."""
    return ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=STARTED_AT,
        lease_expires_at=LEASE_EXPIRES_AT,
    )


def test_claim_acquired_factory_returns_owned_attempt() -> None:
    """A successful claim should authorize continuation."""
    attempt = make_attempt()

    result = ProcessingStartResult.claim_acquired(
        attempt=attempt,
    )

    assert result.outcome is ProcessingStartOutcome.CLAIM_ACQUIRED
    assert result.attempt is attempt


def test_effect_already_applied_factory_omits_attempt() -> None:
    """An already-applied effect must not authorize continuation."""
    result = ProcessingStartResult.effect_already_applied()

    assert result.outcome is ProcessingStartOutcome.EFFECT_ALREADY_APPLIED
    assert result.attempt is None


def test_claim_acquired_requires_attempt() -> None:
    """Continuation cannot be authorized without ownership."""
    with pytest.raises(
        ValueError,
        match="claim_acquired outcome requires an attempt",
    ):
        ProcessingStartResult(
            outcome=ProcessingStartOutcome.CLAIM_ACQUIRED,
            attempt=None,
        )


def test_effect_already_applied_rejects_attempt() -> None:
    """Another worker's attempt must not authorize continuation."""
    with pytest.raises(
        ValueError,
        match=("effect_already_applied outcome must not include an attempt"),
    ):
        ProcessingStartResult(
            outcome=(ProcessingStartOutcome.EFFECT_ALREADY_APPLIED),
            attempt=make_attempt(),
        )


def test_result_is_immutable() -> None:
    """Continuation decisions must not change after creation."""
    result = ProcessingStartResult.claim_acquired(
        attempt=make_attempt(),
    )

    with pytest.raises(FrozenInstanceError):
        result.attempt = None


def test_outcome_values_are_stable_strings() -> None:
    """Outcome values should remain suitable for logs and tests."""
    assert ProcessingStartOutcome.CLAIM_ACQUIRED.value == "claim_acquired"
    assert (
        ProcessingStartOutcome.EFFECT_ALREADY_APPLIED.value == "effect_already_applied"
    )


@pytest.mark.parametrize(
    "result",
    [
        ProcessingStartResult.claim_acquired(
            attempt=make_attempt(),
        ),
        ProcessingStartResult.effect_already_applied(),
    ],
)
def test_result_preserves_declared_outcome(
    result: ProcessingStartResult,
) -> None:
    """Every valid result should preserve one explicit decision."""
    assert result.outcome in {
        ProcessingStartOutcome.CLAIM_ACQUIRED,
        ProcessingStartOutcome.EFFECT_ALREADY_APPLIED,
    }
