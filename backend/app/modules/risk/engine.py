"""Transparent, rule-based review-priority engine (PDF 5.6). No hidden scores, no ML.

Principles:
  * Evidence dimensions stay separate (integrity / consistency / status / person comparison).
  * Findings with the same root cause are grouped and counted once (correlation).
  * UNAVAILABLE / INCONCLUSIVE never raise priority - they are listed as unresolved.
  * Independent dimensions that agree are called out as corroboration.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import Status
from app.modules.validation.engine import CONSISTENCY, INTEGRITY, PERSON, QUALITY, STATUS, Check

POLICY_VERSION = "review-priority-policy@1.0.0"
DIMENSIONS = [INTEGRITY, CONSISTENCY, STATUS, PERSON]
DIM_LABEL = {INTEGRITY: "Document integrity", CONSISTENCY: "Information consistency",
             STATUS: "Document status", PERSON: "Person-to-document comparison", QUALITY: "Capture quality"}


@dataclass
class RiskOutcome:
    priority: str  # LOW | MEDIUM | HIGH | INCOMPLETE
    dimensions: dict
    reasons: list[dict]
    unresolved: list[dict]
    quality_gate_failed: bool
    complete: bool


def assess(checks: list[Check], quality_gate_failed: bool = False) -> RiskOutcome:
    dims: dict[str, dict] = {}
    reasons: list[dict] = []
    unresolved: list[dict] = []
    seen_groups: set[str] = set()

    for d in DIMENSIONS:
        rows = [c for c in checks if c.dimension == d]
        fails = [c for c in rows if c.status == Status.FAIL]
        reviews = [c for c in rows if c.status == Status.REVIEW]
        unres = [c for c in rows if c.status in (Status.INCONCLUSIVE, Status.UNAVAILABLE)]
        if quality_gate_failed:
            level = "NOT_ASSESSED"
        elif fails:
            level = "FAIL"
        elif reviews:
            level = "REVIEW"
        elif unres:
            level = "INCOMPLETE"
        elif not rows or all(c.status == Status.NOT_APPLICABLE for c in rows):
            level = "NOT_APPLICABLE"
        else:
            level = "CLEAR"
        dims[d] = {"label": DIM_LABEL[d], "level": level,
                   "counts": {"pass": sum(c.status == Status.PASS for c in rows), "fail": len(fails), "review": len(reviews),
                              "unresolved": len(unres), "not_applicable": sum(c.status == Status.NOT_APPLICABLE for c in rows)},
                   "checks": [c.check_id for c in rows]}

    if quality_gate_failed:
        for c in checks:
            if c.dimension == QUALITY and c.status in (Status.FAIL, Status.INCONCLUSIVE):
                reasons.append({"check_id": c.check_id, "dimension": QUALITY, "status": c.status.value, "text": c.message})
        return RiskOutcome("INCOMPLETE", dims, reasons, [], True, False)

    flagged_dims = set()
    for c in checks:
        if c.dimension == QUALITY:
            if c.status == Status.REVIEW:
                reasons.append({"check_id": c.check_id, "dimension": QUALITY, "status": "REVIEW", "text": c.message})
            continue
        if c.status in (Status.FAIL, Status.REVIEW):
            if c.group and c.group in seen_groups:
                continue  # correlated finding: counted once
            if c.group:
                seen_groups.add(c.group)
            flagged_dims.add(c.dimension)
            reasons.append({"check_id": c.check_id, "dimension": c.dimension, "status": c.status.value, "text": f"{c.title}: {c.message}"})
        elif c.status in (Status.INCONCLUSIVE, Status.UNAVAILABLE):
            unresolved.append({"check_id": c.check_id, "dimension": c.dimension, "status": c.status.value, "text": f"{c.title}: {c.message}"})

    hard = any(c.status == Status.FAIL and c.dimension in (INTEGRITY, CONSISTENCY) for c in checks)
    status_fail = any(c.status == Status.FAIL and c.dimension == STATUS for c in checks)
    any_review = any(c.status == Status.REVIEW and c.dimension != QUALITY for c in checks)
    if hard:
        priority = "HIGH"
    elif status_fail or any_review:
        priority = "MEDIUM"
    else:
        priority = "LOW"
    if len(flagged_dims) >= 2 and priority != "LOW":
        reasons.append({"check_id": "corroboration", "dimension": "policy", "status": "INFO",
                        "text": "Independent evidence dimensions both raise findings (" +
                                ", ".join(DIM_LABEL[d] for d in sorted(flagged_dims)) + "); the findings corroborate each other."})
        if priority == "MEDIUM" and (hard or len(flagged_dims) >= 2) and any(c.status == Status.FAIL for c in checks):
            priority = "HIGH"
    return RiskOutcome(priority, dims, reasons, unresolved, False, not unresolved)
