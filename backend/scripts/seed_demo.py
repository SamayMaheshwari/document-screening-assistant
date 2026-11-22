"""Seed demo users and cases. Run:  python -m scripts.seed_demo [--reset] [--all]"""
import os, sys
os.environ.setdefault("IDS_DEMO_STEP_DELAY", "0")
from app.core.config import get_settings
get_settings.cache_clear()
from sqlalchemy import select
from app.database.models import Base, User, ScreeningCase, OfficerReview
from app.database.session import SessionLocal, engine, init_db
from app.main import seed_users
from app.modules.intake.service import create_case
from app.orchestration.pipeline import run_pipeline
from app.audit.service import log_event
from app.synthetic import samples

def main():
    reset, extra = "--reset" in sys.argv, "--all" in sys.argv
    if reset:
        Base.metadata.drop_all(engine)
    init_db(); seed_users()
    db = SessionLocal()
    officer = db.execute(select(User).where(User.username == "officer")).scalar_one()
    if db.execute(select(ScreeningCase)).first():
        print("cases exist; use --reset to rebuild"); return
    order = ["clean", "bad_check_digit", "edited_name", "blurry", "registry_unavailable"]
    if extra:
        order += ["portrait_swap", "expired", "edited_dob", "stamp_edit", "rotated", "glare"]
    for v in order:
        b, meta = samples.sample_bytes(v)
        case, doc = create_case(db, officer, b, f"demo_{v}.jpg", label=f"[DEMO] {meta['title']}", demo_flags=samples.flags_for(v), capture_source="demo-sample")
        log_event(db, officer.display_name, "case.created", case.id, "officer", None, {"sha256": doc.sha256, "demo_sample": v})
        run_pipeline(case.id)
        db.refresh(case)
        print(f"{case.case_number:16} {v:22} {case.status:20} {case.risk[0].priority if case.risk else '-'}")
    db.close()

main()
