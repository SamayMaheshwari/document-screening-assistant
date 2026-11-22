"""Stubbed auth with roles (real IdP + MFA later). Demo accounts only."""
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database.models import User
from app.database.session import get_db

PERMISSIONS = {
    "officer": {"case:create", "case:read", "case:review", "case:recapture", "case:report",
                "field:correct", "pii:full"},
    "admin": {"case:read", "case:report", "audit:read", "users:read", "pii:full"},
    "auditor": {"case:read", "case:report", "audit:read"},  # PII is redacted for auditors
}


def hash_password(pw: str) -> str:
    return hashlib.sha256(("demo-salt:" + pw).encode()).hexdigest()


def verify_password(pw: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_password(pw), hashed)


def make_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.token_ttl_minutes)
    return jwt.encode({"sub": user.id, "role": user.role, "exp": exp}, s.secret_key, algorithm="HS256")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired session")
    user = db.get(User, data["sub"])
    if not user or user.status != "active":
        raise HTTPException(401, "Unknown user")
    return user


def require(permission: str):
    def dep(user: User = Depends(current_user)) -> User:
        if permission not in PERMISSIONS.get(user.role, set()):
            raise HTTPException(403, f"Role '{user.role}' lacks permission '{permission}'")
        return user
    return dep


def can_see_pii(user: User) -> bool:
    return "pii:full" in PERMISSIONS.get(user.role, set())
