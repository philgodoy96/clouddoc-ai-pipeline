"""Tests for the concrete runtime job identifier generator."""

import re

from clouddoc.application import JobIdGenerator, ProcessingAttemptIdGenerator
from clouddoc.infrastructure import (
    UUIDJobIdGenerator,
    UUIDProcessingAttemptIdGenerator,
)

JOB_ID_PATTERN = re.compile(r"^job_[0-9a-f]{32}$")
ATTEMPT_ID_PATTERN = re.compile(r"^attempt_[0-9a-f]{32}$")


def test_uuid_generator_satisfies_job_id_port() -> None:
    """The runtime generator should implement the application port."""
    assert isinstance(
        UUIDJobIdGenerator(),
        JobIdGenerator,
    )


def test_uuid_generator_uses_approved_format() -> None:
    """Generated identifiers should use the approved job prefix."""
    job_id = UUIDJobIdGenerator().generate()

    assert JOB_ID_PATTERN.fullmatch(job_id)


def test_uuid_generator_returns_unique_identifiers() -> None:
    """Sequential generations should not reuse identifiers."""
    generator = UUIDJobIdGenerator()

    generated_ids = {generator.generate() for _ in range(100)}

    assert len(generated_ids) == 100


def test_uuid_attempt_generator_satisfies_processing_attempt_id_port() -> None:
    """The attempt generator should implement the application port."""
    assert isinstance(
        UUIDProcessingAttemptIdGenerator(),
        ProcessingAttemptIdGenerator,
    )


def test_uuid_attempt_generator_uses_approved_format() -> None:
    """Generated identifiers should use the approved attempt prefix."""
    attempt_id = UUIDProcessingAttemptIdGenerator().generate()

    assert attempt_id.startswith("attempt_")
    assert ATTEMPT_ID_PATTERN.fullmatch(attempt_id)


def test_uuid_attempt_generator_returns_unique_identifiers() -> None:
    """Sequential generations should not reuse attempt identifiers."""
    generator = UUIDProcessingAttemptIdGenerator()

    first = generator.generate()
    second = generator.generate()

    assert first != second
