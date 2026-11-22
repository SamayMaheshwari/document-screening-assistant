"""End-to-end API tests through FastAPI's TestClient against a temporary database and storage."""
import hashlib
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

CREDS = {"officer": "officer", "admin": "admin", "auditor": "auditor"}


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    out = {}
    for user, pw in CREDS.items():
        r = client.post("/api/v1/auth/login", json={"username": user, "password": pw})
        assert r.status_code == 200, r.text
        out[user] = {"Authorization": f"Bearer {r.json()['token']}"}
    return out


def wait_done(client, headers, case_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        c = client.get(f"/api/v1/cases/{case_id}", headers=headers).json()
        if c["status"] not in ("PROCESSING", "NEW"):
            return c
        time.sleep(0.3)
    raise AssertionError("pipeline did not finish")


def upload(client, headers, data, name="scan.jpg"):
    r = client.post("/api/v1/cases", headers=headers, files={"file": (name, data, "image/jpeg")})
    assert r.status_code == 202, r.text
    return r.json()["case_id"]


def submit_demo(client, headers, variant):
    r = client.post(f"/api/v1/demo/samples/{variant}/submit", headers=headers)
    assert r.status_code == 202, r.text
    return r.json()["case_id"]


def results(client, headers, case_id):
    r = client.get(f"/api/v1/cases/{case_id}/results", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def checks_of(res):
    return {c["id"]: c for c in res["checks"]}


@pytest.fixture(scope="module")
def core(client, auth):
    """The 5 core demo variants, processed once. Uploaded through POST /cases (registry_unavailable needs
    its demo flag, so it goes through the demo-submit endpoint, which uses the same pipeline)."""
    from app.synthetic import samples
    out, sent = {}, {}
    for v in ("clean", "bad_check_digit", "edited_name", "blurry"):
        data, _ = samples.sample_bytes(v)
        sent[v] = data
        out[v] = upload(client, auth["officer"], data, f"{v}.jpg")
    out["registry_unavailable"] = submit_demo(client, auth["officer"], "registry_unavailable")
    sent["registry_unavailable"] = samples.sample_bytes("registry_unavailable")[0]
    summaries = {v: wait_done(client, auth["officer"], cid) for v, cid in out.items()}
    return {"ids": out, "summary": summaries, "sent": sent}


# ------------------------------------------------------------------ auth
@pytest.mark.parametrize("user", ["officer", "admin", "auditor"])
def test_login_all_roles(client, user):
    r = client.post("/api/v1/auth/login", json={"username": user, "password": CREDS[user]})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == user and body["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200 and me.json()["username"] == user


def test_bad_password_401(client):
    assert client.post("/api/v1/auth/login", json={"username": "officer", "password": "nope"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"}).status_code == 401


def test_unauthenticated_and_garbage_token_rejected(client):
    assert client.get("/api/v1/cases").status_code == 401
    assert client.get("/api/v1/cases", headers={"Authorization": "Bearer abc.def.ghi"}).status_code == 401
    assert client.post("/api/v1/cases", files={"file": ("a.jpg", b"x", "image/jpeg")}).status_code == 401


def test_health(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"


# ------------------------------------------------------------------ the 5 core demo variants
def test_clean_completed_low(core):
    s = core["summary"]["clean"]
    assert s["status"] == "COMPLETED" and s["priority"] == "LOW" and s["complete"] is True


def test_clean_checks_all_good(client, auth, core):
    res = results(client, auth["officer"], core["ids"]["clean"])
    ch = checks_of(res)
    bad = {k: c["status"] for k, c in ch.items() if c["status"] in ("FAIL", "REVIEW", "INCONCLUSIVE", "UNAVAILABLE")}
    assert not bad, bad
    assert ch["forensics_ela"]["status"] == "PASS" and ch["registry_lookup"]["status"] == "PASS"
    assert ch["face_comparison"]["status"] == "NOT_APPLICABLE"


def test_bad_check_digit_fails_mrz_digit(client, auth, core):
    s = core["summary"]["bad_check_digit"]
    assert s["status"] == "REVIEW_REQUIRED" and s["priority"] == "HIGH"
    ch = checks_of(results(client, auth["officer"], core["ids"]["bad_check_digit"]))
    assert ch["mrz_cd_passport_number"]["status"] == "FAIL"
    assert ch["mrz_cd_date_of_birth"]["status"] == "PASS"
    assert ch["xc_surname"]["status"] == "PASS"  # a check-digit error is not a VIZ/MRZ mismatch


def test_edited_name_fails_surname_crosscheck(client, auth, core):
    s = core["summary"]["edited_name"]
    assert s["status"] == "REVIEW_REQUIRED" and s["priority"] == "HIGH"
    res = results(client, auth["officer"], core["ids"]["edited_name"])
    ch = checks_of(res)
    assert ch["xc_surname"]["status"] == "FAIL"
    assert ch["xc_given_names"]["status"] == "PASS" and ch["xc_dob"]["status"] == "PASS"
    assert ch["forensics_ela"]["status"] == "REVIEW"  # ELA flags the edited region (a review aid)
    assert any(r["check_id"] == "corroboration" for r in res["risk"]["reasons"])


def test_blurry_requires_recapture_with_inconclusive_downstream(client, auth, core):
    s = core["summary"]["blurry"]
    assert s["status"] == "RECAPTURE_REQUIRED" and s["priority"] == "INCOMPLETE"
    res = results(client, auth["officer"], core["ids"]["blurry"])
    ch = checks_of(res)
    assert ch["quality_blur"]["status"] == "FAIL"
    for cid in ("mrz_checkdigits", "viz_mrz_crosscheck", "status_expiry", "forensics_ela", "registry_lookup"):
        assert ch[cid]["status"] == "INCONCLUSIVE", cid
    assert not res["fields"]  # no unreliable OCR output was produced
    assert not any(c["status"] == "FAIL" and c["dimension"] != "capture_quality" for c in res["checks"])


def test_registry_unavailable_is_not_a_fraud_signal(client, auth, core):
    s = core["summary"]["registry_unavailable"]
    assert s["priority"] == "LOW" and s["status"] == "REVIEW_REQUIRED" and s["complete"] is False
    res = results(client, auth["officer"], core["ids"]["registry_unavailable"])
    assert checks_of(res)["registry_lookup"]["status"] == "UNAVAILABLE"
    assert [u["check_id"] for u in res["risk"]["unresolved"]] == ["registry_lookup"]
    assert not any(c["status"] == "FAIL" for c in res["checks"])


def test_original_stored_unchanged(client, auth, core):
    from app.database.models import Document
    from app.database.session import SessionLocal
    from app.storage.backend import get_storage
    for v in ("clean", "edited_name", "blurry"):
        cid, sent = core["ids"][v], core["sent"][v]
        res = results(client, auth["officer"], cid)
        assert res["document"]["sha256"] == hashlib.sha256(sent).hexdigest()
        with SessionLocal() as db:
            doc = db.execute(select(Document).where(Document.case_id == cid)).scalars().one()
            stored = get_storage().get(doc.storage_key)
        assert hashlib.sha256(stored).hexdigest() == hashlib.sha256(sent).hexdigest() and stored == sent
        r = client.get(f"/api/v1/cases/{cid}/image?kind=original", headers=auth["officer"])
        assert r.status_code == 200 and r.content == sent
        assert doc.size_bytes == len(sent)


def test_rectified_image_is_a_separate_derived_file(client, auth, core):
    r = client.get(f"/api/v1/cases/{core['ids']['clean']}/image?kind=rectified", headers=auth["officer"])
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert r.content != core["sent"]["clean"]


# ------------------------------------------------------------------ intake via API
def test_upload_rejections(client, auth):
    h = auth["officer"]
    for name, data, code in [("a.jpg", b"MZ\x90\x00" + b"\x00" * 64, "type_not_allowed"),
                             ("a.jpg", b"%PDF-1.4 x", "type_not_allowed"),
                             ("a.jpg", b"", "empty"),
                             ("a.jpg", b"not an image at all", "bad_signature"),
                             ("a.jpg", b"\xff\xd8\xff\xe0" + b"junk" * 50, "corrupt")]:
        r = client.post("/api/v1/cases", headers=h, files={"file": (name, data, "image/jpeg")})
        assert r.status_code == 422, (name, r.text)
        assert r.json()["detail"]["code"] == code


def test_rejected_upload_audited_without_creating_case(client, auth):
    before = client.get("/api/v1/cases", headers=auth["officer"]).json()["total"]
    client.post("/api/v1/cases", headers=auth["officer"], files={"file": ("a.jpg", b"%PDF-1.4", "image/jpeg")})
    assert client.get("/api/v1/cases", headers=auth["officer"]).json()["total"] == before
    ev = client.get("/api/v1/audit?action=intake.rejected", headers=auth["auditor"]).json()["items"]
    assert ev and ev[0]["metadata"]["code"] == "type_not_allowed"


# ------------------------------------------------------------------ roles
def test_auditor_cannot_create_review_or_get_image(client, auth, core):
    cid = core["ids"]["clean"]
    a = auth["auditor"]
    assert client.post("/api/v1/cases", headers=a, files={"file": ("a.jpg", core["sent"]["clean"], "image/jpeg")}).status_code == 403
    assert client.post(f"/api/v1/cases/{cid}/review", headers=a,
                       json={"outcome": "NO_ISSUES_FOUND", "rationale": "auditors may not review"}).status_code == 403
    assert client.get(f"/api/v1/cases/{cid}/image?kind=original", headers=a).status_code == 403
    assert client.get(f"/api/v1/cases/{cid}/image?kind=rectified", headers=a).status_code == 403
    assert client.post(f"/api/v1/demo/samples/clean/submit", headers=a).status_code == 403


def test_auditor_results_are_redacted(client, auth, core):
    cid = core["ids"]["edited_name"]
    off = results(client, auth["officer"], cid)
    aud = results(client, auth["auditor"], cid)
    assert aud["pii_redacted"] is True and off["pii_redacted"] is False
    off_f = {f["name"]: f for f in off["fields"]}
    aud_f = {f["name"]: f for f in aud["fields"]}
    assert off_f["surname"]["raw"] and "•" not in off_f["surname"]["raw"]
    for name in ("surname", "given_names", "passport_number", "date_of_birth", "mrz_line1", "mrz_line2"):
        assert "•" in (aud_f[name]["raw"] or ""), name
        assert aud_f[name]["raw"] != off_f[name]["raw"]
    assert aud_f["sex"]["raw"] == off_f["sex"]["raw"]  # non-sensitive fields are not masked
    # no raw sensitive value leaks through any other part of the payload
    blob = str(aud)
    for secret in (off_f["surname"]["raw"], off_f["passport_number"]["raw"], off_f["mrz_line2"]["raw"],
                   off["mrz"]["parsed"]["surname"], off["mrz"]["parsed"]["passport_number"]):
        assert secret not in blob, secret
    assert aud["document"]["original_filename"] == "(hidden)"
    assert "•" in aud["mrz"]["lines"][1]
    holder = client.get(f"/api/v1/cases/{cid}", headers=auth["auditor"]).json()["holder"]
    assert off_f["surname"]["value"] not in holder


def test_admin_permissions(client, auth, core):
    cid = core["ids"]["clean"]
    ad = auth["admin"]
    assert client.post(f"/api/v1/cases/{cid}/review", headers=ad,
                       json={"outcome": "NO_ISSUES_FOUND", "rationale": "admins cannot review"}).status_code == 403
    assert client.post("/api/v1/cases", headers=ad, files={"file": ("a.jpg", core["sent"]["clean"], "image/jpeg")}).status_code == 403
    assert client.get(f"/api/v1/cases/{cid}/image?kind=original", headers=ad).status_code == 200
    assert client.get("/api/v1/audit", headers=ad).status_code == 200
    assert results(client, ad, cid)["pii_redacted"] is False


def test_officer_cannot_read_audit_log(client, auth):
    assert client.get("/api/v1/audit", headers=auth["officer"]).status_code == 403
    assert client.get("/api/v1/audit/verify", headers=auth["officer"]).status_code == 403


def test_unknown_case_404(client, auth):
    assert client.get("/api/v1/cases/does-not-exist", headers=auth["officer"]).status_code == 404


# ------------------------------------------------------------------ review
def test_review_requires_rationale_of_10_chars(client, auth, core):
    cid = core["ids"]["registry_unavailable"]
    h = auth["officer"]
    assert client.post(f"/api/v1/cases/{cid}/review", headers=h, json={"outcome": "NO_ISSUES_FOUND", "rationale": "short"}).status_code == 422
    assert client.post(f"/api/v1/cases/{cid}/review", headers=h, json={"outcome": "NO_ISSUES_FOUND", "rationale": "9 chars!!"}).status_code == 422
    assert client.post(f"/api/v1/cases/{cid}/review", headers=h, json={"outcome": "NO_ISSUES_FOUND"}).status_code == 422
    assert client.post(f"/api/v1/cases/{cid}/review", headers=h, json={"outcome": "SHRUG", "rationale": "long enough rationale"}).status_code == 422
    assert client.get(f"/api/v1/cases/{cid}", headers=h).json()["status"] != "REVIEWED"


def test_officer_review_recorded_and_audited(client, auth):
    from app.synthetic import samples
    cid = upload(client, auth["officer"], samples.sample_bytes("clean")[0])
    wait_done(client, auth["officer"], cid)
    r = client.post(f"/api/v1/cases/{cid}/review", headers=auth["officer"],
                    json={"outcome": "NO_ISSUES_FOUND", "rationale": "Checked all fields against the image."})
    assert r.status_code == 200 and r.json()["status"] == "REVIEWED"
    res = results(client, auth["officer"], cid)
    assert res["case"]["status"] == "REVIEWED" and res["reviews"][0]["outcome"] == "NO_ISSUES_FOUND"
    actions = [e["action"] for e in client.get(f"/api/v1/cases/{cid}/audit", headers=auth["auditor"]).json()["items"]]
    assert "review.submitted" in actions and "case.created" in actions and "pipeline.completed" in actions


# ------------------------------------------------------------------ officer corrections
def test_officer_correction_recomputes_checks_and_is_audited(client, auth):
    from app.synthetic import samples
    h = auth["officer"]
    cid = upload(client, h, samples.sample_bytes("edited_name")[0])
    wait_done(client, h, cid)
    res = results(client, h, cid)
    assert checks_of(res)["xc_surname"]["status"] == "FAIL"
    field = next(f for f in res["fields"] if f["name"] == "surname")
    mrz_surname = res["mrz"]["parsed"]["surname"]
    assert field["value"] != mrz_surname

    # officer fixes the (mis-read / edited) VIZ surname to the MRZ value -> mismatch disappears
    r = client.patch(f"/api/v1/cases/{cid}/fields/{field['id']}", headers=h,
                     json={"value": mrz_surname, "reason": "Re-read from the image"})
    assert r.status_code == 200, r.text
    assert r.json()["check_changes"]["xc_surname"] == {"from": "FAIL", "to": "PASS"}
    res2 = results(client, h, cid)
    assert checks_of(res2)["xc_surname"]["status"] == "PASS"
    f2 = next(f for f in res2["fields"] if f["name"] == "surname")
    assert f2["corrected_value"] == mrz_surname and f2["raw"] == field["raw"]  # raw OCR text preserved
    assert f2["corrections"][0]["reason"] == "Re-read from the image" and f2["corrections"][0]["previous"] == field["raw"]

    # and the reverse: a wrong correction creates a mismatch (corrections count as confident input)
    r = client.patch(f"/api/v1/cases/{cid}/fields/{field['id']}", headers=h, json={"value": "WRONGNAME", "reason": "typo test"})
    assert r.json()["check_changes"]["xc_surname"] == {"from": "PASS", "to": "FAIL"}

    audit = client.get(f"/api/v1/cases/{cid}/audit", headers=auth["auditor"]).json()["items"]
    corr = [e for e in audit if e["action"] == "field.corrected"]
    assert len(corr) == 2
    assert corr[1]["metadata"]["field"] == "surname"
    assert corr[1]["metadata"]["check_changes"]["xc_surname"] == ["FAIL", "PASS"]


def test_correction_requires_reason_and_permission(client, auth, core):
    cid = core["ids"]["clean"]
    res = results(client, auth["officer"], cid)
    fid = next(f["id"] for f in res["fields"] if f["name"] == "sex")
    url = f"/api/v1/cases/{cid}/fields/{fid}"
    assert client.patch(url, headers=auth["officer"], json={"value": "F", "reason": "x"}).status_code == 422
    assert client.patch(url, headers=auth["auditor"], json={"value": "F", "reason": "not allowed"}).status_code == 403
    assert client.patch(url, headers=auth["admin"], json={"value": "F", "reason": "not allowed"}).status_code == 403
    assert client.patch(f"/api/v1/cases/{cid}/fields/nope", headers=auth["officer"], json={"value": "F", "reason": "abc"}).status_code == 404


def test_mrz_line_correction_changes_digit_checks(client, auth):
    """Correcting an MRZ line to the true value clears the planted check-digit failure."""
    from app.synthetic import samples
    h = auth["officer"]
    cid = upload(client, h, samples.sample_bytes("bad_check_digit")[0])
    wait_done(client, h, cid)
    res = results(client, h, cid)
    assert checks_of(res)["mrz_cd_passport_number"]["status"] == "FAIL"
    line2 = next(f for f in res["fields"] if f["name"] == "mrz_line2")
    from app.modules.ocr_mrz.mrz import check_digit
    ocr_l2 = line2["value"]
    fixed = ocr_l2[:9] + check_digit(ocr_l2[:9]) + ocr_l2[10:]
    # composite digit depends on the passport-number digit as well; recompute it too
    fixed = fixed[:43] + check_digit(fixed[0:10] + fixed[13:20] + fixed[21:43])
    r = client.patch(f"/api/v1/cases/{cid}/fields/{line2['id']}", headers=h, json={"value": fixed, "reason": "Verified against image"})
    assert r.status_code == 200, r.text
    ch = r.json()["check_changes"]
    assert ch["mrz_cd_passport_number"] == {"from": "FAIL", "to": "PASS"}


# ------------------------------------------------------------------ report, audit
def test_pdf_report(client, auth, core):
    cid = core["ids"]["edited_name"]
    for who in ("officer", "auditor", "admin"):
        r = client.get(f"/api/v1/cases/{cid}/report", headers=auth[who])
        assert r.status_code == 200 and r.content.startswith(b"%PDF"), who
        assert r.headers["content-type"] == "application/pdf"
        assert b"%%EOF" in r.content[-64:]
    actions = [e["action"] for e in client.get("/api/v1/audit?action=report.exported", headers=auth["auditor"]).json()["items"]]
    assert actions


def test_audit_chain_verifies_and_detects_tampering(client, auth, core):
    from app.database.models import AuditEvent
    from app.database.session import SessionLocal
    v = client.get("/api/v1/audit/verify", headers=auth["auditor"]).json()
    assert v["valid"] is True and v["checked"] > 10 and v["first_broken_seq"] is None

    with SessionLocal() as db:
        ev = db.execute(select(AuditEvent).where(AuditEvent.action == "case.created").order_by(AuditEvent.seq)).scalars().first()
        seq, original = ev.seq, dict(ev.event_metadata or {})
        ev.event_metadata = {**original, "tampered": True}
        db.commit()
    try:
        broken = client.get("/api/v1/audit/verify", headers=auth["admin"]).json()
        assert broken["valid"] is False and broken["first_broken_seq"] == seq
    finally:
        with SessionLocal() as db:
            ev = db.execute(select(AuditEvent).where(AuditEvent.seq == seq)).scalar_one()
            ev.event_metadata = original
            db.commit()
    assert client.get("/api/v1/audit/verify", headers=auth["auditor"]).json()["valid"] is True


def test_audit_chain_detects_deleted_row(client, auth):
    from app.database.models import AuditEvent
    from app.database.session import SessionLocal
    from sqlalchemy import delete
    client.post("/api/v1/auth/login", json={"username": "officer", "password": "bad"})  # ensure a late, removable row
    with SessionLocal() as db:
        rows = db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().all()
        victim = rows[len(rows) // 2]
        saved = {c.name: getattr(victim, c.name) for c in AuditEvent.__table__.columns}
        db.execute(delete(AuditEvent).where(AuditEvent.seq == victim.seq))
        db.commit()
    try:
        v = client.get("/api/v1/audit/verify", headers=auth["auditor"]).json()
        assert v["valid"] is False
    finally:
        with SessionLocal() as db:
            db.execute(AuditEvent.__table__.insert().values(**saved))
            db.commit()
    assert client.get("/api/v1/audit/verify", headers=auth["auditor"]).json()["valid"] is True


def test_login_failures_and_case_creation_are_audited(client, auth):
    items = client.get("/api/v1/audit", headers=auth["auditor"]).json()["items"]
    actions = {e["action"] for e in items}
    assert {"auth.login", "case.created"} <= actions


def test_stats_and_list(client, auth, core):
    st = client.get("/api/v1/stats", headers=auth["officer"]).json()
    assert st["total"] >= 5 and "HIGH" in st["by_priority"]
    lst = client.get("/api/v1/cases?priority=HIGH", headers=auth["officer"]).json()
    assert lst["total"] >= 2 and all(i["priority"] == "HIGH" for i in lst["items"])


def test_recapture_supersedes_blurry_capture(client, auth, core):
    from app.synthetic import samples
    h = auth["officer"]
    cid = upload(client, h, samples.sample_bytes("blurry")[0])
    assert wait_done(client, h, cid)["status"] == "RECAPTURE_REQUIRED"
    r = client.post(f"/api/v1/cases/{cid}/recapture", headers=h, data={"rationale": "Retaken with steady hands"},
                    files={"file": ("again.jpg", samples.sample_bytes("clean")[0], "image/jpeg")})
    assert r.status_code == 202 and r.json()["capture_index"] == 2
    done = wait_done(client, h, cid)
    assert done["status"] == "COMPLETED" and done["priority"] == "LOW" and done["capture_count"] == 2
    docs = results(client, h, cid)["documents"]
    assert [d["superseded"] for d in docs] == [True, False]
