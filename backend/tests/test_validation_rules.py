from datetime import date

from app.core.enums import Status
from app.modules.ocr_mrz.mrz import build_td3, parse_td3
from app.modules.validation import engine as V
from app.modules.validation.engine import FieldView

TODAY = date(2026, 6, 1)


def mrz_for(expiry=date(2033, 1, 14), dob=date(1985, 3, 9), surname="VALDRIS", given="ANNA MARIA", number="UT1234567",
            issuer="UTO", doc_code="P"):
    l1, l2 = build_td3(surname, given, number, "UTO", dob, "F", expiry, issuer=issuer, doc_code=doc_code)
    return parse_td3(l1, l2), (l1, l2)


def fv(name, raw, value=None, conf=0.97, corrected=False, bbox=None):
    return FieldView(name, raw, value if value is not None else raw, conf, bbox or [1, 2, 3, 4], corrected)


def viz_for(mrz, **over):
    d = {
        "surname": fv("surname", "VALDRIS", "VALDRIS"), "given_names": fv("given_names", "ANNA MARIA", "ANNA MARIA"),
        "passport_number": fv("passport_number", "UT1234567", "UT1234567"),
        "date_of_birth": fv("date_of_birth", "09 MAR 1985", "1985-03-09"),
        "date_of_expiry": fv("date_of_expiry", "14 JAN 2033", "2033-01-14"),
        "date_of_issue": fv("date_of_issue", "15 JAN 2023", "2023-01-15"),
        "sex": fv("sex", "F", "F"), "nationality": fv("nationality", "UTOPIAN", "UTOPIAN"),
        "issuer_code": fv("issuer_code", "UTO", "UTO"),
    }
    d.update(over)
    return d


def by_id(checks):
    return {c.check_id: c for c in checks}


# ------------------------------------------------------------------ status / expiry
def test_expired_document_is_status_fail_with_reason_code(rules):
    mrz, _ = mrz_for(expiry=date(2020, 1, 1))
    c = by_id(V.status_checks(mrz, viz_for(mrz), rules, TODAY))["status_expiry"]
    assert c.status == Status.FAIL and c.dimension == V.STATUS
    assert c.evidence["reason_code"] == "EXPIRED"
    assert "EXPIRED" in c.message and "not evidence of forgery" in c.message


def test_expiring_soon_is_review(rules):
    mrz, _ = mrz_for(expiry=date(2026, 6, 20))
    c = by_id(V.status_checks(mrz, viz_for(mrz), rules, TODAY))["status_expiry"]
    assert c.status == Status.REVIEW and c.evidence["reason_code"] == "EXPIRING_SOON"


def test_valid_document_passes_expiry(rules):
    mrz, _ = mrz_for()
    assert by_id(V.status_checks(mrz, viz_for(mrz), rules, TODAY))["status_expiry"].status == Status.PASS


def test_unreadable_mrz_makes_status_checks_inconclusive(rules):
    out = by_id(V.status_checks(None, viz_for(None), rules, TODAY))
    assert out["status_expiry"].status == Status.INCONCLUSIVE
    assert out["status_dob"].status == Status.INCONCLUSIVE
    assert out["status_issue_window"].status == Status.INCONCLUSIVE


def test_malformed_mrz_makes_status_checks_inconclusive(rules):
    bad = parse_td3("P<UTO", "123")
    assert by_id(V.status_checks(bad, {}, rules, TODAY))["status_expiry"].status == Status.INCONCLUSIVE


def test_dob_plausibility_pass(rules):
    mrz, _ = mrz_for(dob=date(1990, 5, 5))
    assert by_id(V.status_checks(mrz, viz_for(mrz), rules, TODAY))["status_dob"].status == Status.PASS


# ------------------------------------------------------------------ issue window
def issue_check(rules, issued, mrz=None, **kw):
    mrz = mrz or mrz_for(**kw)[0]
    viz = viz_for(mrz, date_of_issue=fv("date_of_issue", "x", issued.isoformat() if issued else None) if issued else
                  FieldView("date_of_issue", "", None, 0.0, None))
    return by_id(V.status_checks(mrz, viz, rules, TODAY))["status_issue_window"]


def test_issue_window_pass(rules):
    c = issue_check(rules, date(2023, 1, 15), expiry=date(2033, 1, 14))
    assert c.status == Status.PASS


