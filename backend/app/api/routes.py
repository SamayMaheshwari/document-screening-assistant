from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import serializers as S
from app.audit.service import log_event, verify_chain
from app.core.config import get_settings
from app.core.security import (PERMISSIONS, can_see_pii, current_user, make_token, require, verify_password)
from app.database.models import (AuditEvent, Document, ExtractedField, FieldCorrection, OfficerReview, ScreeningCase, User,
                                 ValidationResult)
from app.database.session import get_db
from app.modules.intake.service import create_case, ingest_document
from app.modules.intake.validate import IntakeError
from app.orchestration.pipeline import recompute_after_correction, run_pipeline
from app.reporting.report import build_pdf
from app.storage.backend import get_storage
from app.synthetic import samples

router = APIRouter(prefix="/api/v1")

OUTCOMES = {"NO_ISSUES_FOUND": "No issues found - routine processing",
            "REFER_SECONDARY": "Refer to secondary examination",
            "RECAPTURE_REQUESTED": "Recapture / re-present document",
            "ESCALATE_SUPERVISOR": "Escalate to supervisor"}


def _req_id(request: Request) -> str:
    return request.headers.get("x-request-id") or str(uuid.uuid4())


def _dispatch(background: BackgroundTasks, case_id: str):
    """Job dispatcher: BackgroundTasks now, Celery later (one-line change)."""
    background.add_task(run_pipeline, case_id)


def _case_or_404(db: Session, case_id: str) -> ScreeningCase:
    case = db.get(ScreeningCase, case_id)
    if not case:
        raise HTTPException(404, "Case not found")
    return case


# ------------------------------------------------------------------ auth / health
class LoginBody(BaseModel):
    username: str
    password: str


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    s = get_settings()
    return {"status": "ok", "database": "ok", "storage": s.storage_backend, "jobs": s.jobs_backend, "environment": s.environment,
            "time": datetime.now(timezone.utc).isoformat()}


