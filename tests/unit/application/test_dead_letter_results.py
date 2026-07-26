"""Tests for dead-letter reconciliation results."""

from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from clouddoc.application import (
    DeadLetterReconciliationOutcome,
    DeadLetterReconciliationResult,
)

JOB_ID = "job-001"


def test_dead_recorded_factory_preserves_job_identity() -> None:
    """A persisted dead transition should expose its job identity."""
    result = DeadLetterReconciliationResult.dead_recorded(
        job_id=JOB_ID,
    )

    assert result.outcome is DeadLetterReconciliationOutcome.DEAD_RECORDED
    assert result.job_id == JOB_ID


def test_effect_already_applied_factory_preserves_job_identity() -> None:
    """An idempotent terminal result should expose its job identity."""
    result = DeadLetterReconciliationResult.effect_already_applied(
        job_id=JOB_ID,
    )

    assert result.outcome is (DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED)
    assert result.job_id == JOB_ID


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        " ",
        "   ",
        "\t",
        "\n",
    ],
)
def test_result_rejects_blank_job_id(
    job_id: str,
) -> None:
    """A reconciliation result requires stable job identity."""
    with pytest.raises(
        ValueError,
        match="job_id must not be blank",
    ):
        DeadLetterReconciliationResult.dead_recorded(
            job_id=job_id,
        )


def test_result_preserves_job_id_without_mutation() -> None:
    """Validation should not alter the supplied job identifier."""
    job_id = "  job-001  "

    result = DeadLetterReconciliationResult.dead_recorded(
        job_id=job_id,
    )

    assert result.job_id == job_id


def test_result_rejects_unsupported_outcome() -> None:
    """Raw strings must not bypass the reconciliation enum."""
    unsupported_outcome = cast(
        DeadLetterReconciliationOutcome,
        "unsupported",
    )

    with pytest.raises(
        ValueError,
        match=("unsupported dead-letter reconciliation outcome"),
    ):
        DeadLetterReconciliationResult(
            outcome=unsupported_outcome,
            job_id=JOB_ID,
        )


def test_result_is_immutable() -> None:
    """A reconciliation decision must not change after creation."""
    result = DeadLetterReconciliationResult.dead_recorded(
        job_id=JOB_ID,
    )

    with pytest.raises(FrozenInstanceError):
        result.job_id = "job-002"


def test_outcome_values_are_stable_strings() -> None:
    """Outcome values should remain suitable for logs and metrics."""
    assert DeadLetterReconciliationOutcome.DEAD_RECORDED.value == "dead_recorded"
    assert (
        DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED.value
        == "effect_already_applied"
    )


@pytest.mark.parametrize(
    "result",
    [
        DeadLetterReconciliationResult.dead_recorded(
            job_id=JOB_ID,
        ),
        DeadLetterReconciliationResult.effect_already_applied(
            job_id=JOB_ID,
        ),
    ],
)
def test_result_preserves_one_explicit_outcome(
    result: DeadLetterReconciliationResult,
) -> None:
    """Every valid result should expose one reconciliation decision."""
    assert result.outcome in {
        DeadLetterReconciliationOutcome.DEAD_RECORDED,
        DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED,
    }