def test_issue_date_in_future_fails(rules):
    c = issue_check(rules, date(2027, 1, 1), expiry=date(2033, 1, 14))
    assert c.status == Status.FAIL and c.evidence["reason_code"] == "INVALID_DATE" and "future" in c.message


def test_expiry_not_after_issue_fails(rules):
    c = issue_check(rules, date(2025, 1, 1), expiry=date(2024, 1, 1))
    assert c.status == Status.FAIL and "not after the issue date" in c.message


def test_validity_longer_than_ruleset_max_is_review_not_fail(rules):
    c = issue_check(rules, date(2020, 1, 1), expiry=date(2035, 1, 1))  # 15 years > 10
    assert c.status == Status.REVIEW and "exceeds" in c.message


def test_issue_before_birth_fails(rules):
    c = issue_check(rules, date(2003, 1, 1), expiry=date(2010, 1, 1), dob=date(2005, 6, 1))
    assert c.status == Status.FAIL and "precedes the date of birth" in c.message


def test_unreadable_issue_date_is_inconclusive(rules):
    assert issue_check(rules, None).status == Status.INCONCLUSIVE


# ------------------------------------------------------------------ VIZ vs MRZ
def test_all_fields_agree(rules):
    mrz, _ = mrz_for()
    out = V.cross_checks(mrz, viz_for(mrz), rules)
    assert {c.check_id for c in out} >= {"xc_surname", "xc_given_names", "xc_dob", "xc_expiry", "xc_number", "xc_sex",
                                         "xc_nationality", "xc_issuer"}
    assert all(c.status == Status.PASS for c in out), [(c.check_id, c.status) for c in out if c.status != Status.PASS]


def test_confident_mismatch_is_fail(rules):
    mrz, _ = mrz_for()
    c = by_id(V.cross_checks(mrz, viz_for(mrz, surname=fv("surname", "KORENTHAL", "KORENTHAL", 0.97)), rules))["xc_surname"]
    assert c.status == Status.FAIL and c.group == "viz_mrz_surname"
    assert "KORENTHAL" in c.message and "VALDRIS" in c.message


def test_low_confidence_mismatch_is_review_not_fail(rules):
    mrz, _ = mrz_for()
    c = by_id(V.cross_checks(mrz, viz_for(mrz, surname=fv("surname", "VALORIS", "VALORIS", 0.55)), rules))["xc_surname"]
    assert c.status == Status.REVIEW and "may be a reading error" in c.message


def test_officer_corrected_low_confidence_mismatch_is_fail(rules):
    mrz, _ = mrz_for()
    c = by_id(V.cross_checks(mrz, viz_for(mrz, surname=fv("surname", "OTHER", "OTHER", 0.2, corrected=True)), rules))["xc_surname"]
    assert c.status == Status.FAIL


def test_unreadable_viz_field_is_inconclusive(rules):
    mrz, _ = mrz_for()
    out = by_id(V.cross_checks(mrz, viz_for(mrz, surname=fv("surname", "  ", None, 0.0)), rules))
    assert out["xc_surname"].status == Status.INCONCLUSIVE
    assert out["xc_given_names"].status == Status.PASS  # other fields unaffected


def test_unparseable_date_is_inconclusive_not_fail(rules):
    mrz, _ = mrz_for()
    out = by_id(V.cross_checks(mrz, viz_for(mrz, date_of_birth=FieldView("date_of_birth", "9 M4R 1985", None, 0.9, None)), rules))
    assert out["xc_dob"].status == Status.INCONCLUSIVE


def test_missing_viz_field_is_inconclusive(rules):
    mrz, _ = mrz_for()
    viz = viz_for(mrz)
    del viz["sex"]
    assert by_id(V.cross_checks(mrz, viz, rules))["xc_sex"].status == Status.INCONCLUSIVE


def test_no_mrz_means_single_inconclusive_crosscheck(rules):
    out = V.cross_checks(None, {}, rules)
    assert len(out) == 1 and out[0].check_id == "viz_mrz_crosscheck" and out[0].status == Status.INCONCLUSIVE


