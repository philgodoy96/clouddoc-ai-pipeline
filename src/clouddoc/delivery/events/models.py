"""Normalized delivery models for uploaded-document events."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from clouddoc.schemas.document_keys import (
    extract_job_id_from_document_object_key,
)


class UploadedDocumentEvent(BaseModel):
    """Normalized S3 ObjectCreated event received through SQS."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
    )

    message_id: str = Field(min_length=1)
    event_name: str = Field(
        min_length=1,
        pattern=r"^ObjectCreated:.+$",
    )
    bucket_name: str = Field(min_length=1)
    object_key: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    object_size: int = Field(ge=0)
    etag: str | None = Field(
        default=None,
        min_length=1,
    )
    sequencer: str | None = Field(
        default=None,
        min_length=1,
    )
    version_id: str | None = Field(
        default=None,
        min_length=1,
    )

    @field_validator(
        "message_id",
        "event_name",
        "bucket_name",
        "object_key",
        "job_id",
        "etag",
        "sequencer",
        "version_id",
        mode="before",
    )
    @classmethod
    def reject_blank_strings(
        cls,
        value: object,
    ) -> object:
        """Reject whitespace-only event values without coercion."""
        if isinstance(value, str) and not value.strip():
            raise ValueError("event string values must not be blank")

        return value

    @model_validator(mode="after")
    def validate_document_key_ownership(
        self,
    ) -> "UploadedDocumentEvent":
        """Ensure the canonical object key belongs to the declared job."""
        try:
            extracted_job_id = extract_job_id_from_document_object_key(self.object_key)
        except ValueError as error:
            raise ValueError(
                "object_key must be a canonical document object key"
            ) from error

        if extracted_job_id != self.job_id:
            raise ValueError("job_id must match the canonical document object key")

        return self
