"""Canonical document object-key contract."""

DOCUMENT_OBJECT_KEY_PREFIX = "documents"
DOCUMENT_SOURCE_FILENAME = "source.txt"


def build_document_object_key(
    job_id: str,
) -> str:
    """Build the canonical object key owned by a document job."""
    normalized_job_id = job_id.strip()

    if not normalized_job_id:
        raise ValueError("job_id must not be empty")

    return (
        f"{DOCUMENT_OBJECT_KEY_PREFIX}/{normalized_job_id}/{DOCUMENT_SOURCE_FILENAME}"
    )


def extract_job_id_from_document_object_key(
    object_key: str,
) -> str:
    """Extract a job ID from a canonical document object key."""
    normalized_object_key = object_key.strip()

    if not normalized_object_key:
        raise ValueError("object_key must not be empty")

    parts = normalized_object_key.split("/")

    if parts != [
        DOCUMENT_OBJECT_KEY_PREFIX,
        parts[1] if len(parts) > 1 else "",
        DOCUMENT_SOURCE_FILENAME,
    ]:
        raise ValueError("invalid canonical document object key")

    job_id = parts[1]

    if not job_id:
        raise ValueError("invalid canonical document object key")

    return job_id