def test_truncated_given_names_tolerated(rules):
    long_given = "ALEXANDRA MARIA CHARLOTTE ISABELLA"
    mrz, _ = mrz_for(given=long_given, surname="VALDRIS")
    viz = viz_for(mrz, given_names=fv("given_names", long_given, long_given))
    assert by_id(V.cross_checks(mrz, viz, rules))["xc_given_names"].status == Status.PASS


def test_name_normalisation_ignores_punctuation_and_case(rules):
    mrz, _ = mrz_for(surname="O BRIEN")
    viz = viz_for(mrz, surname=fv("surname", "O'Brien", "O'Brien"))
    assert by_id(V.cross_checks(mrz, viz, rules))["xc_surname"].status == Status.PASS


# ------------------------------------------------------------------ MRZ checks (confidence handling)
def test_bad_digit_high_confidence_is_fail(rules):
    _, (l1, l2) = mrz_for()
    mrz = parse_td3(l1, l2[:9] + str((int(l2[9]) + 3) % 10) + l2[10:])
    out = by_id(V.mrz_checks(mrz, [0.97, 0.97], [], rules))
    assert out["mrz_cd_passport_number"].status == Status.FAIL and out["mrz_cd_passport_number"].group == "mrz_digits"
    assert out["mrz_cd_date_of_birth"].status == Status.PASS
    assert out["mrz_structure"].status == Status.PASS


def test_bad_digit_low_confidence_is_review(rules):
    _, (l1, l2) = mrz_for()
    mrz = parse_td3(l1, l2[:9] + str((int(l2[9]) + 3) % 10) + l2[10:])
    out = by_id(V.mrz_checks(mrz, [0.97, 0.60], [], rules))
    assert out["mrz_cd_passport_number"].status == Status.REVIEW


def test_bad_digit_after_filler_repair_is_review(rules):
    _, (l1, l2) = mrz_for()
    mrz = parse_td3(l1, l2[:9] + str((int(l2[9]) + 3) % 10) + l2[10:])
    repairs = [{"line": 2, "position": 30, "from": "<<", "to": "<<<", "expected": "filler run repaired"}]
    assert by_id(V.mrz_checks(mrz, [0.97, 0.97], repairs, rules))["mrz_cd_passport_number"].status == Status.REVIEW


def test_valid_mrz_all_digits_pass(rules):
    mrz, _ = mrz_for()
    out = V.mrz_checks(mrz, [0.97, 0.97], [], rules)
    assert all(c.status == Status.PASS for c in out) and len(out) == 6


def test_structure_error_high_conf_fail_low_conf_review(rules):
    bad = parse_td3("P<UTOX", "123")
    assert by_id(V.mrz_checks(bad, [0.97, 0.97], [], rules))["mrz_structure"].status == Status.FAIL
    assert by_id(V.mrz_checks(bad, [0.5, 0.5], [], rules))["mrz_structure"].status == Status.REVIEW


def test_no_mrz_found_is_review(rules):
    assert V.mrz_checks(None, [], [], rules)[0].status == Status.REVIEW


# ------------------------------------------------------------------ template recognition
def test_template_recognised(rules):
    mrz, _ = mrz_for()
    c = V.template_check(mrz, rules)
    assert c.status == Status.PASS and rules["template_id"] in c.message


def test_other_issuer_is_not_applicable(rules):
    mrz, _ = mrz_for(issuer="XXA")
    assert V.template_check(mrz, rules).status == Status.NOT_APPLICABLE


def test_other_document_code_is_not_applicable(rules):
    mrz, _ = mrz_for(doc_code="PD")
    assert V.template_check(mrz, rules).status == Status.NOT_APPLICABLE


def test_template_inconclusive_without_mrz(rules):
    assert V.template_check(None, rules).status == Status.INCONCLUSIVE
    assert V.template_check(parse_td3("x", "y"), rules).status == Status.INCONCLUSIVE


def test_rule_version_string(rules):
    assert V.rule_version(rules) == "uto-td3-rules@1.0.0"


def test_missing_inputs_never_become_fail(rules):
    """Every 'could not evaluate' path yields INCONCLUSIVE/REVIEW, never FAIL."""
    outs = V.status_checks(None, {}, rules, TODAY) + V.cross_checks(None, {}, rules) + V.mrz_checks(None, [], [], rules)
    assert not any(c.status == Status.FAIL for c in outs)
