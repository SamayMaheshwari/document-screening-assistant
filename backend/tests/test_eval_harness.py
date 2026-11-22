"""Unit tests for the evaluation harness in model-work/ (split, dataset loader, metric helpers)."""
import json
import sys
from pathlib import Path

import pytest

MODEL_WORK = Path(__file__).resolve().parents[2] / "model-work"
sys.path.insert(0, str(MODEL_WORK))

from evaluation import dataset as D  # noqa: E402
from evaluation import split as S  # noqa: E402


def rec(i, person, template, session, variant="clean"):
    return {"doc_id": f"d{i:03d}", "person_id": person, "template_id": template, "session_id": session, "variant": variant}


def synthetic_records(n_persons=30, per_person=5):
    out = []
    for p in range(n_persons):
        for v in range(per_person):
            out.append(rec(len(out), f"P{p}", f"T/lot{p // 3}", f"S{p // 2}"))  # sessions of 2 persons, lots of 3 -> chains
    return out


# ------------------------------------------------------------------ split
def test_split_has_no_group_leak_on_any_key():
    docs = synthetic_records()
    for seed in range(8):
        train, test = S.group_split(docs, 0.3, seed)
        assert len(train) + len(test) == len(docs)
        assert {d["doc_id"] for d in train}.isdisjoint({d["doc_id"] for d in test})
        assert S.check_no_leak(train, test) == {"person_id": [], "template_id": [], "session_id": []}


def test_split_keeps_chained_groups_together():
    # A~B by person, B~C by session, C~D by template: all four must land on the same side
    docs = [rec(0, "pA", "tA", "s0"), rec(1, "pA", "tB", "s1"), rec(2, "pC", "tC", "s1"), rec(3, "pD", "tC", "s9"),
            rec(4, "pX", "tX", "sX"), rec(5, "pY", "tY", "sY"), rec(6, "pZ", "tZ", "sZ"), rec(7, "pW", "tW", "sW")]
    groups = S.connected_groups(docs)
    assert sorted(len(g) for g in groups) == [1, 1, 1, 1, 4]
    for seed in range(20):
        train, test = S.group_split(docs, 0.5, seed)
        chain = {"d000", "d001", "d002", "d003"}
        ids_test = {d["doc_id"] for d in test}
        assert chain <= ids_test or not (chain & ids_test)


def test_split_is_deterministic_and_seed_dependent():
    docs = synthetic_records()
    a = S.group_split(docs, 0.3, 7)
    b = S.group_split(docs, 0.3, 7)
    assert [d["doc_id"] for d in a[1]] == [d["doc_id"] for d in b[1]]
    others = {tuple(d["doc_id"] for d in S.group_split(docs, 0.3, s)[1]) for s in range(10)}
    assert len(others) > 1


def test_split_is_roughly_70_30():
    docs = synthetic_records(60, 5)
    train, test = S.group_split(docs, 0.3, 7)
    assert 0.2 <= len(test) / len(docs) <= 0.4


def test_leak_detector_actually_detects():
    a = [rec(0, "p1", "t1", "s1")]
    b = [rec(1, "p1", "t2", "s2")]
    assert S.check_no_leak(a, b)["person_id"] == ["p1"]


def test_missing_keys_do_not_link_documents():
    docs = [{"doc_id": "a", "person_id": "", "template_id": None, "session_id": ""}, {"doc_id": "b", "person_id": "", "template_id": None, "session_id": ""}]
    assert len(S.connected_groups(docs)) == 2


def test_real_generated_dataset_split_if_present():
    root = D.DEFAULT_DATASET
    if not (root / "labels.json").exists():
        pytest.skip("synthetic dataset not generated")
    ds = D.load_dataset(root)
    train, test = S.group_split(ds.docs, 0.3, 7)
    assert test and train and not any(S.check_no_leak(train, test).values())
    assert len(S.connected_groups(ds.docs)) > 3  # grouping keys must not collapse everything into one component


# ------------------------------------------------------------------ dataset loader
def _write_img(path: Path):
    from PIL import Image
    Image.new("RGB", (8, 8), (1, 2, 3)).save(path, "JPEG")


def test_loader_reads_manifest_list_and_defaults(tmp_path):
    _write_img(tmp_path / "a.jpg")
    _write_img(tmp_path / "b.png".replace("png", "jpg"))
    (tmp_path / "labels.json").write_text(json.dumps([
        {"doc_id": "a", "file": "a.jpg", "variant": "clean", "ground_truth": {"surname": "X"}, "mrz": ["l1", "l2"],
         "person_id": "P1", "template_id": "T", "session_id": "S"},
        {"doc_id": "b"}]))
    ds = D.load_dataset(tmp_path)
    assert [d.doc_id for d in ds.docs] == ["a", "b"]
    b = ds.docs[1]
    assert b.variant == "unlabelled" and b.tamper_regions == [] and b.person_id == "b"  # each unlabelled doc is its own group
    assert ds.docs[0].group_keys == {"person_id": "P1", "template_id": "T", "session_id": "S"}


def test_loader_reads_manifest_object_with_meta(tmp_path):
    _write_img(tmp_path / "a.jpg")
    (tmp_path / "labels.json").write_text(json.dumps({"dataset": {"name": "company_batch_1", "source": "company"},
                                                      "documents": [{"doc_id": "a", "variant": "clean"}]}))
    ds = D.load_dataset(tmp_path)
    assert ds.name == "company_batch_1" and ds.source == "company"