@router.post("/auth/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == body.username.strip().lower())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash) or user.status != "active":
        log_event(db, body.username[:60], "auth.login_failed", request_id=_req_id(request))
        raise HTTPException(401, "Invalid username or password")
    log_event(db, user.display_name, "auth.login", role=user.role, request_id=_req_id(request))
    return {"token": make_token(user), "user": _user_json(user)}


def _user_json(u: User) -> dict:
    return {"id": u.id, "username": u.username, "name": u.display_name, "role": u.role,
            "permissions": sorted(PERMISSIONS.get(u.role, set()))}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return _user_json(user)


# ------------------------------------------------------------------ cases
@router.post("/cases", status_code=202)
async def post_case(request: Request, background: BackgroundTasks, file: UploadFile = File(...), label: str | None = Form(None),
                    user: User = Depends(require("case:create")), db: Session = Depends(get_db)):
    data = await file.read()
    try:
        case, doc = create_case(db, user, data, file.filename or "upload", label=(label or None))
    except IntakeError as e:
        log_event(db, user.display_name, "intake.rejected", role=user.role, request_id=_req_id(request),
                  metadata={"code": e.code, "reason": e.message, "filename_len": len(file.filename or "")})
        raise HTTPException(422, {"code": e.code, "message": e.message})
    log_event(db, user.display_name, "case.created", case.id, user.role, _req_id(request),
              {"sha256": doc.sha256, "size": doc.size_bytes, "media_type": doc.media_type})
    _dispatch(background, case.id)
    return {"case_id": case.id, "case_number": case.case_number, "status": "PROCESSING"}


@router.get("/cases")
def list_cases(status: str | None = None, priority: str | None = None, q: str | None = None, limit: int = Query(100, le=500),
               user: User = Depends(require("case:read")), db: Session = Depends(get_db)):
    stmt = select(ScreeningCase).order_by(ScreeningCase.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(ScreeningCase.status == status)
    if q:
        stmt = stmt.where(or_(ScreeningCase.case_number.ilike(f"%{q}%"), ScreeningCase.label.ilike(f"%{q}%")))
    cases = db.execute(stmt).scalars().all()
    items = [S.case_summary(db, c, user) for c in cases]
    if priority:
        items = [i for i in items if i["priority"] == priority]
    return {"items": items, "total": len(items)}


@router.get("/cases/{case_id}")
def get_case(case_id: str, user: User = Depends(require("case:read")), db: Session = Depends(get_db)):
    return S.case_summary(db, _case_or_404(db, case_id), user) | {"steps": _case_or_404(db, case_id).pipeline_steps or []}


@router.get("/cases/{case_id}/results")
def get_results(case_id: str, request: Request, user: User = Depends(require("case:read")), db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    if request.query_params.get("log") == "1":
        log_event(db, user.display_name, "case.viewed", case.id, user.role, _req_id(request))
    return S.build_results(db, case, user)


@router.get("/cases/{case_id}/image")
def get_image(case_id: str, request: Request, kind: str = "rectified", user: User = Depends(require("case:read")),
              db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    if not can_see_pii(user):
        raise HTTPException(403, "Document images are hidden for your role")
    doc = S.current_doc(case)
    if not doc:
        raise HTTPException(404, "No document")
    key, mt = {"original": (doc.storage_key, doc.media_type), "rectified": (doc.rectified_key, "image/png"),
               "heatmap": (doc.heatmap_key, "image/png")}.get(kind, (None, None))
    if not key:
        raise HTTPException(404, f"No {kind} image for this capture")
    if request.query_params.get("log") == "1":
        log_event(db, user.display_name, f"image.viewed.{kind}", case.id, user.role, _req_id(request))
    return Response(get_storage().get(key), media_type=mt, headers={"Cache-Control": "private, max-age=300"})


@router.post("/cases/{case_id}/recapture", status_code=202)
async def recapture(case_id: str, request: Request, background: BackgroundTasks, file: UploadFile = File(...),
                    rationale: str = Form(...), user: User = Depends(require("case:recapture")), db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    if len(rationale.strip()) < 5:
        raise HTTPException(422, {"code": "rationale_required", "message": "A short rationale is required to attach a new capture."})
    data = await file.read()
    for d in case.documents:
        d.superseded = True
    try:
        doc = ingest_document(db, case, data, file.filename or "recapture", "recapture")
    except IntakeError as e:
        db.rollback()
        raise HTTPException(422, {"code": e.code, "message": e.message})
    case.status = "PROCESSING"
    db.commit()
    log_event(db, user.display_name, "case.recapture", case.id, user.role, _req_id(request),
              {"capture_index": doc.capture_index, "sha256": doc.sha256, "rationale": rationale[:300]})
    _dispatch(background, case.id)
    return {"case_id": case.id, "status": "PROCESSING", "capture_index": doc.capture_index}


class ReviewBody(BaseModel):
    outcome: str
    rationale: str = Field(min_length=10, max_length=2000)


@router.post("/cases/{case_id}/review")
def post_review(case_id: str, body: ReviewBody, request: Request, user: User = Depends(require("case:review")),
                db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    if body.outcome not in OUTCOMES:
        raise HTTPException(422, {"code": "bad_outcome", "message": f"Outcome must be one of {sorted(OUTCOMES)}"})
    if case.status in ("PROCESSING", "NEW"):
        raise HTTPException(409, "Case is still processing")
    db.add(OfficerReview(case_id=case.id, officer_id=user.id, officer_name=user.display_name, outcome=body.outcome, rationale=body.rationale))
    case.status = "REVIEWED"
    db.commit()
    log_event(db, user.display_name, "review.submitted", case.id, user.role, _req_id(request),
              {"outcome": body.outcome, "rationale_len": len(body.rationale)})
    return {"ok": True, "status": case.status}


class CorrectionBody(BaseModel):
    value: str = Field(min_length=0, max_length=256)
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/cases/{case_id}/fields/{field_id}")
def correct_field(case_id: str, field_id: str, body: CorrectionBody, request: Request,
                  user: User = Depends(require("field:correct")), db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    f = db.get(ExtractedField, field_id)
    doc = S.current_doc(case)
    if not f or not doc or f.document_id != doc.id:
        raise HTTPException(404, "Field not found on the current capture")
    prev = f.corrected_value if f.corrected_value is not None else (f.normalized_value if f.source == "MRZ" else f.raw_value)
    new = body.value.strip().upper() if f.source == "MRZ" else body.value.strip()
    db.add(FieldCorrection(field_id=f.id, officer_id=user.id, officer_name=user.display_name, previous_value=prev or "",
                           new_value=new, reason=body.reason))
    f.corrected_value = new
    f.needs_review = False
    db.commit()
    changes = recompute_after_correction(db, case, doc)
    log_event(db, user.display_name, "field.corrected", case.id, user.role, _req_id(request),
              {"field": f.field_name, "reason": body.reason[:200], "check_changes": {k: list(v) for k, v in changes.items()}})
    return {"ok": True, "check_changes": {k: {"from": v[0], "to": v[1]} for k, v in changes.items()}}


@router.get("/cases/{case_id}/audit")
def case_audit(case_id: str, user: User = Depends(require("case:read")), db: Session = Depends(get_db)):
    _case_or_404(db, case_id)
    rows = db.execute(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.seq.desc()).limit(200)).scalars().all()
    return {"items": [_audit_json(a) for a in rows]}


@router.get("/cases/{case_id}/report")
def report(case_id: str, request: Request, user: User = Depends(require("case:report")), db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    results = S.build_results(db, case, user)
    rows = db.execute(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.seq.desc()).limit(30)).scalars().all()
    img = None
    doc = S.current_doc(case)
    if doc and doc.rectified_key and can_see_pii(user):
        img = get_storage().get(doc.rectified_key)
    pdf = build_pdf(results, [_audit_json(a) for a in rows], f"{user.display_name} ({user.role})", img)
    log_event(db, user.display_name, "report.exported", case.id, user.role, _req_id(request),
              {"pii_redacted": results["pii_redacted"], "bytes": len(pdf)})
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{case.case_number}-report.pdf"'})


# ------------------------------------------------------------------ audit / stats / admin
def _audit_json(a: AuditEvent) -> dict:
    return {"seq": a.seq, "timestamp": a.timestamp.isoformat() + "Z", "actor": a.actor, "actor_role": a.actor_role, "action": a.action,
            "case_id": a.case_id, "request_id": a.request_id, "metadata": a.event_metadata, "hash": a.event_hash[:16]}


@router.get("/audit")
def audit(action: str | None = None, limit: int = Query(200, le=1000), user: User = Depends(require("audit:read")),
          db: Session = Depends(get_db)):
    stmt = select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action.like(f"{action}%"))
    return {"items": [_audit_json(a) for a in db.execute(stmt).scalars().all()],
            "total": db.execute(select(func.count()).select_from(AuditEvent)).scalar_one()}


@router.get("/audit/verify")
def audit_verify(user: User = Depends(require("audit:read")), db: Session = Depends(get_db)):
    return verify_chain(db)


@router.get("/stats")
def stats(user: User = Depends(require("case:read")), db: Session = Depends(get_db)):
    by_status = dict(db.execute(select(ScreeningCase.status, func.count()).group_by(ScreeningCase.status)).all())
    total = sum(by_status.values())
    cases = db.execute(select(ScreeningCase)).scalars().all()
    by_priority: dict[str, int] = {}
    unresolved = 0
    for c in cases:
        if c.risk:
            by_priority[c.risk[0].priority] = by_priority.get(c.risk[0].priority, 0) + 1
            unresolved += 1 if c.risk[0].unresolved else 0
    checks = dict(db.execute(select(ValidationResult.status, func.count()).group_by(ValidationResult.status)).all())
    day = datetime.utcnow() - timedelta(days=1)
    return {"total": total, "by_status": by_status, "by_priority": by_priority, "check_status": checks,
            "needs_attention": by_status.get("REVIEW_REQUIRED", 0) + by_status.get("RECAPTURE_REQUIRED", 0),
            "cases_with_unresolved": unresolved,
            "last_24h": db.execute(select(func.count()).select_from(ScreeningCase).where(ScreeningCase.created_at >= day)).scalar_one()}


# ------------------------------------------------------------------ demo lab
@router.get("/demo/samples")
def demo_samples(user: User = Depends(current_user)):
    return {"items": samples.catalogue()}


@router.get("/demo/samples/{variant}/image")
def demo_sample_image(variant: str, user: User = Depends(current_user)):
    try:
        b, _ = samples.sample_bytes(variant)
    except KeyError:
        raise HTTPException(404, "Unknown sample")
    return Response(b, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/demo/samples/{variant}/download")
def demo_sample_download(variant: str, user: User = Depends(current_user)):
    try:
        b, _ = samples.sample_bytes(variant)
    except KeyError:
        raise HTTPException(404, "Unknown sample")
    return Response(b, media_type="image/jpeg", headers={"Content-Disposition": f'attachment; filename="demo_{variant}.jpg"'})


@router.post("/demo/samples/{variant}/submit", status_code=202)
def demo_sample_submit(variant: str, request: Request, background: BackgroundTasks, user: User = Depends(require("case:create")),
                       db: Session = Depends(get_db)):
    try:
        b, meta = samples.sample_bytes(variant)
    except KeyError:
        raise HTTPException(404, "Unknown sample")
    case, doc = create_case(db, user, b, f"demo_{variant}.jpg", label=f"[DEMO] {meta['title']}", demo_flags=samples.flags_for(variant),
                            capture_source="demo-sample")
    log_event(db, user.display_name, "case.created", case.id, user.role, _req_id(request), {"sha256": doc.sha256, "demo_sample": variant})
    _dispatch(background, case.id)
    return {"case_id": case.id, "case_number": case.case_number, "status": "PROCESSING"}


@router.get("/evaluation")
def evaluation(user: User = Depends(current_user)):
    p = get_settings().synthetic_dir.parent / "evaluation" / "results.json"
    if not p.exists():
        return {"available": False}
    return {"available": True, **json.loads(p.read_text())}
