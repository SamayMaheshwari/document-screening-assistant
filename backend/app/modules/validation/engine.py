"""Versioned, configurable validation rules (PDF 5.3).

Distinguishes: PASS / FAIL (deterministic rule failed) / REVIEW (needs human) /
INCONCLUSIVE (low quality or unreadable) / UNAVAILABLE (dependency down) / NOT_APPLICABLE.
A missing or unreadable input is NEVER converted into a fraud signal.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from app.core.config import get_settings
from app.core.enums import Status
from app.modules.classification import template as T
from app.modules.ocr_mrz.mrz import MRZResult

# dimensions (PDF 5.6: kept independent)
INTEGRITY = "document_integrity"
CONSISTENCY = "information_consistency"
STATUS = "document_status"
PERSON = "person_comparison"
QUALITY = "capture_quality"


@lru_cache
def load_rules() -> dict:
    return json.loads(get_settings().rules_file.read_text())


def rule_version(rules: dict | None = None) -> str:
    r = rules or load_rules()
    return f"{r['ruleset_id']}@{r['version']}"


@dataclass
class Check:
    check_id: str
    check_type: str
    dimension: str
    title: str
    status: Status
    message: str
    source: str = "rules-engine"
    evidence: dict | None = None
    group: str | None = None  # correlation group (findings with the same root cause count once)


@dataclass
class FieldView:
    """Effective value of an extracted field (officer correction overrides OCR)."""
    name: str
    raw: str
    value: str | None
    confidence: float
    bbox: list[int] | None
    corrected: bool = False


NATIONALITY_CODES = {"UTOPIAN": "UTO"}


def _norm_name(s: str) -> str:
    s = re.sub(r"[-'.]", " ", s.upper())
    return re.sub(r"\s+", " ", s).strip()


def _fmt(d: date | None) -> str:
    return d.isoformat() if d else "unreadable"


def mrz_checks(mrz: MRZResult | None, line_conf: list[float], repairs: list[dict], rules: dict) -> list[Check]:
    src = "mrz-icao9303-td3"
    if mrz is None:
        return [Check("mrz_structure", "structure", CONSISTENCY, "MRZ could be read", Status.REVIEW,
                      "No machine readable zone was detected on the page. Officer should examine the MRZ manually.", src,
                      {"region": list(T.MRZ_ZONE)}, group="mrz")]
    min_c = rules["ocr"]["min_mrz_confidence"]
    mrz_conf = min(line_conf) if line_conf else 0.0
    out: list[Check] = []
    ev_region = {"region": list(T.MRZ_ZONE)}
    if not mrz.format_ok:
        # structure problems can come from OCR errors: only deterministic when confidence is high
        st = Status.FAIL if mrz_conf >= min_c and not repairs else Status.REVIEW
        out.append(Check("mrz_structure", "structure", CONSISTENCY, "MRZ structure (TD3: 2 x 44 characters)", st,
                         " ".join(mrz.format_errors) + ("" if st == Status.FAIL else " OCR confidence/repairs mean this may be a reading error."),
                         src, ev_region, group="mrz_structure"))
        return out
    note = "; ".join(f"{c['expected']} ({c['from'] or '-'}->{c['to'] or '-'})" for c in repairs)
    out.append(Check("mrz_structure", "structure", CONSISTENCY, "MRZ structure (TD3: 2 x 44 characters)", Status.PASS,
                     "Both lines are 44 characters from the MRZ character set." + (f" OCR normalisations applied: {note}." if repairs else ""),
                     src, ev_region))
    labels = {"passport_number": "Passport number", "date_of_birth": "Date of birth",
              "date_of_expiry": "Date of expiry", "personal_number": "Personal number", "composite": "Composite (whole line)"}
    line2_repaired = any(r.get("line") == 2 and "filler" in r.get("expected", "") for r in repairs)
    for c in mrz.checks:
        cid = f"mrz_cd_{c.name}"
        title = f"Check digit - {labels[c.name]}"
        zone_box = [40 + 25 * (c.region[1] if c.region else 0) - 6, T.MRZ_LINE_ZONES[1][1], 38, T.MRZ_LINE_ZONES[1][3]]
        ev = {"region": zone_box, "printed": c.expected, "computed": c.computed, "data": c.data}
        if c.valid:
            out.append(Check(cid, "structure", CONSISTENCY, title, Status.PASS,
                             f"Printed digit {c.expected} matches the computed value {c.computed}.", src, ev))
        else:
            doubtful = mrz_conf < min_c or line2_repaired
            st = Status.REVIEW if doubtful else Status.FAIL
            msg = f"Printed digit {c.expected} but the ICAO 9303 algorithm computes {c.computed} for '{c.data}'."
            if doubtful:
                msg += " The MRZ was read with limited confidence, so this may be an OCR error; officer to verify against the image."
            out.append(Check(cid, "structure", CONSISTENCY, title, st, msg, src, ev, group="mrz_digits"))
    return out


def cross_checks(mrz: MRZResult | None, viz: dict[str, FieldView], rules: dict) -> list[Check]:
    src = "viz-vs-mrz"
    min_c = rules["ocr"]["min_field_confidence"]
    if mrz is None or not mrz.format_ok:
        return [Check("viz_mrz_crosscheck", "consistency", CONSISTENCY, "Visual zone vs MRZ cross-check", Status.INCONCLUSIVE,
                      "MRZ was not reliably read, so visual-zone fields cannot be cross-checked automatically.", src,
                      group="viz_mrz")]
    out: list[Check] = []

    def compare(cid, title, vname, viz_val, mrz_val, display_viz=None, display_mrz=None, eq=lambda a, b: a == b):
        f = viz.get(vname)
        ev = {"field": vname, "region": f.bbox if f else None, "viz": display_viz or viz_val, "mrz": display_mrz or mrz_val}
        if f is None or not f.raw.strip():
            out.append(Check(cid, "consistency", CONSISTENCY, title, Status.INCONCLUSIVE,
                             "The visual-zone field could not be read; officer may enter it manually.", src, ev))
            return
        if viz_val is None or mrz_val is None or mrz_val == "":
            out.append(Check(cid, "consistency", CONSISTENCY, title, Status.INCONCLUSIVE,
                             f"Could not interpret the value (read as '{f.raw}').", src, ev))
            return
        if eq(viz_val, mrz_val):
            out.append(Check(cid, "consistency", CONSISTENCY, title, Status.PASS,
                             f"Visual zone and MRZ agree ({display_mrz or mrz_val}).", src, ev))
        else:
            confident = f.confidence >= min_c or f.corrected
            st = Status.FAIL if confident else Status.REVIEW
            msg = f"Visual zone shows '{display_viz or viz_val}' but the MRZ encodes '{display_mrz or mrz_val}'."
            if not confident:
                msg += f" OCR confidence for this field is only {f.confidence:.0%}; may be a reading error."
            out.append(Check(cid, "consistency", CONSISTENCY, title, st, msg, src, ev, group=f"viz_mrz_{vname}"))

    def v(name):
        f = viz.get(name)
        return f.value if f else None

    compare("xc_surname", "Surname matches MRZ", "surname", _norm_name(v("surname") or "") or None, _norm_name(mrz.surname) or None,
            v("surname"), mrz.surname)
    mrz_given = _norm_name(mrz.given_names)
    compare("xc_given_names", "Given names match MRZ", "given_names", _norm_name(v("given_names") or "") or None, mrz_given or None,
            v("given_names"), mrz.given_names,
            eq=lambda a, b: a == b or (len(b) >= 30 and a.startswith(b)))  # MRZ names may be truncated
    compare("xc_dob", "Date of birth matches MRZ", "date_of_birth", v("date_of_birth"), mrz.birth_date.isoformat() if mrz.birth_date else None)
    compare("xc_expiry", "Date of expiry matches MRZ", "date_of_expiry", v("date_of_expiry"), mrz.expiry_date.isoformat() if mrz.expiry_date else None)
    compare("xc_number", "Passport number matches MRZ", "passport_number", v("passport_number"), re.sub(r"[^A-Z0-9]", "", mrz.passport_number))
    compare("xc_sex", "Sex matches MRZ", "sex", v("sex"), mrz.sex if mrz.sex != "<" else None)
    nat_viz = NATIONALITY_CODES.get((v("nationality") or "").upper(), v("nationality"))
    compare("xc_nationality", "Nationality matches MRZ", "nationality", nat_viz, mrz.nationality,
            v("nationality"), mrz.nationality)
    compare("xc_issuer", "Issuing State code matches MRZ", "issuer_code", v("issuer_code"), mrz.issuer)
    return out


def status_checks(mrz: MRZResult | None, viz: dict[str, FieldView], rules: dict, today: date | None = None) -> list[Check]:
    today = today or date.today()
    src = f"date-rules {rule_version(rules)}"
    exp = mrz.expiry_date if mrz and mrz.format_ok else None
    dob = mrz.birth_date if mrz and mrz.format_ok else None

    def viz_date(name):
        f = viz.get(name)
        if f and f.value:
            try:
                return date.fromisoformat(f.value)
            except ValueError:
                return None
        return None

    issued = viz_date("date_of_issue")
    out: list[Check] = []

    if exp is None:
        out.append(Check("status_expiry", "status", STATUS, "Document validity (expiry)", Status.INCONCLUSIVE,
                         "Expiry date could not be determined from a readable MRZ.", src, group="status"))
    elif exp < today:
        out.append(Check("status_expiry", "status", STATUS, "Document validity (expiry)", Status.FAIL,
                         f"EXPIRED: the document expired on {exp.isoformat()} ({(today - exp).days} days ago). "
                         "This is a status finding, not evidence of forgery.", src,
                         {"reason_code": "EXPIRED", "field": "date_of_expiry", "region": (viz.get("date_of_expiry").bbox if viz.get("date_of_expiry") else None)},
                         group="status"))
    elif (exp - today).days < rules["min_validity_days"]:
        out.append(Check("status_expiry", "status", STATUS, "Document validity (expiry)", Status.REVIEW,
                         f"Expires in {(exp - today).days} days (ruleset minimum remaining validity: {rules['min_validity_days']} days).",
                         src, {"reason_code": "EXPIRING_SOON"}, group="status"))
    else:
        out.append(Check("status_expiry", "status", STATUS, "Document validity (expiry)", Status.PASS,
                         f"Valid until {exp.isoformat()} ({(exp - today).days} days remaining).", src))

    if dob is None:
        out.append(Check("status_dob", "status", STATUS, "Date of birth plausibility", Status.INCONCLUSIVE,
                         "Date of birth could not be determined from a readable MRZ.", src))
    else:
        age = (today - dob).days / 365.25
        if dob > today or age > rules["max_age_years"]:
            out.append(Check("status_dob", "status", STATUS, "Date of birth plausibility", Status.FAIL,
                             f"Date of birth {dob.isoformat()} is implausible (age {age:.0f}).", src, {"reason_code": "INVALID_DATE"}))
        else:
            out.append(Check("status_dob", "status", STATUS, "Date of birth plausibility", Status.PASS,
                             f"Holder age at screening: {age:.0f} years.", src))

    if issued is None or exp is None:
        out.append(Check("status_issue_window", "status", STATUS, "Issue-to-expiry window", Status.INCONCLUSIVE,
                         "Issue and/or expiry date unreadable; window not evaluated.", src))
    else:
        yrs = (exp - issued).days / 365.25
        if issued > today:
            out.append(Check("status_issue_window", "status", STATUS, "Issue-to-expiry window", Status.FAIL,
                             f"Issue date {issued.isoformat()} is in the future.", src, {"reason_code": "INVALID_DATE"}))
        elif exp <= issued:
            out.append(Check("status_issue_window", "status", STATUS, "Issue-to-expiry window", Status.FAIL,
                             "Expiry date is not after the issue date.", src, {"reason_code": "INVALID_DATE"}))
        elif yrs > rules["max_validity_years"] + 0.02:
            out.append(Check("status_issue_window", "status", STATUS, "Issue-to-expiry window", Status.REVIEW,
                             f"Validity of {yrs:.1f} years exceeds the ruleset maximum of {rules['max_validity_years']} years.", src))
        elif dob and issued < dob:
            out.append(Check("status_issue_window", "status", STATUS, "Issue-to-expiry window", Status.FAIL,
                             "Issue date precedes the date of birth.", src, {"reason_code": "INVALID_DATE"}))
        else:
            out.append(Check("status_issue_window", "status", STATUS, "Issue-to-expiry window", Status.PASS,
                             f"Issued {issued.isoformat()}, valid for {yrs:.1f} years (max {rules['max_validity_years']}).", src))
    return out


def template_check(mrz: MRZResult | None, rules: dict) -> Check:
    if mrz is None or not mrz.format_ok:
        return Check("template_recognition", "structure", INTEGRITY, "Document type / template recognised", Status.INCONCLUSIVE,
                     "Could not read the MRZ to confirm issuing State and document code.", "classifier-rules", group="template")
    if mrz.document_code == "P" and mrz.issuer == rules["issuer_code"]:
        return Check("template_recognition", "structure", INTEGRITY, "Document type / template recognised", Status.PASS,
                     f"Passport (P), issuing State {mrz.issuer}; template {rules['template_id']}.", "classifier-rules")
    return Check("template_recognition", "structure", INTEGRITY, "Document type / template recognised", Status.NOT_APPLICABLE,
                 f"Issuing State '{mrz.issuer}' / code '{mrz.document_code}' is outside the supported demo ruleset ({rules['issuer_code']} TD3).",
                 "classifier-rules")
