"""Append-only, hash-chained audit log (PDF s.10). Rows are only ever inserted."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import AuditEvent


def _hash(prev: str, row: dict) -> str:
    payload = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256((prev + payload).encode()).hexdigest()


def _row(e: AuditEvent) -> dict:
    return {"id": e.id, "timestamp": e.timestamp.replace(microsecond=0).isoformat(), "actor": e.actor,
            "actor_role": e.actor_role, "action": e.action, "case_id": e.case_id,
            "request_id": e.request_id, "metadata": e.event_metadata}


def log_event(db: Session, actor: str, action: str, case_id: str | None = None, role: str = "system",
              request_id: str | None = None, metadata: dict | None = None) -> AuditEvent:
    last = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    prev = last.event_hash if last else "GENESIS"
    ev = AuditEvent(actor=actor, actor_role=role, action=action, case_id=case_id, request_id=request_id,
                    event_metadata=metadata or {}, prev_hash=prev)
    db.add(ev)
    db.flush()
    ev.event_hash = _hash(prev, _row(ev))
    db.commit()
    return ev


def verify_chain(db: Session) -> dict:
    events = db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars().all()
    prev = "GENESIS"
    for e in events:
        if e.prev_hash != prev or e.event_hash != _hash(prev, _row(e)):
            return {"valid": False, "checked": len(events), "first_broken_seq": e.seq}
        prev = e.event_hash
    return {"valid": True, "checked": len(events), "first_broken_seq": None}
