"""Case creation and document ingestion (secure intake)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.models import Document, ScreeningCase, User
from app.modules.intake.validate import IntakeError, validate_upload
from app.storage.backend import get_storage, sha256_hex


def next_case_number(db: Session) -> str:
    n = (db.execute(select(func.count()).select_from(ScreeningCase)).scalar_one() or 0) + 1
    year = datetime.now(timezone.utc).year
    return f"SC-{year}-{n:06d}"


def ingest_document(db: Session, case: ScreeningCase, data: bytes, filename: str, capture_source: str = "upload") -> Document:
    """Validate and persist an upload. The original bytes are stored unchanged under a random key."""
    info = validate_upload(data, filename, get_settings())
    key = get_storage().put(data, prefix="originals", ext="bin")
    idx = len(case.documents) + 1
    doc = Document(case_id=case.id, capture_index=idx, storage_key=key, sha256=sha256_hex(data), media_type=info.media_type,
                   original_filename=filename[:255], size_bytes=info.size_bytes, width=info.width, height=info.height,
                   capture_source=capture_source)
    db.add(doc)
    db.flush()
    return doc


def create_case(db: Session, user: User | None, data: bytes, filename: str, label: str | None = None,
                demo_flags: dict | None = None, capture_source: str = "upload") -> tuple[ScreeningCase, Document]:
    case = ScreeningCase(case_number=next_case_number(db), status="NEW", capture_source=capture_source,
                         created_by=user.id if user else None, assigned_officer=user.id if user and user.role == "officer" else None,
                         demo_flags=demo_flags or {}, label=label)
    db.add(case)
    db.flush()
    try:
        doc = ingest_document(db, case, data, filename, capture_source)
    except IntakeError:
        db.rollback()
        raise
    db.commit()
    return case, doc
