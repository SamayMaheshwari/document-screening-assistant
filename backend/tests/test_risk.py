from app.core.enums import Status
from app.modules.risk.engine import assess
from app.modules.validation.engine import CONSISTENCY, INTEGRITY, PERSON, QUALITY, STATUS, Check


def chk(cid, dim, status, group=None, title=None):
    return Check(cid, "t", dim, title or cid, status, f"msg {cid}", group=group)


BASE_PASS = [chk("a", INTEGRITY, Status.PASS), chk("b", CONSISTENCY, Status.PASS), chk("c", STATUS, Status.PASS),
             chk("q", QUALITY, Status.PASS)]


def test_all_pass_is_low_and_complete():
    o = assess(BASE_PASS)
    assert o.priority == "LOW" and o.complete and not o.reasons and not o.unresolved
    assert o.dimensions[INTEGRITY]["level"] == "CLEAR"


def test_unavailable_never_raises_priority():
    o = assess(BASE_PASS + [chk("registry_lookup", STATUS, Status.UNAVAILABLE, group="registry")])
    assert o.priority == "LOW"
    assert not o.complete and [u["check_id"] for u in o.unresolved] == ["registry_lookup"]
    assert o.dimensions[STATUS]["level"] == "INCOMPLETE"
    assert o.reasons == []


def test_inconclusive_never_raises_priority():
    o = assess(BASE_PASS + [chk("x1", CONSISTENCY, Status.INCONCLUSIVE), chk("x2", INTEGRITY, Status.INCONCLUSIVE),
                            chk("x3", STATUS, Status.UNAVAILABLE)])
    assert o.priority == "LOW" and len(o.unresolved) == 3 and not o.complete


def test_only_unresolved_checks_is_low():
    o = assess([chk("x", CONSISTENCY, Status.INCONCLUSIVE), chk("y", STATUS, Status.UNAVAILABLE)])
    assert o.priority == "LOW"


def test_quality_gate_failure_is_incomplete_and_assesses_nothing():
    checks = [chk("quality_blur", QUALITY, Status.FAIL), chk("xc", CONSISTENCY, Status.FAIL), chk("s", STATUS, Status.FAIL)]
    o = assess(checks, quality_gate_failed=True)
    assert o.priority == "INCOMPLETE" and o.quality_gate_failed and not o.complete
    assert all(d["level"] == "NOT_ASSESSED" for d in o.dimensions.values())
    assert [r["check_id"] for r in o.reasons] == ["quality_blur"]  # downstream FAILs are not reported as findings


def test_consistency_fail_is_high():
    o = assess(BASE_PASS + [chk("xc_surname", CONSISTENCY, Status.FAIL)])
    assert o.priority == "HIGH" and o.dimensions[CONSISTENCY]["level"] == "FAIL"


def test_integrity_fail_is_high():
    assert assess(BASE_PASS + [chk("i", INTEGRITY, Status.FAIL)]).priority == "HIGH"


def test_status_fail_alone_is_medium_not_high():
    o = assess(BASE_PASS + [chk("status_expiry", STATUS, Status.FAIL)])
    assert o.priority == "MEDIUM"
    assert not any(r["check_id"] == "corroboration" for r in o.reasons)


def test_review_is_medium():
    o = assess(BASE_PASS + [chk("f", INTEGRITY, Status.REVIEW)])
    assert o.priority == "MEDIUM" and o.dimensions[INTEGRITY]["level"] == "REVIEW"


def test_quality_review_does_not_change_priority_but_is_listed():
    o = assess(BASE_PASS + [chk("quality_glare", QUALITY, Status.REVIEW)])
    assert o.priority == "LOW"
    assert any(r["check_id"] == "quality_glare" for r in o.reasons)


def test_correlated_findings_counted_once():
    checks = BASE_PASS + [chk(f"mrz_cd_{n}", CONSISTENCY, Status.FAIL, group="mrz_digits") for n in ("passport_number", "composite")]
    o = assess(checks)
    assert [r["check_id"] for r in o.reasons] == ["mrz_cd_passport_number"]
    # the per-dimension counts still show both rows (transparency), only the reasons are de-duplicated
    assert o.dimensions[CONSISTENCY]["counts"]["fail"] == 2


def test_ungrouped_findings_all_listed():
    o = assess(BASE_PASS + [chk("u1", CONSISTENCY, Status.FAIL), chk("u2", CONSISTENCY, Status.FAIL)])
    assert len([r for r in o.reasons if r["status"] == "FAIL"]) == 2


def test_corroboration_reason_when_two_dimensions_flag():
    checks = BASE_PASS + [chk("xc_surname", CONSISTENCY, Status.FAIL), chk("forensics_ela", INTEGRITY, Status.REVIEW, group="forensics")]
    o = assess(checks)
    assert o.priority == "HIGH"
    corr = [r for r in o.reasons if r["check_id"] == "corroboration"]
    assert len(corr) == 1 and corr[0]["status"] == "INFO"
    assert "Information consistency" in corr[0]["text"] and "Document integrity" in corr[0]["text"]


def test_two_dimensions_with_only_reviews_stay_medium():
    checks = BASE_PASS + [chk("r1", CONSISTENCY, Status.REVIEW), chk("r2", INTEGRITY, Status.REVIEW)]
    o = assess(checks)
    assert o.priority == "MEDIUM"  # escalation to HIGH needs at least one hard FAIL
    assert any(r["check_id"] == "corroboration" for r in o.reasons)


def test_status_fail_plus_review_in_other_dimension_escalates_to_high():
    o = assess(BASE_PASS + [chk("status_expiry", STATUS, Status.FAIL), chk("f", INTEGRITY, Status.REVIEW)])
    assert o.priority == "HIGH"


def test_correlation_group_is_shared_across_dimensions_once():
    checks = BASE_PASS + [chk("a1", CONSISTENCY, Status.FAIL, group="g"), chk("a2", INTEGRITY, Status.FAIL, group="g")]
    o = assess(checks)
    assert len([r for r in o.reasons if r["check_id"] in ("a1", "a2")]) == 1


def test_not_applicable_dimension():
    o = assess([chk("face", PERSON, Status.NOT_APPLICABLE)] + BASE_PASS)
    assert o.dimensions[PERSON]["level"] == "NOT_APPLICABLE" and o.priority == "LOW"


def test_dimensions_are_independent():
    o = assess(BASE_PASS + [chk("xc", CONSISTENCY, Status.FAIL)])
    assert o.dimensions[INTEGRITY]["level"] == "CLEAR" and o.dimensions[STATUS]["level"] == "CLEAR"
