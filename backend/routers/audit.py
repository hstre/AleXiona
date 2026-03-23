"""Audit router — read-only access to the append-only audit trail.

GET /api/audit/claim/{claim_id}   → full provenance chain for one Claim
GET /api/audit/session/{session_id} → all AuditEvents for a session, newest first
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api_errors import internal_error, not_found
from auth import UserSession, require_user
from models import AuditEvent, AuditEventType, AuditTrailResponse
from neo4j_client import get_db

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _to_audit_event(row: dict) -> AuditEvent:
    return AuditEvent(
        id=row["id"],
        event_type=AuditEventType(row["event_type"]),
        claim_id=row["claim_id"],
        session_id=row["session_id"],
        actor=row["actor"],
        pipeline_stage=row["pipeline_stage"],
        timestamp=row["timestamp"],
        before=row.get("before"),
        after=row.get("after"),
        meta=row.get("meta") or {},
    )


@router.get("/claim/{claim_id}", response_model=AuditTrailResponse)
async def get_claim_audit_trail(
    claim_id: str,
    user: UserSession = Depends(require_user),
):
    """Return the full audit trail for a single Claim, oldest event first."""
    db = get_db()
    try:
        claim = db.get_claim_by_id(claim_id)
        if claim is None:
            raise not_found(f"Claim {claim_id!r} not found")
        # Enforce ownership: audit trails contain PHI — require a bound session token
        if not user.session_id:
            raise HTTPException(status_code=403, detail="Session binding required to access audit trail")
        if claim.get("session_id") != user.session_id:
            raise HTTPException(status_code=403, detail="Access denied")
        rows = db.get_claim_audit_trail(claim_id)
        return AuditTrailResponse(
            claim_id=claim_id,
            events=[_to_audit_event(r) for r in rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/session/{session_id}", response_model=AuditTrailResponse)
async def get_session_audit_trail(
    session_id: str,
    user: UserSession = Depends(require_user),
):
    """Return all AuditEvents for a session, oldest first."""
    if not user.session_id:
        raise HTTPException(status_code=403, detail="Session binding required to access audit trail")
    if user.session_id != session_id:
        raise HTTPException(status_code=403, detail="Access denied")
    db = get_db()
    try:
        rows = db.get_session_audit_trail(session_id)
        return AuditTrailResponse(
            session_id=session_id,
            events=[_to_audit_event(r) for r in rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)
