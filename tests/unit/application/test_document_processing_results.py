"""Tests for document-processing workflow results."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from clouddoc.application import (
    DocumentProcessingOutcome,
    DocumentProcessingResult,
)
from clouddoc.domain import ProcessingAttempt
from clouddoc.schemas import (
    AIExtractionResult,
    DocumentType,
)

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
    """Create one deterministic owned processing attempt."""
    return ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=STARTED_AT,
        lease_expires_at=LEASE_EXPIRES_AT,
    )


def make_extraction_result() -> AIExtractionResult:
    """Create one deterministic validated AI extraction."""
    return AIExtractionResult(
        document_type=DocumentType.CONTRACT,
        summary="Service contract between two companies.",
        key_fields={
            "customer_name": "Example Company",
            "contract_number": "CONTRACT-001",
        },
        confidence=0.91,
        requires_human_review=False,
    )


def test_processed_factory_preserves_owned_workflow_result() -> None:
    """A completed invocation should retain ownership and output."""
    attempt = make_attempt()
    extraction_result = make_extraction_result()

    result = DocumentProcessingResult.processed(
        attempt=attempt,
        extraction_result=extraction_result,
    )

    assert result.outcome is DocumentProcessingOutcome.PROCESSED
    assert result.attempt is attempt
    assert result.extraction_result is extraction_result


def test_effect_already_applied_factory_omits_workflow_effects() -> None:
    """An applied duplicate must not expose owned workflow effects."""
    result = DocumentProcessingResult.effect_already_applied()

    assert result.outcome is DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED
    assert result.attempt is None
    assert result.extraction_result is None


def test_processed_outcome_requires_attempt() -> None:
    """A processed result requires current-worker ownership."""
    with pytest.raises(
        ValueError,
        match="processed outcome requires an attempt",
    ):
        DocumentProcessingResult(
            outcome=DocumentProcessingOutcome.PROCESSED,
            attempt=None,
            extraction_result=make_extraction_result(),
        )


def test_processed_outcome_requires_extraction_result() -> None:
    """A processed result requires validated provider output."""
    with pytest.raises(
        ValueError,
        match=("processed outcome requires an extraction result"),
    ):
        DocumentProcessingResult(
            outcome=DocumentProcessingOutcome.PROCESSED,
            attempt=make_attempt(),
            extraction_result=None,
        )


def test_effect_already_applied_rejects_attempt() -> None:
    """Another worker's attempt cannot authorize continuation."""
    with pytest.raises(
        ValueError,
        match=("effect_already_applied outcome must not include an attempt"),
    ):
        DocumentProcessingResult(
            outcome=(DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED),
            attempt=make_attempt(),
            extraction_result=None,
        )


def test_effect_already_applied_rejects_extraction_result() -> None:
    """An applied duplicate must not expose an AI extraction."""
    with pytest.raises(
        ValueError,
        match=("effect_already_applied outcome must not include an extraction result"),
    ):
        DocumentProcessingResult(
            outcome=(DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED),
            attempt=None,
            extraction_result=make_extraction_result(),
        )


def test_result_is_immutable() -> None:
    """Workflow decisions must not change after creation."""
    result = DocumentProcessingResult.processed(
        attempt=make_attempt(),
        extraction_result=make_extraction_result(),
    )

    with pytest.raises(FrozenInstanceError):
        result.attempt = None


def test_outcome_values_are_stable_strings() -> None:
    """Outcome values should remain suitable for logs and metrics."""
    assert DocumentProcessingOutcome.PROCESSED.value == "processed"
    assert (
        DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED.value
        == "effect_already_applied"
    )


@pytest.mark.parametrize(
    "result",
    [
        DocumentProcessingResult.processed(
            attempt=make_attempt(),
            extraction_result=make_extraction_result(),
        ),
        DocumentProcessingResult.effect_already_applied(),
    ],
)
def test_result_preserves_one_explicit_outcome(
    result: DocumentProcessingResult,
) -> None:
    """Every valid result should expose one workflow decision."""
    assert result.outcome in {
        DocumentProcessingOutcome.PROCESSED,
        DocumentProcessingOutcome.EFFECT_ALREADY_APPLIED,
    }
