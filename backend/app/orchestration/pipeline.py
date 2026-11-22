"""Processing pipeline for one case. `run_pipeline(case_id)` is the only entry point, so swapping
FastAPI BackgroundTasks for Celery later is a one-line change in the job dispatcher."""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import date, datetime, timezone

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import log_event
from app.core.config import get_settings
from app.core.enums import CaseStatus, Status
from app.database.models import (Document, ExtractedField, FaceCheck, ForensicFinding, RiskAssessment,
                                 ScreeningCase, ValidationResult)
from app.database.session import SessionLocal
from app.modules.classification import template as T
from app.modules.face_verification.verifier import get_verifier
from app.modules.forensics import ela
from app.modules.ocr_mrz import extract as ocr
from app.modules.ocr_mrz.mrz import correct_by_field_type, parse_td3
from app.modules.preprocessing.rectify import locate_and_rectify, measure_quality, rotate_180
from app.modules.registry.connector import get_registry
from app.modules.risk.engine import POLICY_VERSION, assess
from app.modules.validation import engine as V
from app.storage.backend import get_storage

log = logging.getLogger("pipeline")

STEP_DEFS = [
    ("intake", "Secure intake & SHA-256 hash"),
    ("preprocess", "Rectification & quality measurement"),
    ("quality_gate", "Capture quality gate"),
    ("ocr", "OCR & MRZ extraction"),
    ("validation", "Validation rules (ICAO 9303)"),
    ("forensics", "Image forensics (baseline)"),
    ("face", "Face verification (1:1)"),
    ("external", "External registry check"),
    ("risk", "Evidence aggregation & review priority"),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


class Steps:
    def __init__(self, db: Session, case: ScreeningCase):
        self.db, self.case = db, case
        self.rows = [{"key": k, "label": l, "status": "pending", "detail": "", "at": None} for k, l in STEP_DEFS]
        self._flush()

    def _flush(self):
        self.case.pipeline_steps = [dict(r) for r in self.rows]
        self.db.commit()

    def start(self, key: str):
        for r in self.rows:
            if r["key"] == key:
                r["status"], r["at"] = "running", _now()
        self._flush()

    def done(self, key: str, detail: str = "", status: str = "done"):
        for r in self.rows:
            if r["key"] == key:
                r["status"], r["detail"], r["at"] = status, detail, _now()
        self._flush()
        d = get_settings().demo_step_delay
        if d and status != "skipped":
            time.sleep(d)

    def skip(self, key: str, detail: str):
        self.done(key, detail, "skipped")


def _persist_checks(db: Session, case: ScreeningCase, doc: Document, checks: list[V.Check]):
    rv = V.rule_version()
    for c in checks:
        ev = dict(c.evidence or {})
        if c.group:
            ev["_group"] = c.group
        db.add(ValidationResult(case_id=case.id, document_id=doc.id, check_id=c.check_id, check_type=c.check_type,
                                dimension=c.dimension, title=c.title, status=c.status.value, message=c.message,
                                source=c.source, rule_version=rv, evidence_ref=ev or None))
    db.commit()


def _checks_from_rows(rows: list[ValidationResult]) -> list[V.Check]:
    out = []
    for r in rows:
        ev = dict(r.evidence_ref or {})
        out.append(V.Check(r.check_id, r.check_type, r.dimension, r.title, Status(r.status), r.message, r.source,
                           ev or None, ev.pop("_group", None) if ev else None))
    return out


# ------------------------------------------------------------------ field persistence / views
def effective_views(doc: Document) -> tuple[dict[str, V.FieldView], list[str], list[float], list[dict]]:
    viz: dict[str, V.FieldView] = {}
    mrz_lines = ["", ""]
    confs = [0.0, 0.0]
    for f in doc.fields:
        eff_raw = f.corrected_value if f.corrected_value is not None else f.raw_value
        if f.source == "VIZ":
            val = f.normalized_value
            if f.corrected_value is not None:
                val = ocr.normalise_viz(f.field_name, f.corrected_value)
            viz[f.field_name] = V.FieldView(f.field_name, eff_raw, val, 1.0 if f.corrected_value is not None else f.confidence,
                                            f.bounding_box, f.corrected_value is not None)
        elif f.field_name in ("mrz_line1", "mrz_line2"):
            i = 0 if f.field_name == "mrz_line1" else 1
            mrz_lines[i] = (f.corrected_value if f.corrected_value is not None else (f.normalized_value or f.raw_value)).upper().replace(" ", "")
            confs[i] = 1.0 if f.corrected_value is not None else f.confidence
    repairs = (doc.preprocessing or {}).get("mrz_repairs", [])
    if any(f.corrected_value is not None for f in doc.fields if f.field_name.startswith("mrz_line")):
        repairs = []
    return viz, mrz_lines, confs, repairs


def parse_effective_mrz(mrz_lines: list[str]):
    if not mrz_lines[0] and not mrz_lines[1]:
        return None
    if not mrz_lines[0].startswith("P") and not mrz_lines[1]:
        return None
    return parse_td3(mrz_lines[0], mrz_lines[1])


def text_checks(doc: Document, today: date | None = None) -> list[V.Check]:
    rules = V.load_rules()
    viz, lines, confs, repairs = effective_views(doc)
    mrz = parse_effective_mrz(lines)
    out = [V.template_check(mrz, rules)]
    out += V.mrz_checks(mrz, confs, repairs, rules)
    out += V.cross_checks(mrz, viz, rules)
    out += V.status_checks(mrz, viz, rules, today)
    return out


TEXT_CHECK_PREFIXES = ("mrz_", "xc_", "status_", "template_recognition", "viz_mrz_crosscheck")


def _status_and_summary(db: Session, case: ScreeningCase, doc: Document):
    """Aggregate current checks -> RiskAssessment + case status."""
    rows = db.execute(select(ValidationResult).where(ValidationResult.document_id == doc.id)).scalars().all()
    checks = _checks_from_rows(rows)
    quality_failed = any(c.dimension == V.QUALITY and c.status in (Status.FAIL, Status.INCONCLUSIVE) for c in checks)
    outcome = assess(checks, quality_failed)
    db.add(RiskAssessment(case_id=case.id, priority=outcome.priority,
                          dimensions={**outcome.dimensions, "_complete": outcome.complete},
                          reasons=outcome.reasons, unresolved=outcome.unresolved, policy_version=POLICY_VERSION))
    if quality_failed:
        case.status = CaseStatus.RECAPTURE_REQUIRED.value
    elif outcome.priority == "LOW" and outcome.complete:
        case.status = CaseStatus.COMPLETED.value
    else:
        case.status = CaseStatus.REVIEW_REQUIRED.value
    db.commit()
    return outcome


def recompute_after_correction(db: Session, case: ScreeningCase, doc: Document) -> dict:
    """Re-run text-derived checks after an officer correction; returns {check_id: (old, new)} changes."""
    db.refresh(doc)
    old = {r.check_id: r for r in db.execute(select(ValidationResult).where(
        ValidationResult.document_id == doc.id)).scalars().all() if r.check_id.startswith(TEXT_CHECK_PREFIXES)}
    old_status = {k: v.status for k, v in old.items()}
    for r in old.values():
        db.delete(r)
    db.commit()
    new_checks = text_checks(doc)
    _persist_checks(db, case, doc, new_checks)
    changes = {c.check_id: (old_status.get(c.check_id), c.status.value) for c in new_checks
               if old_status.get(c.check_id) != c.status.value}
    if case.status != CaseStatus.REVIEWED.value:
        _status_and_summary(db, case, doc)
    else:
        outcome = assess(_checks_from_rows(db.execute(select(ValidationResult).where(ValidationResult.document_id == doc.id)).scalars().all()))
        db.add(RiskAssessment(case_id=case.id, priority=outcome.priority, dimensions={**outcome.dimensions, "_complete": outcome.complete},
                              reasons=outcome.reasons, unresolved=outcome.unresolved, policy_version=POLICY_VERSION))
        db.commit()
    return changes


# ------------------------------------------------------------------ main pipeline
def run_pipeline(case_id: str) -> None:
    db = SessionLocal()
    try:
        _run(db, case_id)
    except Exception as e:  # pragma: no cover - defensive
        log.exception("pipeline failed")
        db.rollback()
        case = db.get(ScreeningCase, case_id)
        if case:
            case.status, case.failure_reason = CaseStatus.FAILED.value, f"Processing error: {type(e).__name__}: {e}"
            db.commit()
            log_event(db, "system", "pipeline.failed", case_id, metadata={"error": str(e)[:300]})
    finally:
        db.close()


def _run(db: Session, case_id: str) -> None:
    case = db.get(ScreeningCase, case_id)
    case.status, case.failure_reason = CaseStatus.PROCESSING.value, None
    db.commit()
    log_event(db, "system", "pipeline.started", case_id)
    rules = V.load_rules()
    storage = get_storage()
    doc = db.execute(select(Document).where(Document.case_id == case_id, Document.superseded == False)  # noqa: E712
                     .order_by(Document.capture_index.desc())).scalars().first()
    steps = Steps(db, case)

    steps.start("intake")
    data = storage.get(doc.storage_key)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("stored image could not be decoded")
    steps.done("intake", f"{doc.media_type}, {doc.width}x{doc.height}px, sha256 {doc.sha256[:12]}...")

    # ---- preprocessing + quality
    steps.start("preprocess")
    rect = locate_and_rectify(img)
    metrics = measure_quality(rect, rules)
    doc.quality = {"metrics": [asdict(m) for m in metrics]}
    doc.preprocessing = {"method": rect.method, "card_found": rect.card_found, "touches_border": rect.touches_border,
                         "angle_deg": round(rect.angle_deg, 2), "origin": rect.origin, "resampled": rect.resampled,
                         "quad": rect.quad, "notes": rect.notes, "template_id": T.TEMPLATE_ID,
                         "canonical_size": [T.CARD_W, T.CARD_H]}
    if rect.image is not None:
        ok, png = cv2.imencode(".png", rect.image)
        doc.rectified_key = storage.put(png.tobytes(), prefix="derived", ext="png")
    db.commit()
    steps.done("preprocess", f"method={rect.method}; {len(metrics)} quality measurements")

    quality_checks = [V.Check(f"quality_{m.name}", "quality", V.QUALITY, m.label, Status(m.status), m.message, "quality-assessment",
                              {"value": m.value, "unit": m.unit, "threshold": m.threshold}) for m in metrics]
    gate_failed = any(c.status in (Status.FAIL, Status.INCONCLUSIVE) for c in quality_checks)

    steps.start("quality_gate")
    if gate_failed:
        bad = [c.title for c in quality_checks if c.status in (Status.FAIL, Status.INCONCLUSIVE)]
        steps.done("quality_gate", "FAILED: " + "; ".join(bad) + ". Recapture requested.", "failed")
        placeholder_msg = "Not run: capture quality was insufficient. Recapture the document; no unreliable results were generated."
        skipped = [V.Check("mrz_checkdigits", "structure", V.CONSISTENCY, "MRZ check digits", Status.INCONCLUSIVE, placeholder_msg, "quality-gate"),
                   V.Check("viz_mrz_crosscheck", "consistency", V.CONSISTENCY, "Visual zone vs MRZ cross-check", Status.INCONCLUSIVE, placeholder_msg, "quality-gate"),
                   V.Check("status_expiry", "status", V.STATUS, "Document validity (expiry)", Status.INCONCLUSIVE, placeholder_msg, "quality-gate"),
                   V.Check("forensics_ela", "forensic", V.INTEGRITY, "Image integrity (ELA baseline)", Status.INCONCLUSIVE, placeholder_msg, "quality-gate"),
                   V.Check("face_comparison", "biometric", V.PERSON, "Face comparison (1:1)", Status.NOT_APPLICABLE, "No live capture in this demo.", "quality-gate"),
                   V.Check("registry_lookup", "external", V.STATUS, "External registry lookup", Status.INCONCLUSIVE, placeholder_msg, "quality-gate")]
        for k in ("ocr", "validation", "forensics", "face", "external"):
            steps.skip(k, "Skipped: quality gate failed")
        steps.start("risk")
        _persist_checks(db, case, doc, quality_checks + skipped)
        outcome = _status_and_summary(db, case, doc)
        steps.done("risk", "Recapture requested; no analysis results generated", "done")
        log_event(db, "system", "pipeline.completed", case_id, metadata={"status": case.status, "priority": outcome.priority, "gate": "failed"})
        return
    steps.done("quality_gate", "Passed" + ("; with warnings" if any(c.status == Status.REVIEW for c in quality_checks) else ""))

    # ---- OCR + MRZ
    steps.start("ocr")
    page = ocr.extract_page(rect.image)
    if not any(l.startswith("P") and len(l) > 20 for l in page.mrz_lines[:1]):
        rotated = rotate_180(rect)
        page2 = ocr.extract_page(rotated.image)
        if any(l.startswith("P") and len(l) > 20 for l in page2.mrz_lines[:1]):
            page = page2
            doc.preprocessing = {**doc.preprocessing, "notes": rect.notes}
            ok, png = cv2.imencode(".png", rotated.image)
            doc.rectified_key = storage.put(png.tobytes(), prefix="derived", ext="png")
        else:
            rotate_180(rect)  # revert
    l1, l2, repairs = correct_by_field_type(page.mrz_lines[0], page.mrz_lines[1])
    doc.preprocessing = {**doc.preprocessing, "mrz_repairs": repairs}
    ev = ocr.engine_version()
    for f in page.viz:
        db.add(ExtractedField(document_id=doc.id, field_name=f.name, source="VIZ", raw_value=f.raw, normalized_value=f.normalized,
                              confidence=round(f.confidence, 4), bounding_box=f.bbox, engine=ocr.ENGINE_NAME, engine_version=ev,
                              needs_review=f.confidence < rules["ocr"]["min_field_confidence"] or f.normalized is None))
    for i, (raw, norm, conf, box) in enumerate(zip(page.mrz_lines, (l1, l2), page.mrz_conf, page.mrz_boxes), start=1):
        db.add(ExtractedField(document_id=doc.id, field_name=f"mrz_line{i}", source="MRZ", raw_value=raw, normalized_value=norm,
                              confidence=round(conf, 4), bounding_box=box, engine=ocr.ENGINE_NAME, engine_version=ev,
                              needs_review=conf < rules["ocr"]["min_mrz_confidence"]))
    db.commit()
    db.refresh(doc)
    steps.done("ocr", f"{len(page.viz)} visual-zone fields, 2 MRZ lines; {len(repairs)} normalisation(s)")

    # ---- validation
    steps.start("validation")
    checks = text_checks(doc)
    _persist_checks(db, case, doc, quality_checks + checks)
    mrz = parse_effective_mrz(effective_views(doc)[1])
    if mrz and mrz.format_ok and mrz.document_code == "P":
        case.document_type = f"Passport (TD3) - {mrz.issuer}"
    n_fail = sum(c.status == Status.FAIL for c in checks)
    steps.done("validation", f"{len(checks)} checks; {n_fail} failed")

    # ---- forensics
    steps.start("forensics")
    fr = ela.analyze(img, rect.image, rect.origin, rect.resampled, rules)
    if fr.applicable:
        for z in fr.findings:
            db.add(ForensicFinding(document_id=doc.id, finding_type="ela_background_zone", zone=z.zone, status=z.status,
                                   confidence=z.score, score=z.z, region=z.box, message=z.message, model_version=fr.model_version))
        if fr.heatmap_png:
            doc.heatmap_key = storage.put(fr.heatmap_png, prefix="derived", ext="png")
        flagged = [z for z in fr.findings if z.status == "REVIEW"]
        if flagged:
            fc = V.Check("forensics_ela", "forensic", V.INTEGRITY, "Image integrity (ELA baseline)", Status.REVIEW,
                         "Review aid, not proof. Regions with an error-level profile that deviates from the template reference: " +
                         ", ".join(z.zone.replace("_", " ") for z in flagged) + ".", f"{fr.model_version}",
                         {"regions": [{"zone": z.zone, "box": z.box, "z": z.z} for z in flagged]}, group="forensics")
        else:
            fc = V.Check("forensics_ela", "forensic", V.INTEGRITY, "Image integrity (ELA baseline)", Status.PASS,
                         "No zone deviates from the template reference. This baseline cannot authenticate a document "
                         "(holograms, UV/IR and substrate are not assessable from an RGB image).", f"{fr.model_version}")
    else:
        fc = V.Check("forensics_ela", "forensic", V.INTEGRITY, "Image integrity (ELA baseline)", Status.INCONCLUSIVE, fr.reason,
                     f"{fr.model_version}")
    _persist_checks(db, case, doc, [fc])
    steps.done("forensics", fc.status.value + (f": {len([z for z in fr.findings if z.status == 'REVIEW'])} region(s) flagged" if fr.applicable else ": not applicable to this capture"))

    # ---- face (stub)
    steps.start("face")
    fo = get_verifier().verify(None, None)
    db.add(FaceCheck(case_id=case.id, quality_status=fo.quality_status.value, comparison_status=fo.comparison_status.value,
                     message=fo.message, model_version=fo.model_version))
    _persist_checks(db, case, doc, [V.Check("face_comparison", "biometric", V.PERSON, "Face comparison (1:1)", fo.comparison_status,
                                            fo.message, f"face-verifier {fo.model_version}")])
    steps.done("face", "Not applicable (no live capture / model in this demo)")

    # ---- external registry (stub)
    steps.start("external")
    num = None
    vf = effective_views(doc)[0].get("passport_number")
    if mrz and mrz.format_ok:
        num = mrz.passport_number
    elif vf:
        num = vf.value
    reg = get_registry().check(num, mrz.issuer if mrz else None, (case.demo_flags or {}).get("simulate_registry"))
    ev_ref = {"response_ref": reg.response_ref, "freshness": reg.freshness, "attempts": reg.attempts}
    _persist_checks(db, case, doc, [V.Check("registry_lookup", "external", V.STATUS, "External registry lookup", reg.status,
                                            reg.message, reg.source, ev_ref, group="registry")])
    steps.done("external", f"{reg.status.value} ({reg.attempts} attempt(s))")

    # ---- risk
    steps.start("risk")
    outcome = _status_and_summary(db, case, doc)
    steps.done("risk", f"Priority {outcome.priority}; {len(outcome.unresolved)} unresolved")
    log_event(db, "system", "pipeline.completed", case_id,
              metadata={"status": case.status, "priority": outcome.priority, "unresolved": len(outcome.unresolved)})
