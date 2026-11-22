"""Evaluation harness: runs the REAL pipeline functions directly (no HTTP, no database) on the TEST split.

    python model-work/evaluation/evaluate.py                         # data/synthetic_dataset
    python model-work/evaluation/evaluate.py --dataset D:/company/passports
    IDS_EVAL_DATASET=... python model-work/evaluation/evaluate.py

Outputs (schema documented at the top of REPORT.md):
    data/evaluation/results.json        machine readable, rendered by the app's evaluation page (GET /api/v1/evaluation)
    model-work/evaluation/REPORT.md     human readable report

Pipeline functions used: rectify.locate_and_rectify / measure_quality, ocr.extract_page, mrz.correct_by_field_type /
parse_td3, validation.engine checks, forensics.ela.analyze, risk.engine.assess. Nothing is tuned on the test split.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE.parent))
os.environ.setdefault("IDS_DEMO_STEP_DELAY", "0")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from app.core.enums import Status  # noqa: E402
from app.modules.classification import template as T  # noqa: E402
from app.modules.forensics import ela  # noqa: E402
from app.modules.ocr_mrz import extract as ocr  # noqa: E402
from app.modules.ocr_mrz.mrz import correct_by_field_type, parse_td3  # noqa: E402
from app.modules.preprocessing.rectify import locate_and_rectify, measure_quality, rotate_180  # noqa: E402
from app.modules.risk.engine import POLICY_VERSION, assess  # noqa: E402
from app.modules.validation import engine as V  # noqa: E402
from evaluation.dataset import Doc, DatasetError, load_dataset  # noqa: E402
from evaluation.split import check_no_leak, connected_groups, group_split  # noqa: E402

N_BOOT = 2000
BOOT_SEED = 20260101
GATE_POSITIVE_VARIANTS = {"blurry", "glare", "cropped", "low_res"}
CLEAN_VARIANTS = {"clean", "registry_unavailable"}
MISMATCH_CHECK = {"edited_name": "xc_surname", "edited_dob": "xc_dob", "viz_mrz_mismatch": "xc_number"}
VIZ_OVERRIDES = {"surname_viz_edited": "surname", "dob_viz_edited": "date_of_birth", "number_viz_edited": "passport_number"}
EXPECTED_PRIORITY = {  # what the documented design says should happen (see VARIANTS[...]['expect'])
    "clean": "LOW", "registry_unavailable": "LOW", "rotated": "LOW", "bad_check_digit": "HIGH", "edited_name": "HIGH",
    "edited_dob": "HIGH", "viz_mrz_mismatch": "HIGH", "portrait_swap": "MEDIUM", "stamp_edit": "MEDIUM",
    "expired": "MEDIUM", "blurry": "INCOMPLETE", "glare": "INCOMPLETE", "cropped": "INCOMPLETE", "low_res": "INCOMPLETE",
}


# ---------------------------------------------------------------------------------------------- helpers
def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def mrz_cer(pred: list[str], truth: list[str]) -> float:
    denom = sum(len(t) for t in truth)
    return sum(levenshtein(p, t) for p, t in zip(pred, truth)) / denom if denom else 0.0


def iou(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


_RECS: dict[str, list] = {}


def bind(recs: list, *ids: str) -> None:
    """Tell ratio_metric which records (hence which persons) the per-document arrays of these metric ids are aligned with."""
    for i in ids:
        _RECS[i] = recs


def ratio_metric(mid: str, label: str, num, den, unit: str = "fraction", note: str = "", counts: dict | None = None,
                 n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> dict:
    """value = sum(num)/sum(den). 95% CI = percentile CLUSTER bootstrap: persons (all documents of one holder) are
    resampled with replacement, because variants of one person are strongly correlated. Falls back to a document
    bootstrap when no person ids are bound to the metric."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    n = len(num)
    out = {"id": mid, "label": label, "value": None, "ci": None, "n": int(n), "unit": unit, "note": note}
    if counts:
        out["counts"] = counts
    if n == 0 or den.sum() == 0:
        return out
    out["value"] = round(float(num.sum() / den.sum()), 4)
    recs = _RECS.get(mid)
    if recs is not None and len(recs) == n:
        pid = [r["person_id"] for r in recs]
        uniq = {p: i for i, p in enumerate(dict.fromkeys(pid))}
        cl = np.array([uniq[p] for p in pid])
        k = len(uniq)
        cn, cd = np.zeros(k), np.zeros(k)
        np.add.at(cn, cl, num)
        np.add.at(cd, cl, den)
        num_u, den_u = cn, cd
        out["n_clusters"] = int(k)
    else:
        num_u, den_u, k = num, den, n
    rng = np.random.default_rng([seed, zlib.crc32(mid.encode())])
    idx = rng.integers(0, k, size=(n_boot, k))
    d = den_u[idx].sum(axis=1)
    ok = d > 0
    vals = num_u[idx].sum(axis=1)[ok] / d[ok]
    if len(vals) >= 20:
        out["ci"] = [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]
    return out


