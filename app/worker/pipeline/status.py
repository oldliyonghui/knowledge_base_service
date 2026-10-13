import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentStatus


def set_document_status(
    session: Session,
    doc_id: uuid.UUID,
    status: DocumentStatus,
    error_msg: str | None = None,
) -> None:
    doc = session.get(Document, doc_id)
    if not doc:
        return
    doc.status = status
    doc.error_msg = error_msg
    doc.updated_at = datetime.now(timezone.utc)
    session.add(doc)
    session.commit()