def test_loader_reads_per_image_json_without_manifest(tmp_path):
    for n in ("x1", "x2"):
        _write_img(tmp_path / f"{n}.jpg")
        (tmp_path / f"{n}.json").write_text(json.dumps({"variant": "blurry", "ground_truth": {}, "mrz": []}))
    ds = D.load_dataset(tmp_path)
    assert [d.doc_id for d in ds.docs] == ["x1", "x2"] and ds.docs[0].variant == "blurry"


def test_loader_folder_precedence_cli_over_env(tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("IDS_EVAL_DATASET", str(other))
    assert D.resolve_dataset_dir() == other.resolve()
    assert D.resolve_dataset_dir(str(tmp_path)) == tmp_path.resolve()
    monkeypatch.delenv("IDS_EVAL_DATASET")
    assert D.resolve_dataset_dir() == D.DEFAULT_DATASET.resolve()


def test_loader_errors(tmp_path):
    with pytest.raises(D.DatasetError):
        D.load_dataset(tmp_path / "missing")
    with pytest.raises(D.DatasetError):
        D.load_dataset(tmp_path)  # empty folder
    (tmp_path / "labels.json").write_text(json.dumps([{"doc_id": "ghost", "file": "ghost.jpg"}]))
    with pytest.raises(D.DatasetError):
        D.load_dataset(tmp_path)  # image missing
    _write_img(tmp_path / "a.jpg")
    (tmp_path / "labels.json").write_text(json.dumps([{"doc_id": "a"}, {"doc_id": "a"}]))
    with pytest.raises(D.DatasetError):
        D.load_dataset(tmp_path)  # duplicate ids


# ------------------------------------------------------------------ metric helpers
@pytest.fixture(scope="module")
def E():
    from evaluation import evaluate
    return evaluate


def test_levenshtein_and_cer(E):
    assert E.levenshtein("kitten", "sitting") == 3 and E.levenshtein("", "abc") == 3 and E.levenshtein("abc", "abc") == 0
    assert E.mrz_cer(["ABCD", "EFGH"], ["ABCD", "EFGH"]) == 0
    assert E.mrz_cer(["ABXD", "EFGH"], ["ABCD", "EFGH"]) == pytest.approx(1 / 8)


def test_iou(E):
    assert E.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1
    assert E.iou([0, 0, 10, 10], [20, 20, 5, 5]) == 0
    assert E.iou([0, 0, 10, 10], [5, 0, 10, 10]) == pytest.approx(50 / 150)


def test_ratio_metric_value_ci_and_determinism(E):
    flags = [1] * 30 + [0] * 10
    m1 = E.rate_metric("t", "t", flags)
    m2 = E.rate_metric("t", "t", flags)
    assert m1 == m2  # seeded
    assert m1["value"] == 0.75 and m1["n"] == 40
    lo, hi = m1["ci"]
    assert 0.55 <= lo < 0.75 < hi <= 0.9  # binomial sd ~0.07 -> roughly +/-0.14


def test_ratio_metric_empty_and_perfect(E):
    assert E.rate_metric("e", "e", [])["value"] is None
    assert E.ratio_metric("z", "z", [0, 0], [0, 0])["value"] is None
    m = E.rate_metric("p", "p", [1] * 12)
    assert m["value"] == 1.0 and m["ci"] == [1.0, 1.0]


def test_bootstrap_resample_count_floor(E):
    assert E.N_BOOT >= 1000


def test_cluster_bootstrap_is_wider_than_document_bootstrap_for_correlated_variants(E):
    # 10 persons x 6 documents; each person is either entirely right or entirely wrong
    recs = [{"person_id": f"p{p}"} for p in range(10) for _ in range(6)]
    flags = [1.0 if p < 5 else 0.0 for p in range(10) for _ in range(6)]
    E.bind([], "cl_a")
    doc_level = E.rate_metric("cl_a", "x", flags)
    E.bind(recs, "cl_b")
    clustered = E.rate_metric("cl_b", "x", flags)
    assert doc_level["value"] == clustered["value"] == 0.5
    assert clustered["n_clusters"] == 10
    width = lambda m: m["ci"][1] - m["ci"][0]
    assert width(clustered) > width(doc_level)


def test_pick_failures_caps_at_15_and_spreads_over_categories(E):
    fails = [{"doc_id": f"d{i}", "person_id": f"p{i % 4}", "variant": "v", "category": "viz_ocr", "expected": "a", "got": "b", "note": ""}
             for i in range(40)] + \
            [{"doc_id": "g", "person_id": "pg", "variant": "blurry", "category": "gate_miss", "expected": "a", "got": "b", "note": ""}]
    out = E.pick_failures(fails)
    assert len(out) == 15 and out[0]["category"] == "gate_miss"
    assert {"doc_id", "variant", "expected", "got", "note"} <= set(out[0])


def test_results_json_schema_if_present():
    p = MODEL_WORK.parent / "data" / "evaluation" / "results.json"
    if not p.exists():
        pytest.skip("evaluation not run")
    r = json.loads(p.read_text())
    assert {"generated_at", "dataset", "metrics", "per_variant", "failure_cases", "limitations"} <= set(r)
    assert set(r["metrics"]) == {"ocr", "validation", "quality_gate", "forensics"}
    assert r["dataset"]["source"] == "synthetic" and r["dataset"]["split"]["leaks"] == {"person_id": [], "template_id": [], "session_id": []}
    assert r["config"]["bootstrap_resamples"] >= 1000 and len(r["failure_cases"]) <= 15
    for g in r["metrics"].values():
        for m in g:
            assert {"id", "label", "value", "ci", "n"} <= set(m)
            if m["value"] is not None and m["ci"]:
                assert m["ci"][0] <= m["value"] <= m["ci"][1] or abs(m["value"] - m["ci"][0]) < 0.02 or abs(m["value"] - m["ci"][1]) < 0.02