def rate_metric(mid, label, flags, **kw) -> dict:
    flags = [1.0 if f else 0.0 for f in flags]
    return ratio_metric(mid, label, flags, [1.0] * len(flags), **kw)


# ---------------------------------------------------------------------------------------------- one document
def expected_viz(doc: Doc) -> dict[str, str]:
    exp = {k: str(v) for k, v in doc.ground_truth.items() if k in T.FIELD_ZONES}
    for key, field in VIZ_OVERRIDES.items():  # the image shows the EDITED value in these fields
        if key in doc.ground_truth:
            exp[field] = str(doc.ground_truth[key])
    return {k: ocr.normalise_viz(k, v) for k, v in exp.items()}


def run_document(doc: Doc, rules: dict, today: date) -> dict:
    data = doc.read_bytes()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    rec: dict = {"doc_id": doc.doc_id, "person_id": doc.person_id, "variant": doc.variant, "decode_ok": img is not None}
    if img is None:
        raise ValueError(f"cannot decode {doc.image_path}")
    rect = locate_and_rectify(img)
    metrics = measure_quality(rect, rules)
    qchecks = [V.Check(f"quality_{m.name}", "quality", V.QUALITY, m.label, Status(m.status), m.message) for m in metrics]
    bad = [c.check_id for c in qchecks if c.status in (Status.FAIL, Status.INCONCLUSIVE)]
    rec.update(gate_failed=bool(bad), gate_reasons=bad, rect_method=rect.method, resampled=rect.resampled)
    checks = list(qchecks)
    if bad:  # same placeholders as the pipeline
        for cid, dim in (("mrz_checkdigits", V.CONSISTENCY), ("viz_mrz_crosscheck", V.CONSISTENCY), ("status_expiry", V.STATUS),
                         ("forensics_ela", V.INTEGRITY), ("registry_lookup", V.STATUS)):
            checks.append(V.Check(cid, "x", dim, cid, Status.INCONCLUSIVE, "quality gate failed"))
        outcome = assess(checks, True)
        rec.update(priority=outcome.priority, case_status="RECAPTURE_REQUIRED", ocr_ran=False, ela_applicable=None)
        return rec

    # ---- OCR (same logic as pipeline._run)
    page = ocr.extract_page(rect.image)
    if not any(l.startswith("P") and len(l) > 20 for l in page.mrz_lines[:1]):
        rotated = rotate_180(rect)
        page2 = ocr.extract_page(rotated.image)
        if any(l.startswith("P") and len(l) > 20 for l in page2.mrz_lines[:1]):
            page = page2
        else:
            rotate_180(rect)
    l1, l2, repairs = correct_by_field_type(page.mrz_lines[0], page.mrz_lines[1])
    rec["ocr_ran"] = True
    exp = expected_viz(doc)
    got = {f.name: f.normalized for f in page.viz}
    rec["viz"] = {k: {"expected": e, "got": got.get(k), "raw": next((f.raw for f in page.viz if f.name == k), None),
                      "match": got.get(k) == e} for k, e in exp.items()}
    if len(doc.mrz) == 2:
        rec["mrz"] = {"truth": doc.mrz, "raw": page.mrz_lines, "corrected": [l1, l2],
                      "cer_raw": mrz_cer(page.mrz_lines, doc.mrz), "cer_corrected": mrz_cer([l1, l2], doc.mrz),
                      "exact_corrected": [l1, l2] == doc.mrz}
    # ---- validation
    mrz = None if (not l1 and not l2) or (not l1.startswith("P") and not l2) else parse_td3(l1, l2)
    rec["mrz_format_ok"] = bool(mrz and mrz.format_ok)
    viz = {f.name: V.FieldView(f.name, f.raw, f.normalized, f.confidence, f.bbox) for f in page.viz}
    vchecks = [V.template_check(mrz, rules)] + V.mrz_checks(mrz, page.mrz_conf, repairs, rules) + \
        V.cross_checks(mrz, viz, rules) + V.status_checks(mrz, viz, rules, today)
    checks += vchecks
    rec["checks"] = {c.check_id: c.status.value for c in vchecks}
    # ---- forensics (as pipeline)
    fr = ela.analyze(img, rect.image, rect.origin, rect.resampled, rules)
    rec["ela_applicable"] = fr.applicable
    flagged = [z for z in fr.findings if z.status == "REVIEW"] if fr.applicable else []
    rec["ela_flagged"] = [z.zone for z in flagged]
    rec["ela_reason"] = None if fr.applicable else fr.reason
    if fr.applicable and flagged:
        checks.append(V.Check("forensics_ela", "forensic", V.INTEGRITY, "ELA", Status.REVIEW, "flagged", group="forensics"))
    elif fr.applicable:
        checks.append(V.Check("forensics_ela", "forensic", V.INTEGRITY, "ELA", Status.PASS, "ok"))
    else:
        checks.append(V.Check("forensics_ela", "forensic", V.INTEGRITY, "ELA", Status.INCONCLUSIVE, fr.reason))
    checks.append(V.Check("face_comparison", "biometric", V.PERSON, "face", Status.NOT_APPLICABLE, "n/a"))
    reg = Status.UNAVAILABLE if doc.variant == "registry_unavailable" else Status.PASS  # simulated, like the demo flag
    checks.append(V.Check("registry_lookup", "external", V.STATUS, "registry", reg, "simulated", group="registry"))
    outcome = assess(checks, False)
    rec["priority"] = outcome.priority
    rec["complete"] = outcome.complete
    rec["case_status"] = "COMPLETED" if outcome.priority == "LOW" and outcome.complete else "REVIEW_REQUIRED"
    return rec


