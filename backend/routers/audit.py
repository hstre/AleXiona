"""Audit router — read-only access to the append-only audit trail.

GET /api/audit/claim/{claim_id}   → full provenance chain for one Claim
GET /api/audit/session/{session_id} → all AuditEvents for a session, newest first
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api_errors import internal_error, not_found
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
async def get_claim_audit_trail(claim_id: str):
    """Return the full audit trail for a single Claim, oldest event first."""
    db = get_db()
    try:
        rows = db.get_claim_audit_trail(claim_id)
        if not rows:
            # Check whether the claim itself exists to distinguish 404 vs empty log
            if db.get_claim_by_id(claim_id) is None:
                raise not_found(f"Claim {claim_id!r} not found")
        return AuditTrailResponse(
            claim_id=claim_id,
            events=[_to_audit_event(r) for r in rows],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/session/{session_id}", response_model=AuditTrailResponse)
async def get_session_audit_trail(session_id: str):
    """Return all AuditEvents for a session, oldest first."""
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
