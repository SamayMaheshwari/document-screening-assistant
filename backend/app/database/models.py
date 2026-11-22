"""Relational schema (PDF s.6). SQLite now / PostgreSQL later: no Postgres-only features."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))
    password_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ScreeningCase(Base):
    __tablename__ = "screening_cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    case_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="NEW", index=True)
    document_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capture_source: Mapped[str] = mapped_column(String(32), default="upload")
    assigned_officer: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_steps: Mapped[list] = mapped_column(JSON, default=list)
    demo_flags: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. simulated registry outage
    label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    documents = relationship("Document", back_populates="case", order_by="Document.capture_index")
    validation_results = relationship("ValidationResult", back_populates="case")
    risk = relationship("RiskAssessment", back_populates="case", order_by="RiskAssessment.created_at.desc()")
    reviews = relationship("OfficerReview", back_populates="case", order_by="OfficerReview.reviewed_at")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("screening_cases.id"), index=True)
    capture_index: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(128))  # random key; original never modified
    rectified_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    heatmap_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    media_type: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    capture_source: Mapped[str] = mapped_column(String(32), default="upload")
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    preprocessing: Mapped[dict] = mapped_column(JSON, default=dict)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    case = relationship("ScreeningCase", back_populates="documents")
    fields = relationship("ExtractedField", back_populates="document")
    findings = relationship("ForensicFinding", back_populates="document")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(48))
    source: Mapped[str] = mapped_column(String(8))  # VIZ | MRZ
    raw_value: Mapped[str] = mapped_column(String(256), default="")
    normalized_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    bounding_box: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [x,y,w,h] in rectified px
    engine: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(32))
    corrected_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)

    document = relationship("Document", back_populates="fields")
    corrections = relationship("FieldCorrection", back_populates="field", order_by="FieldCorrection.created_at")


class FieldCorrection(Base):
    __tablename__ = "field_corrections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    field_id: Mapped[str] = mapped_column(ForeignKey("extracted_fields.id"), index=True)
    officer_id: Mapped[str] = mapped_column(String(36))
    officer_name: Mapped[str] = mapped_column(String(128))
    previous_value: Mapped[str] = mapped_column(String(256))
    new_value: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    field = relationship("ExtractedField", back_populates="corrections")


class ValidationResult(Base):
    __tablename__ = "validation_results"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("screening_cases.id"), index=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    check_id: Mapped[str] = mapped_column(String(64))
    check_type: Mapped[str] = mapped_column(String(32))  # quality | structure | consistency | status | forensic | external | biometric
    dimension: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(48))
    evidence_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    case = relationship("ScreeningCase", back_populates="validation_results")


class ForensicFinding(Base):
    __tablename__ = "forensic_findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    finding_type: Mapped[str] = mapped_column(String(48))
    zone: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    region: Mapped[list | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    model_version: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    document = relationship("Document", back_populates="findings")


class FaceCheck(Base):
    __tablename__ = "face_checks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("screening_cases.id"), index=True)
    quality_status: Mapped[str] = mapped_column(String(16))
    comparison_status: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text, default="")
    model_version: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("screening_cases.id"), index=True)
    priority: Mapped[str] = mapped_column(String(16))  # LOW | MEDIUM | HIGH | INCOMPLETE
    dimensions: Mapped[dict] = mapped_column(JSON, default=dict)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    unresolved: Mapped[list] = mapped_column(JSON, default=list)
    policy_version: Mapped[str] = mapped_column(String(48))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    case = relationship("ScreeningCase", back_populates="risk")


class OfficerReview(Base):
    __tablename__ = "officer_reviews"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("screening_cases.id"), index=True)
    officer_id: Mapped[str] = mapped_column(String(36))
    officer_name: Mapped[str] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    case = relationship("ScreeningCase", back_populates="reviews")


class AuditEvent(Base):
    """Append-only, hash-chained. Each row commits to the previous row's hash."""
    __tablename__ = "audit_events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), default=_id, unique=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    actor: Mapped[str] = mapped_column(String(128))
    actor_role: Mapped[str] = mapped_column(String(16), default="system")
    action: Mapped[str] = mapped_column(String(48), index=True)
    case_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64), default="")
