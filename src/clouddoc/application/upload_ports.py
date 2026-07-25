"""Application-layer contract for document upload provisioning."""

from typing import Protocol, runtime_checkable

from clouddoc.schemas.upload_views import PresignedDocumentUpload


@runtime_checkable
class DocumentUploadProvider(Protocol):
    """Provide upload instructions for one document job."""

    def create_upload(
        self,
        *,
        job_id: str,
    ) -> PresignedDocumentUpload:
        """Create upload instructions for a document job."""
        ...
