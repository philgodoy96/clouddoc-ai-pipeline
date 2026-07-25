"""Tests for the concrete runtime job identifier generator."""

import re

from clouddoc.application import JobIdGenerator
from clouddoc.infrastructure import UUIDJobIdGenerator

JOB_ID_PATTERN = re.compile(r"^job_[0-9a-f]{32}$")


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
