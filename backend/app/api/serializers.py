"""Builds API payloads from DB rows, applying role-based redaction."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import can_see_pii
from app.database.models import (Document, ExtractedField, FaceCheck, ForensicFinding, OfficerReview, RiskAssessment,
                                 ScreeningCase, User, ValidationResult)
from app.modules.classification import template as T
from app.modules.ocr_mrz.mrz import MRZResult
from app.orchestration.pipeline import effective_views, parse_effective_mrz

SENSITIVE_FIELDS = {"surname", "given_names", "passport_number", "date_of_birth", "place_of_birth",
                    "date_of_issue", "date_of_expiry", "mrz_line1", "mrz_line2"}

LIMITATIONS = [
    "Decision-support only: the system flags evidence and review needs; authorised officers make every decision.",
    "ELA is a weak baseline indicator. It needs an unresampled capture and a compatible JPEG history; metadata and compression traces can be stripped or forged.",
    "A clean forensic result does not authenticate a document. Holograms, UV/IR features, substrate and tactile security features cannot be assessed from an RGB image.",
    "Face comparison, ePassport chip / PKD verification and live registry checks are not part of this prototype and are shown as unavailable/not applicable.",
    "All demo documents are synthetic (fictional people, ICAO test State UTO). Results do not generalise to real documents until evaluated on authorised data.",
]


def mask(s: str | None) -> str | None:
    if not s:
        return s
    return s[0] + "•" * (len(s) - 1) if len(s) > 1 else "•"


def sensitive_values(doc: Document | None) -> set[str]:
    out: set[str] = set()
    if not doc:
        return out
    viz, lines, _, _ = effective_views(doc)
    for n, f in viz.items():
        if n in SENSITIVE_FIELDS:
            for v in (f.raw, f.value):
                if v and len(v) > 2:
                    out.add(v)
    mrz = parse_effective_mrz(lines)
    if mrz and mrz.format_ok:
        for v in (mrz.surname, mrz.given_names, mrz.passport_number, mrz.birth_date_raw, mrz.expiry_date_raw,
                  mrz.birth_date.isoformat() if mrz.birth_date else "", mrz.expiry_date.isoformat() if mrz.expiry_date else ""):
            if v and len(v) > 2:
                out.add(v)
    for l in lines:
        if l:
            out.add(l)
    return out


def redact_text(text: str | None, sens: set[str]) -> str | None:
    if not text:
        return text
    for s in sorted(sens, key=len, reverse=True):
        text = text.replace(s, mask(s) or "")
    return text


def current_doc(case: ScreeningCase) -> Document | None:
    live = [d for d in case.documents if not d.superseded]
    return live[-1] if live else (case.documents[-1] if case.documents else None)


def case_summary(db: Session, case: ScreeningCase, user: User) -> dict:
    doc = current_doc(case)
    risk = case.risk[0] if case.risk else None
    pii = can_see_pii(user)
    holder = None
    if doc:
        viz, lines, _, _ = effective_views(doc)
        sn, gn = (viz.get("surname").value if viz.get("surname") else None), (viz.get("given_names").value if viz.get("given_names") else None)
        if sn:
            holder = f"{sn}, {gn}" if gn else sn
            if not pii:
                holder = mask(sn) + ", " + (mask(gn.split()[0]) if gn else "")
    return {
        "id": case.id, "case_number": case.case_number, "status": case.status, "document_type": case.document_type,
        "label": case.label, "holder": holder, "capture_source": case.capture_source, "failure_reason": case.failure_reason,
        "priority": risk.priority if risk else None, "complete": (risk.dimensions or {}).get("_complete") if risk else None,
        "unresolved_count": len(risk.unresolved) if risk else 0, "reason_count": len([r for r in (risk.reasons if risk else []) if r.get("status") != "INFO"]),
        "created_at": case.created_at.isoformat() + "Z", "updated_at": case.updated_at.isoformat() + "Z",
        "capture_count": len(case.documents), "reviewed": bool(case.reviews),
    }


def build_results(db: Session, case: ScreeningCase, user: User) -> dict:
    pii = can_see_pii(user)
    doc = current_doc(case)
    out: dict = {"case": case_summary(db, case, user), "pii_redacted": not pii, "steps": case.pipeline_steps or [],
                 "limitations": LIMITATIONS, "document": None, "documents": [], "fields": [], "mrz": None, "checks": [],
                 "forensics": None, "face": None, "risk": None, "reviews": []}
    if not doc:
        return out
    sens = sensitive_values(doc) if not pii else set()
    out["documents"] = [{"id": d.id, "capture_index": d.capture_index, "sha256": d.sha256, "superseded": d.superseded,
                         "created_at": d.created_at.isoformat() + "Z", "original_filename": d.original_filename if pii else "(hidden)"}
                        for d in case.documents]
    out["document"] = {"id": doc.id, "sha256": doc.sha256, "media_type": doc.media_type, "size_bytes": doc.size_bytes,
                       "width": doc.width, "height": doc.height, "capture_index": doc.capture_index,
                       "original_filename": doc.original_filename if pii else "(hidden)",
                       "quality": (doc.quality or {}).get("metrics", []), "preprocessing": doc.preprocessing or {},
                       "has_rectified": bool(doc.rectified_key), "has_heatmap": bool(doc.heatmap_key),
                       "created_at": doc.created_at.isoformat() + "Z"}
    # fields
    for f in sorted(doc.fields, key=lambda f: (f.source != "VIZ", list(T.FIELD_ZONES).index(f.field_name) if f.field_name in T.FIELD_ZONES else 99)):
        sensitive = f.field_name in SENSITIVE_FIELDS and not pii
        out["fields"].append({
            "id": f.id, "name": f.field_name, "label": T.FIELD_LABELS.get(f.field_name, f.field_name.replace("_", " ").title()),
            "source": f.source, "raw": mask(f.raw_value) if sensitive else f.raw_value,
            "value": mask(f.normalized_value) if sensitive else f.normalized_value,
            "corrected_value": (mask(f.corrected_value) if sensitive else f.corrected_value),
            "confidence": f.confidence, "bbox": f.bounding_box, "needs_review": f.needs_review, "engine": f.engine,
            "engine_version": f.engine_version,
            "corrections": [{"officer": c.officer_name, "previous": mask(c.previous_value) if sensitive else c.previous_value,
                             "new": mask(c.new_value) if sensitive else c.new_value, "reason": c.reason,
                             "at": c.created_at.isoformat() + "Z"} for c in f.corrections]})
    # mrz
    viz, lines, confs, repairs = effective_views(doc)
    mrz: MRZResult | None = parse_effective_mrz(lines)
    if mrz is not None and any(lines):
        parsed = None
        if mrz.format_ok:
            parsed = {"document_code": mrz.document_code, "issuer": mrz.issuer, "surname": mrz.surname, "given_names": mrz.given_names,
                      "passport_number": mrz.passport_number, "nationality": mrz.nationality, "date_of_birth": mrz.birth_date.isoformat() if mrz.birth_date else mrz.birth_date_raw,
                      "sex": mrz.sex, "date_of_expiry": mrz.expiry_date.isoformat() if mrz.expiry_date else mrz.expiry_date_raw,
                      "personal_number": mrz.personal_number}
            if not pii:
                for k in ("surname", "given_names", "passport_number", "date_of_birth", "date_of_expiry", "personal_number"):
                    if parsed.get(k):
                        parsed[k] = mask(str(parsed[k]))
        out["mrz"] = {"lines": [mask(l) if not pii else l for l in lines], "format_ok": mrz.format_ok,
                      "errors": mrz.format_errors, "parsed": parsed, "repairs": repairs,
                      "digit_checks": [{"name": c.name, "printed": c.expected, "computed": c.computed, "valid": c.valid} for c in mrz.checks],
                      "confidence": confs}
    # checks
    rows = db.execute(select(ValidationResult).where(ValidationResult.document_id == doc.id)).scalars().all()
    order = {"capture_quality": 0, "document_integrity": 1, "information_consistency": 2, "document_status": 3, "person_comparison": 4}
    for r in sorted(rows, key=lambda r: (order.get(r.dimension, 9), r.checked_at, r.check_id)):
        ev = {k: v for k, v in (r.evidence_ref or {}).items() if k != "_group"}
        msg = redact_text(r.message, sens)
        if sens:
            for k in ("viz", "mrz", "printed", "computed", "data"):
                if k in ev and isinstance(ev[k], str):
                    ev[k] = mask(ev[k])
        out["checks"].append({"id": r.check_id, "check_type": r.check_type, "dimension": r.dimension, "title": r.title,
                              "status": r.status, "message": msg, "source": r.source, "rule_version": r.rule_version,
                              "evidence": ev or None, "checked_at": r.checked_at.isoformat() + "Z"})
    # forensics
    fnds = db.execute(select(ForensicFinding).where(ForensicFinding.document_id == doc.id)).scalars().all()
    ela_check = next((c for c in out["checks"] if c["id"] == "forensics_ela"), None)
    out["forensics"] = {"applicable": bool(fnds), "status": ela_check["status"] if ela_check else None,
                        "reason": ela_check["message"] if ela_check else "", "model_version": fnds[0].model_version if fnds else "ela-bgzone-baseline-0.2",
                        "findings": [{"zone": f.zone, "status": f.status, "z": f.score, "region": f.region, "message": f.message} for f in fnds],
                        "has_heatmap": bool(doc.heatmap_key)}
    fc = db.execute(select(FaceCheck).where(FaceCheck.case_id == case.id).order_by(FaceCheck.created_at.desc())).scalars().first()
    if fc:
        out["face"] = {"quality": fc.quality_status, "comparison": fc.comparison_status, "message": fc.message, "model_version": fc.model_version}
    risk = case.risk[0] if case.risk else None
    if risk:
        out["risk"] = {"priority": risk.priority, "dimensions": {k: v for k, v in risk.dimensions.items() if not k.startswith("_")},
                       "complete": risk.dimensions.get("_complete"),
                       "reasons": [{**r, "text": redact_text(r["text"], sens)} for r in risk.reasons],
                       "unresolved": [{**r, "text": redact_text(r["text"], sens)} for r in risk.unresolved],
                       "policy_version": risk.policy_version, "created_at": risk.created_at.isoformat() + "Z"}
    out["reviews"] = [{"id": r.id, "officer": r.officer_name, "outcome": r.outcome, "rationale": r.rationale,
                       "reviewed_at": r.reviewed_at.isoformat() + "Z"} for r in case.reviews]
    out["template"] = {"id": T.TEMPLATE_ID, "size": [T.CARD_W, T.CARD_H], "photo": T.PHOTO_ZONE, "stamp": T.STAMP_ZONE,
                       "mrz": T.MRZ_ZONE, "fields": T.FIELD_ZONES}
    return out