# ---------------------------------------------------------------------------------------------- metrics
def compute_metrics(docs: list[Doc], recs: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    by_id = {d.doc_id: d for d in docs}
    R = recs
    passed = [r for r in R if r["ocr_ran"]]
    fails: list[dict] = []

    def fail(cat, r, expected, got, note=""):
        fails.append({"doc_id": r["doc_id"], "person_id": r["person_id"], "variant": r["variant"], "category": cat, "expected": expected, "got": got, "note": note})

    # ---------------- OCR
    ocr_m = []
    fields = list(T.FIELD_ZONES)
    per_field = {f: [] for f in fields}
    per_field_recs = {f: [] for f in fields}
    per_doc_mean, pd_recs = [], []
    for r in passed:
        ms = []
        for f in fields:
            v = r["viz"].get(f)
            if v is None:
                continue
            per_field[f].append(1.0 if v["match"] else 0.0)
            per_field_recs[f].append(r)
            ms.append(1.0 if v["match"] else 0.0)
            if not v["match"]:
                fail("viz_ocr", r, f"{f} = {v['expected']!r}", f"{v['got']!r}", f"raw OCR text {v['raw']!r}")
        if ms:
            per_doc_mean.append(sum(ms) / len(ms))
            pd_recs.append(r)
    note = ("Normalised value (the one validation uses) must equal ground truth exactly. Evaluated on captures that passed "
            "the quality gate; for tampered fields the EDITED text shown in the image is the target.")
    for f in fields:
        bind(per_field_recs[f], f"viz_exact_{f}")
        ocr_m.append(rate_metric(f"viz_exact_{f}", f"VIZ exact match - {f}", per_field[f], note=note if f == fields[0] else ""))
    bind(pd_recs, "viz_exact_mean")
    ocr_m.insert(0, ratio_metric("viz_exact_mean", "VIZ exact match - mean over fields (per document)", per_doc_mean,
                                 [1.0] * len(per_doc_mean), note=note))
    mr = [r for r in passed if "mrz" in r]
    bind(mr, "mrz_cer_raw", "mrz_cer_normalised", "mrz_exact_line_match")
    bind(passed, "mrz_parse_success", "ela_not_applicable_fraction")
    ocr_m.append(ratio_metric("mrz_cer_raw", "MRZ character error rate - raw OCR output (lower is better)",
                              [r["mrz"]["cer_raw"] for r in mr], [1.0] * len(mr),
                              note="Mean of per-document CER = edit distance / reference characters over both lines."))
    ocr_m.append(ratio_metric("mrz_cer_normalised", "MRZ character error rate - after look-alike/filler normalisation (lower is better)",
                              [r["mrz"]["cer_corrected"] for r in mr], [1.0] * len(mr)))
    ocr_m.append(rate_metric("mrz_exact_line_match", "MRZ both lines exactly right after normalisation", [r["mrz"]["exact_corrected"] for r in mr]))
    ocr_m.append(rate_metric("mrz_parse_success", "MRZ parse success (44x2 characters, valid charset, code 'P')", [r["mrz_format_ok"] for r in passed],
                             note="Structure only; says nothing about whether the digits are right."))
    for r in mr:
        if not r["mrz"]["exact_corrected"]:
            m = r["mrz"]
            diff = [(i, a, b) for line in range(2) for i, (a, b) in enumerate(zip(m["corrected"][line], m["truth"][line])) if a != b][:6]
            fail("mrz_ocr", r, "|".join(m["truth"]), "|".join(m["corrected"]),
                 f"CER {m['cer_corrected']:.3f}; first diffs (pos, got, want): {diff}")

    # ---------------- validation
    val_m = []
    bcd = [r for r in passed if r["variant"] == "bad_check_digit"]
    clean = [r for r in passed if r["variant"] in CLEAN_VARIANTS]

    mism = [r for r in passed if r["variant"] in MISMATCH_CHECK]
    clean_all = [r for r in R if r["variant"] in CLEAN_VARIANTS]
    expired = [r for r in passed if r["variant"] == "expired"]
    bind(bcd, "check_digit_detection_recall", "check_digit_detection_recall_flagged")
    bind(clean, "check_digit_false_fail_rate_clean", "check_digit_false_alert_rate_clean", "viz_mrz_false_fail_rate_clean")
    bind(mism, "viz_mrz_mismatch_detection_recall", "viz_mrz_mismatch_detection_recall_flagged")
    bind(clean_all, "clean_case_false_escalation_rate")
    bind(expired, "expired_detection_recall")
    bind(R, "recapture_precision", "recapture_recall", "recapture_f1")

    def cd_status(r):
        return [s for k, s in r["checks"].items() if k.startswith("mrz_cd_")]
    val_m.append(rate_metric("check_digit_detection_recall", "Check-digit error detection recall (deterministic FAIL on a mrz_cd_* check)",
                             ["FAIL" in cd_status(r) for r in bcd], note="Positives: variant bad_check_digit that passed the quality gate."))
    val_m.append(rate_metric("check_digit_detection_recall_flagged", "Check-digit error surfaced to the officer (FAIL or REVIEW)",
                             [("FAIL" in cd_status(r)) or ("REVIEW" in cd_status(r)) for r in bcd]))
    val_m.append(rate_metric("check_digit_false_fail_rate_clean", "Check-digit false FAIL rate on clean documents (lower is better)",
                             ["FAIL" in cd_status(r) for r in clean], note="Negatives: variants clean and registry_unavailable (identical imagery)."))
    val_m.append(rate_metric("check_digit_false_alert_rate_clean", "Check-digit false alert rate (FAIL or REVIEW) on clean documents (lower is better)",
                             [("FAIL" in cd_status(r)) or ("REVIEW" in cd_status(r)) for r in clean]))
    for r in bcd:
        if "FAIL" not in cd_status(r):
            fail("check_digit_miss", r, "an mrz_cd_* check FAIL", ",".join(cd_status(r)), "planted check-digit error not flagged as FAIL")
    for r in clean:
        if "FAIL" in cd_status(r) or "REVIEW" in cd_status(r):
            bad = {k: s for k, s in r["checks"].items() if k.startswith("mrz_") and s in ("FAIL", "REVIEW")}
            fail("check_digit_false_alert", r, "all mrz checks PASS", str(bad), "false alert on a clean document")
    mism = [r for r in passed if r["variant"] in MISMATCH_CHECK]
    val_m.append(rate_metric("viz_mrz_mismatch_detection_recall", "VIZ/MRZ mismatch detection recall (FAIL on the edited field's cross-check)",
                             [r["checks"].get(MISMATCH_CHECK[r["variant"]]) == "FAIL" for r in mism],
                             note="Positives: edited_name -> xc_surname, edited_dob -> xc_dob, viz_mrz_mismatch -> xc_number."))
    val_m.append(rate_metric("viz_mrz_mismatch_detection_recall_flagged", "VIZ/MRZ mismatch surfaced (FAIL or REVIEW)",
                             [r["checks"].get(MISMATCH_CHECK[r["variant"]]) in ("FAIL", "REVIEW") for r in mism]))
    val_m.append(rate_metric("viz_mrz_false_fail_rate_clean", "VIZ/MRZ cross-check false FAIL rate on clean documents, any field (lower is better)",
                             [any(s == "FAIL" for k, s in r["checks"].items() if k.startswith("xc_")) for r in clean]))
    for r in mism:
        st = r["checks"].get(MISMATCH_CHECK[r["variant"]])
        if st != "FAIL":
            fail("mismatch_miss", r, f"{MISMATCH_CHECK[r['variant']]} FAIL", str(st), "edited VIZ field not caught as a mismatch")
    for r in clean:
        xf = {k: s for k, s in r["checks"].items() if k.startswith("xc_") and s == "FAIL"}
        if xf:
            fail("mismatch_false_fail", r, "all xc_* checks PASS", str(xf), "false VIZ/MRZ mismatch on a clean document")
    clean_all = [r for r in R if r["variant"] in CLEAN_VARIANTS]
    val_m.append(rate_metric("clean_case_false_escalation_rate", "Clean documents ending at MEDIUM/HIGH/INCOMPLETE priority (lower is better)",
                             [r["priority"] != "LOW" for r in clean_all],
                             note="End-to-end: rules + forensics + risk engine, registry simulated as available."))
    expired = [r for r in passed if r["variant"] == "expired"]
    val_m.append(rate_metric("expired_detection_recall", "Expired-document detection recall (status_expiry FAIL)",
                             [r["checks"].get("status_expiry") == "FAIL" for r in expired]))

    # ---------------- quality gate
    qg = []
    pos = np.array([1.0 if r["variant"] in GATE_POSITIVE_VARIANTS else 0.0 for r in R])
    pred = np.array([1.0 if r["gate_failed"] else 0.0 for r in R])
    tp, fp, fn = pos * pred, (1 - pos) * pred, pos * (1 - pred)
    qg.append(ratio_metric("recapture_precision", "Recapture request precision", tp, tp + fp,
                           note="Positives: blurry, glare, cropped, low_res. Prediction: quality gate fails.",
                           counts={"tp": int(tp.sum()), "fp": int(fp.sum()), "fn": int(fn.sum())}))
    qg.append(ratio_metric("recapture_recall", "Recapture request recall", tp, tp + fn))
    qg.append(ratio_metric("recapture_f1", "Recapture request F1", 2 * tp, 2 * tp + fp + fn))
    for r in R:
        is_pos = r["variant"] in GATE_POSITIVE_VARIANTS
        if is_pos and not r["gate_failed"]:
            fail("gate_miss", r, "quality gate fails", "gate passed", "degraded capture not sent for recapture")
        if not is_pos and r["gate_failed"]:
            fail("gate_false_alarm", r, "quality gate passes", "FAILED: " + ",".join(r["gate_reasons"]), "good capture rejected")

    # ---------------- forensics
    fo = []
    app_docs = [r for r in passed if r.get("ela_applicable")]
    tps, fps, fns, ious, ntruth = [], [], [], [], []
    for r in app_docs:
        d = by_id[r["doc_id"]]
        truth = {t["zone"]: t["box"] for t in d.tamper_regions if t.get("zone") in T.FORENSIC_ZONES}
        flagged = set(r["ela_flagged"])
        hit = flagged & set(truth)
        tps.append(len(hit))
        fps.append(len(flagged - set(truth)))
        fns.append(len(set(truth) - flagged))
        ious.append(sum(iou(truth[z], T.FORENSIC_ZONES[z]) for z in hit))
        ntruth.append(len(truth))
        for z in sorted(set(truth) - flagged):
            fail("forensic_fn", r, f"region '{z}' flagged", "not flagged", "tampered region missed by ELA baseline")
        for z in sorted(flagged - set(truth)):
            fail("forensic_fp", r, "no flag", f"region '{z}' flagged", "ELA flag on an untampered region")
    tps, fps, fns, ious, ntruth = map(np.array, (tps, fps, fns, ious, ntruth))
    tamp_docs = [r for r in app_docs if by_id[r["doc_id"]].tamper_regions]
    cl_app = [r for r in app_docs if r["variant"] in CLEAN_VARIANTS]
    bind(app_docs, "region_precision", "region_recall", "region_f1", "localisation_iou_detected", "localisation_iou_all")
    bind(tamp_docs, "document_tamper_detection_recall")
    bind(cl_app, "document_false_alert_rate_clean")
    cnt = {"tp": int(tps.sum()) if len(tps) else 0, "fp": int(fps.sum()) if len(fps) else 0, "fn": int(fns.sum()) if len(fns) else 0}
    fo.append(ratio_metric("region_precision", "Forensic region precision", tps, tps + fps, counts=cnt,
                           note="Region = one of the 8 template forensic zones; unit of analysis is (document, zone). "
                                "Only captures where ELA is applicable (unresampled, calibrated template) are scored."))
    fo.append(ratio_metric("region_recall", "Forensic region recall", tps, tps + fns))
    fo.append(ratio_metric("region_f1", "Forensic region F1", 2 * tps, 2 * tps + fps + fns))
    fo.append(ratio_metric("localisation_iou_detected", "Localisation IoU (mean over detected tampered regions)", ious, tps,
                           unit="ratio", note="IoU between the tamper_regions box and the flagged template zone box; ELA only "
                                              "localises to whole template zones, and the forensic zones coincide with the template field boxes the "
                                              "generator edits, so this IoU is near 1 BY CONSTRUCTION - it is not evidence of pixel-level localisation."))
    fo.append(ratio_metric("localisation_iou_all", "Localisation IoU (all tampered regions, misses count as 0)", ious, ntruth, unit="ratio"))
    tamp_docs = [r for r in app_docs if by_id[r["doc_id"]].tamper_regions]
    fo.append(rate_metric("document_tamper_detection_recall", "Tampered documents with at least one correct region flagged",
                          [bool(set(r["ela_flagged"]) & {t["zone"] for t in by_id[r["doc_id"]].tamper_regions}) for r in tamp_docs]))
    cl_app = [r for r in app_docs if r["variant"] in CLEAN_VARIANTS]
    fo.append(rate_metric("document_false_alert_rate_clean", "Clean documents with any ELA region flagged (lower is better)",
                          [bool(r["ela_flagged"]) for r in cl_app]))
    fo.append(rate_metric("ela_not_applicable_fraction", "Quality-passed captures where ELA is not applicable (resampled / rotated / uncalibrated)",
                          [not r["ela_applicable"] for r in passed],
                          note="Not applicable is reported as INCONCLUSIVE by the app, never as a fraud signal."))

    # ---------------- per variant
    rows = []
    for v in sorted({r["variant"] for r in R}):
        rv = [r for r in R if r["variant"] == v]
        pv = [r for r in rv if r["ocr_ran"]]
        pri = Counter(r["priority"] for r in rv)
        exp_p = EXPECTED_PRIORITY.get(v)
        accs = [sum(x["match"] for x in r["viz"].values()) / len(r["viz"]) for r in pv if r.get("viz")]
        cers = [r["mrz"]["cer_corrected"] for r in pv if "mrz" in r]
        rows.append({
            "variant": v, "n": len(rv), "expected_priority": exp_p,
            "priority_match_rate": round(sum(r["priority"] == exp_p for r in rv) / len(rv), 3) if exp_p else None,
            "n_low": pri.get("LOW", 0), "n_medium": pri.get("MEDIUM", 0), "n_high": pri.get("HIGH", 0), "n_incomplete": pri.get("INCOMPLETE", 0),
            "quality_gate_failed": sum(r["gate_failed"] for r in rv),
            "ela_not_applicable": sum(1 for r in pv if not r.get("ela_applicable")),
            "ela_region_flagged": sum(1 for r in pv if r.get("ela_flagged")),
            "mean_mrz_cer": round(float(np.mean(cers)), 4) if cers else None,
            "viz_field_accuracy": round(float(np.mean(accs)), 4) if accs else None})
        if exp_p:
            for r in rv:
                if r["priority"] != exp_p:
                    fail("priority", r, f"priority {exp_p}", f"priority {r['priority']}", "end-to-end outcome differs from the design intent")
    return {"ocr": ocr_m, "validation": val_m, "quality_gate": qg, "forensics": fo}, rows, fails


def pick_failures(fails: list[dict], k: int = 15) -> list[dict]:
    """Round-robin over categories; within a category one case per person first (variants of one holder fail
    identically and would otherwise crowd the list), then the remaining duplicates if there is still room."""
    order = ["gate_miss", "gate_false_alarm", "check_digit_miss", "check_digit_false_alert", "mismatch_miss", "mismatch_false_fail",
             "forensic_fn", "forensic_fp", "mrz_ocr", "viz_ocr", "priority"]
    cats: dict[str, list[dict]] = defaultdict(list)
    for f in fails:
        cats[f["category"]].append(f)
    names = [c for c in order if c in cats] + [c for c in cats if c not in order]
    queues = {}
    for c in names:
        first, rest, seen = [], [], set()
        for f in cats[c]:
            (rest if f["person_id"] in seen else first).append(f)
            seen.add(f["person_id"])
        queues[c] = first + rest
    out: list[dict] = []
    while len(out) < k and any(queues.values()):
        for c in names:
            if queues[c] and len(out) < k:
                out.append(queues[c].pop(0))
    return [{"doc_id": f["doc_id"], "variant": f["variant"], "category": f["category"], "expected": f["expected"], "got": f["got"],
             "note": f["note"]} for f in out]


LIMITATIONS = [
    "Synthetic data only: fictional people, one invented template (UTO-TD3-v1), one font family, clean rendering. Results say nothing about real passports, other layouts, languages or scripts.",
    "Test documents come from the same generator as the rules/thresholds were designed against; thresholds were calibrated on seeds 5000-5079 (forensics) and are NOT tuned on this split, but the distribution is identical, so these numbers are optimistic for real-world use.",
    "Small test split: many confidence intervals are wide. Per-variant counts are in per_variant; a CI of [0, 1] means the sample cannot support a conclusion.",
    "Splitting is by connected group (person / template / session), so near-duplicate variants of one source never cross the split; the split is not stratified by variant.",
    "The ELA baseline localises only to template zones (not pixels) and only on unresampled captures; resampled/rotated captures are reported as not applicable. It is a review aid, not proof of tampering, and cannot detect re-saves, screenshots or well-matched forgeries.",
    "Localisation IoU is inflated by construction: forensic zones are the same template boxes the generator edits. Real tampering will rarely align with predefined zones.",
    "Tamper operations are simple (text redraw, portrait paste, stamp redraw) with a deliberate foreign JPEG history; real forgers can avoid such traces.",
    "No demographic or subgroup coverage: avatars are illustrations and names/dates are drawn from small fixed lists, so no fairness or subgroup analysis is possible.",
    "Face verification, ePassport chip/PKD checks and live registry lookups are out of scope (registry is simulated); quality-gate thresholds are fixed rules, not learned.",
    "Quality-gate positives are the four degradation variants at one severity each; marginal captures (mild blur, partial glare) are not represented.",
]


# ---------------------------------------------------------------------------------------------- report
SCHEMA_MD = """## results.json schema (flat, UI-ready)

```
{
  "generated_at": ISO-8601 UTC string,
  "dataset":  {"name", "source": "synthetic"|..., "path", "n_documents", "n_persons", "n_groups",
               "split": {"train": int, "test": int, "test_fraction": float, "seed": int, "group_keys": [..], "leaks": {key: []}},
               "variants": {variant: count in the test split}},
  "config":   {"bootstrap_resamples", "bootstrap_seed", "ci_level": 0.95, "today", "versions": {...}},
  "metrics":  {"ocr": [Metric], "validation": [Metric], "quality_gate": [Metric], "forensics": [Metric]},
  "per_variant":   [ {variant, n, expected_priority, priority_match_rate, n_low, n_medium, n_high, n_incomplete,
                      quality_gate_failed, ela_not_applicable, ela_region_flagged, mean_mrz_cer, viz_field_accuracy} ],
  "failure_cases": [ {doc_id, variant, category, expected, got, note} ]   (at most 15),
  "limitations":   [string]
}
Metric = {"id", "label", "value": number|null, "ci": [lo, hi]|null, "n": documents contributing, "unit": "fraction"|"ratio",
          "note": string, "n_clusters": persons resampled (optional), "counts": {tp, fp, fn} (optional)}
```
`value` is null when the denominator is empty (no eligible documents). `ci` is a percentile bootstrap 95% interval
(seeded, n_boot >= 1000). It is a CLUSTER bootstrap: whole persons (all variants of one holder) are resampled with
replacement, because variants of the same person are strongly correlated; `n_clusters` is the number of persons in
that metric's sample. The effective sample size is therefore closer to n_clusters than to n. Rates marked "(lower is better)" are error rates.
"""


def fmt(m: dict) -> str:
    if m["value"] is None:
        return "n/a"
    ci = f" [{m['ci'][0]:.3f}, {m['ci'][1]:.3f}]" if m["ci"] else ""
    return f"{m['value']:.3f}{ci}"


def write_report(path: Path, res: dict) -> None:
    ds = res["dataset"]
    L = ["# Evaluation report - Document Screening Assistant (synthetic data)", "", SCHEMA_MD, "---", "",
         f"Generated: {res['generated_at']}  ", f"Dataset: **{ds['name']}** (source: {ds['source']}), {ds['n_documents']} documents, "
         f"{ds['n_persons']} persons, {ds['n_groups']} groups. Split: train {ds['split']['train']} / test {ds['split']['test']} "
         f"(group split, seed {ds['split']['seed']}, leaks: {ds['split']['leaks']}).  ",
         f"Bootstrap: {res['config']['bootstrap_resamples']} resamples, 95% percentile CI.", "",
         "> All numbers are measured on synthetic documents generated by the same code the system was built against. "
         "They are an engineering baseline, **not** an estimate of real-world performance. See Limitations.", ""]
    titles = {"ocr": "OCR and MRZ", "validation": "Validation rules", "quality_gate": "Quality gate", "forensics": "Forensics (ELA baseline)"}
    for g, ms in res["metrics"].items():
        L += [f"## {titles[g]}", "", "| Metric | Value [95% CI] | n |", "|---|---|---|"]
        L += [f"| {m['label']} | {fmt(m)} | {m['n']}" + (f" ({m['n_clusters']} persons)" if m.get("n_clusters") else "") + " |" for m in ms]
        notes = [f"- *{m['label']}*: {m['note']}" for m in ms if m.get("note")]
        L += [""] + notes + [""]
    L += ["## Per-variant outcomes (test split)", "",
          "| Variant | n | Expected priority | Match | LOW | MED | HIGH | INCOMPL. | Gate failed | ELA n/a | ELA flagged | MRZ CER | VIZ acc. |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in res["per_variant"]:
        L.append(f"| {r['variant']} | {r['n']} | {r['expected_priority'] or '-'} | "
                 f"{'-' if r['priority_match_rate'] is None else format(r['priority_match_rate'], '.2f')} | {r['n_low']} | {r['n_medium']} | "
                 f"{r['n_high']} | {r['n_incomplete']} | {r['quality_gate_failed']} | {r['ela_not_applicable']} | {r['ela_region_flagged']} | "
                 f"{'-' if r['mean_mrz_cer'] is None else format(r['mean_mrz_cer'], '.4f')} | "
                 f"{'-' if r['viz_field_accuracy'] is None else format(r['viz_field_accuracy'], '.3f')} |")
    L += ["", "## Failure cases (up to 15, sampled across categories)", "", "| doc_id | variant | category | expected | got | note |", "|---|---|---|---|---|---|"]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    L += [f"| {f['doc_id']} | {f['variant']} | {f['category']} | {esc(f['expected'])} | {esc(f['got'])} | {esc(f['note'])} |" for f in res["failure_cases"]]
    L += ["", "## Limitations", ""] + [f"- {x}" for x in res["limitations"]] + [""]
    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", help="dataset folder (default: $IDS_EVAL_DATASET or data/synthetic_dataset)")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data" / "evaluation")
    ap.add_argument("--report", type=Path, default=HERE / "REPORT.md")
    ap.add_argument("--test-frac", type=float, default=0.30)
    ap.add_argument("--split-seed", type=int, default=7)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--limit", type=int, default=0, help="debug: evaluate only the first N test documents")
    a = ap.parse_args()
    if a.n_boot < 1000:
        ap.error("--n-boot must be >= 1000")
    try:
        ds = load_dataset(a.dataset)
    except DatasetError as e:
        sys.exit(f"dataset error: {e}")
    train, test = group_split(ds.docs, a.test_frac, a.split_seed)
    leaks = check_no_leak(train, test)
    if any(leaks.values()):
        sys.exit(f"split leaks groups: {leaks}")
    if a.limit:
        test = test[:a.limit]
    rules = V.load_rules()
    today = date.today()
    print(f"dataset {ds.name}: {len(ds.docs)} docs -> train {len(train)} / test {len(test)}; evaluating test split")
    recs, t0 = [], time.time()
    for i, d in enumerate(test, 1):
        recs.append(run_document(d, rules, today))
        if i % 10 == 0 or i == len(test):
            print(f"  {i}/{len(test)} ({time.time() - t0:.0f}s)")
    metrics, per_variant, fails = compute_metrics(test, recs)
    for g in metrics.values():
        for m in g:
            if m["n"] and m["value"] is not None and m["ci"] is None and a.n_boot >= 1000:
                m["note"] = (m["note"] + " " if m["note"] else "") + "CI unavailable (too few valid resamples)."
    res = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {"name": ds.name, "source": ds.source, "path": str(ds.root), "n_documents": len(ds.docs),
                    "n_persons": len({d.person_id for d in ds.docs}), "n_groups": len(connected_groups(ds.docs)),
                    "split": {"train": len(train), "test": len(test), "test_fraction": a.test_frac, "seed": a.split_seed,
                              "group_keys": ["person_id", "template_id", "session_id"], "leaks": leaks},
                    "variants": dict(Counter(d.variant for d in test))},
        "config": {"bootstrap_resamples": a.n_boot, "bootstrap_seed": BOOT_SEED, "ci_level": 0.95, "today": today.isoformat(),
                   "versions": {"ocr_engine": f"{ocr.ENGINE_NAME} {ocr.engine_version()}", "forensics": ela.MODEL_VERSION,
                                "rules": V.rule_version(rules), "risk_policy": POLICY_VERSION}},
        "metrics": metrics, "per_variant": per_variant, "failure_cases": pick_failures(fails),
        "n_failure_cases_total": len(fails), "limitations": LIMITATIONS,
    }
    a.out_dir.mkdir(parents=True, exist_ok=True)
    (a.out_dir / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    write_report(a.report, res)
    print(f"wrote {a.out_dir / 'results.json'} and {a.report}")
    for g, ms in metrics.items():
        print(f"[{g}]")
        for m in ms:
            if g != "ocr" or not m["id"].startswith("viz_exact_") or m["id"] == "viz_exact_mean":
                print(f"  {m['label'][:88]:88} {fmt(m):26} n={m['n']}")


if __name__ == "__main__":
    main()
