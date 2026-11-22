"""Quality gate, rectification and OCR on generated captures (OCR results are cached per variant)."""
from datetime import date

import pytest

from app.modules.ocr_mrz import extract as ocr
from app.modules.ocr_mrz.mrz import parse_td3
from app.modules.preprocessing.rectify import rotate_180


def statuses(a):
    return {k: m.status for k, m in a["metrics"].items()}


def test_clean_sample_passes_quality_and_is_cropped_without_resampling(analysed):
    a = analysed("clean")
    assert statuses(a) == {"crop": "PASS", "resolution": "PASS", "blur": "PASS", "glare": "PASS"}
    assert a["rect"].method == "crop" and not a["rect"].resampled and a["rect"].origin is not None
    assert a["rect"].image.shape[:2] == (880, 1250)


@pytest.mark.parametrize("variant,metric", [("blurry", "blur"), ("glare", "glare"), ("cropped", "crop"), ("low_res", "resolution")])
def test_degraded_variants_fail_the_relevant_metric(analysed, variant, metric):
    a = analysed(variant)
    assert a["metrics"][metric].status == "FAIL", statuses(a)
    assert a["page"] is None  # OCR is skipped by the conftest gate, mirroring the pipeline


def test_cropped_variant_not_rectified_and_other_metrics_inconclusive(analysed):
    a = analysed("cropped")
    assert a["rect"].image is None and a["rect"].touches_border
    assert a["metrics"]["blur"].status == "INCONCLUSIVE" and a["metrics"]["glare"].status == "INCONCLUSIVE"


def test_blurry_variant_other_metrics_unaffected(analysed):
    a = analysed("blurry")
    assert a["metrics"]["crop"].status == "PASS" and a["metrics"]["glare"].status == "PASS"


def test_rotated_variant_is_rectified_by_warp_and_still_readable(analysed):
    a = analysed("rotated")
    assert a["rect"].method == "warp" and a["rect"].resampled and a["rect"].origin is None
    assert all(s != "FAIL" for s in statuses(a).values()), statuses(a)
    assert a["page"] is not None
    label = a["label"]
    mrz = parse_td3(*a["lines"])
    assert mrz.format_ok and mrz.all_checks_valid
    assert mrz.passport_number == label["ground_truth"]["passport_number"]
    assert mrz.surname == label["ground_truth"]["surname"]
    viz = {f.name: f for f in a["page"].viz}
    assert viz["surname"].normalized == label["ground_truth"]["surname"]
    assert viz["passport_number"].normalized == label["ground_truth"]["passport_number"]


def test_clean_ocr_reads_mrz_and_key_fields(analysed):
    a = analysed("clean")
    label = a["label"]
    assert list(a["lines"]) == label["mrz"]  # exact after documented look-alike / filler normalisation
    mrz = parse_td3(*a["lines"])
    assert mrz.all_checks_valid
    viz = {f.name: f for f in a["page"].viz}
    gt = label["ground_truth"]
    for name in ("surname", "given_names", "passport_number", "sex", "place_of_birth"):
        assert viz[name].normalized == gt[name].upper(), name
    assert viz["date_of_birth"].normalized == ocr.parse_viz_date(gt["date_of_birth"]).isoformat()
    assert viz["date_of_expiry"].normalized == ocr.parse_viz_date(gt["date_of_expiry"]).isoformat()


def test_ocr_confidence_values_are_probabilities(analysed):
    a = analysed("clean")
    assert all(0.0 <= f.confidence <= 1.0 for f in a["page"].viz)
    assert all(0.0 <= c <= 1.0 for c in a["page"].mrz_conf)


def test_expired_variant_is_readable_and_expired(analysed):
    a = analysed("expired")
    mrz = parse_td3(*a["lines"])
    assert mrz.format_ok and mrz.expiry_date < date.today()


def test_bad_check_digit_survives_ocr_and_normalisation(analysed):
    a = analysed("bad_check_digit")
    mrz = parse_td3(*a["lines"])
    by = {c.name: c for c in mrz.checks}
    assert not by["passport_number"].valid  # normalisation must not repair the planted error
    assert list(a["lines"]) == a["label"]["mrz"]


def test_rotate_180_marks_resampled(analysed):
    from app.modules.preprocessing.rectify import locate_and_rectify
    import copy
    r = copy.deepcopy(analysed("clean")["rect"])
    r = rotate_180(r)
    assert r.resampled and any("upside-down" in n for n in r.notes)
