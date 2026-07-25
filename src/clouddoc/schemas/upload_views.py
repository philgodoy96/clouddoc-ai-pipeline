"""Application-facing views for document upload instructions."""

from pydantic import BaseModel, ConfigDict, Field

from clouddoc.schemas.job_views import DocumentJobView

DOCUMENT_UPLOAD_METHOD = "PUT"
DOCUMENT_UPLOAD_CONTENT_TYPE = "text/plain"


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


class CreateDocumentJobResult(BaseModel):
    """Created document job together with upload instructions."""

    model_config = ConfigDict(frozen=True)

    job: DocumentJobView
    upload: PresignedDocumentUpload
