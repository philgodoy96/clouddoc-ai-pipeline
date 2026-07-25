"""Tests for the canonical document object-key contract."""

import pytest

from clouddoc.schemas.document_keys import (
    build_document_object_key,
    extract_job_id_from_document_object_key,
)


def test_builds_canonical_document_object_key() -> None:
    """A document job should own one canonical source object."""
    assert build_document_object_key("job-001") == "documents/job-001/source.txt"


def test_trims_job_id_when_building_object_key() -> None:
    """Surrounding whitespace should not enter the object key."""
    assert build_document_object_key("  job-001  ") == "documents/job-001/source.txt"


@pytest.mark.parametrize(
    "job_id",
    [
        "",
        " ",
        "   ",
        "\t",
    ],
)
def test_rejects_blank_job_id(
    job_id: str,
) -> None:
    """A document object key requires a valid job identity."""
    with pytest.raises(
        ValueError,
        match="job_id must not be empty",
    ):
        build_document_object_key(job_id)


def test_extracts_job_id_from_canonical_object_key() -> None:
    """The canonical object key should expose its owning job."""
    assert (
        extract_job_id_from_document_object_key("documents/job-001/source.txt")
        == "job-001"
    )


def test_trims_object_key_before_extraction() -> None:
    """Surrounding whitespace should not affect key parsing."""
    assert (
        extract_job_id_from_document_object_key("  documents/job-001/source.txt  ")
        == "job-001"
    )


@pytest.mark.parametrize(
    "object_key",
    [
        "",
        " ",
        "documents/source.txt",
        "documents//source.txt",
        "documents/job-001/other.txt",
        "documents/job-001/source.pdf",
        "uploads/job-001/source.txt",
        "documents/job-001/nested/source.txt",
        "/documents/job-001/source.txt",
        "documents/job-001/source.txt/",
    ],
)
def test_rejects_invalid_canonical_object_key(
    object_key: str,
) -> None:
    """Only the approved document object-key structure is valid."""
    expected_message = (
        "object_key must not be empty"
        if not object_key.strip()
        else "invalid canonical document object key"
    )

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        extract_job_id_from_document_object_key(object_key)
