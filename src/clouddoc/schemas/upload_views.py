"""Application-facing views for document upload instructions."""

from pydantic import BaseModel, ConfigDict, Field

DOCUMENT_UPLOAD_METHOD = "PUT"
DOCUMENT_UPLOAD_CONTENT_TYPE = "text/plain"
DOCUMENT_OBJECT_KEY_PREFIX = "documents"
DOCUMENT_SOURCE_FILENAME = "source.txt"


def build_document_object_key(
    job_id: str,
) -> str:
    """Build the canonical S3 object key for a document job."""
    normalized_job_id = job_id.strip()

    if not normalized_job_id:
        raise ValueError("job_id must not be empty")

    return (
        f"{DOCUMENT_OBJECT_KEY_PREFIX}/{normalized_job_id}/{DOCUMENT_SOURCE_FILENAME}"
    )


class PresignedDocumentUpload(BaseModel):
    """Upload instructions returned to an API client."""

    model_config = ConfigDict(frozen=True)

    method: str = Field(
        default=DOCUMENT_UPLOAD_METHOD,
        pattern=r"^PUT$",
    )
    url: str = Field(min_length=1)
    headers: dict[str, str]
    object_key: str = Field(min_length=1)
    expires_in_seconds: int = Field(gt=0)

    @classmethod
    def create(
        cls,
        *,
        url: str,
        object_key: str,
        expires_in_seconds: int,
    ) -> "PresignedDocumentUpload":
        """Create upload instructions with the approved HTTP contract."""
        normalized_url = url.strip()
        normalized_object_key = object_key.strip()

        if not normalized_url:
            raise ValueError("upload URL must not be empty")

        if not normalized_object_key:
            raise ValueError("object key must not be empty")

        return cls(
            url=normalized_url,
            headers={
                "content-type": DOCUMENT_UPLOAD_CONTENT_TYPE,
            },
            object_key=normalized_object_key,
            expires_in_seconds=expires_in_seconds,
        )
