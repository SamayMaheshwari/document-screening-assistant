from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api.routes import router
from app.core.config import PROJECT_DIR, get_settings
from app.core.security import hash_password
from app.database.models import User
from app.database.session import SessionLocal, init_db

DEMO_USERS = [("officer", "Officer Ananya Singh", "officer", "officer"),
              ("officer2", "Officer Daniel Okafor", "officer", "officer"),
              ("admin", "Admin Priya Nair", "admin", "admin"),
              ("auditor", "Auditor Lucas Meyer", "auditor", "auditor")]


def seed_users():
    db = SessionLocal()
    try:
        for username, name, role, pw in DEMO_USERS:
            if not db.execute(select(User).where(User.username == username)).scalar_one_or_none():
                db.add(User(username=username, display_name=name, role=role, password_hash=hash_password(pw)))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_users()
    threading.Thread(target=lambda: __import__("app.modules.ocr_mrz.extract", fromlist=["x"]).get_engine(), daemon=True).start()
    yield


app = FastAPI(title="Document Screening Assistant API", version="0.1.0-demo", lifespan=lifespan,
              description="Decision-support prototype. Synthetic data only.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse({"detail": {"code": "server_error", "message": "Unexpected server error."}}, status_code=500)


# Serve the built frontend if present (single-process demo); otherwise use `npm run dev`
DIST = PROJECT_DIR / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        return FileResponse(f if f.is_file() else DIST / "index.html")
