"""Audit Layer — append-only event log for every claim mutation.

Every Claim write (create / update / delete) must produce an AuditEvent so the
full provenance chain can be reconstructed from the graph.

Public API
----------
log_created_batch(claim_ids, claims, session_id, actor, pipeline_stage, meta)
log_updated(claim_id, session_id, actor, before, after, meta)
log_deleted(claim_id, session_id, actor, before, meta)

These functions are synchronous fire-and-forget from the perspective of the
calling router — failures are logged as warnings, never propagated to the
request.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from models import AuditActor, AuditEvent, AuditEventType, Claim

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _claim_snapshot(claim: Claim) -> dict:
    """Serialize a Claim to a plain dict for before/after storage."""
    return {
        "text":                   claim.text,
        "claim_type":             claim.claim_type.value if hasattr(claim.claim_type, "value") else str(claim.claim_type),
        "source_type":            claim.source_type.value if hasattr(claim.source_type, "value") else str(claim.source_type),
        "evidence_support_score": claim.evidence_support_score,
        "status":                 claim.status.value if hasattr(claim.status, "value") else str(claim.status),
        "evidence_tier":          claim.evidence_tier,
        "trend":                  claim.trend.value if hasattr(claim.trend, "value") else str(claim.trend),
        "uncertainty_flag":       claim.uncertainty_flag,
        "source_ref":             claim.source_ref,
        "normalized_token":       claim.normalized_token,
        "patient_data_ref":       claim.patient_data_ref,
        "supersedes_claim_id":    claim.supersedes_claim_id,
    }


def _store(event: AuditEvent) -> None:
    """Persist an AuditEvent to Neo4j.  Failures are non-fatal."""
    try:
        from neo4j_client import get_db
        get_db().store_audit_event(event)
    except Exception as exc:
        log.warning("audit_log: failed to store event %s: %s", event.id, exc)


# ── Public functions ──────────────────────────────────────────────────────────

def log_created_batch(
    claim_ids: Sequence[str],
    claims: Sequence[Claim],
    session_id: str,
    actor: str = AuditActor.system,
    pipeline_stage: str = "Stage 4: Graph persistence",
    meta: dict | None = None,
) -> list[AuditEvent]:
    """Log a claim_created event for each (claim_id, claim) pair."""
    events: list[AuditEvent] = []
    for cid, claim in zip(claim_ids, claims):
        event = AuditEvent(
            id=str(uuid.uuid4()),
            event_type=AuditEventType.claim_created,
            claim_id=cid,
            session_id=session_id,
            actor=actor,
            pipeline_stage=pipeline_stage,
            timestamp=_now(),
            before=None,
            after=_claim_snapshot(claim),
            meta=meta or {},
        )
        _store(event)
        events.append(event)
    return events


def log_updated(
    claim_id: str,
    session_id: str,
    actor: str = AuditActor.graph_manual,
    before: dict | None = None,
    after: dict | None = None,
    meta: dict | None = None,
) -> AuditEvent:
    """Log a claim_updated event."""
    event = AuditEvent(
        id=str(uuid.uuid4()),
        event_type=AuditEventType.claim_updated,
        claim_id=claim_id,
        session_id=session_id,
        actor=actor,
        pipeline_stage="Manual edit",
        timestamp=_now(),
        before=before,
        after=after,
        meta=meta or {},
    )
    _store(event)
    return event


def log_deleted(
    claim_id: str,
    session_id: str,
    actor: str = AuditActor.graph_manual,
    before: dict | None = None,
    meta: dict | None = None,
) -> AuditEvent:
    """Log a claim_deleted event."""
    event = AuditEvent(
        id=str(uuid.uuid4()),
        event_type=AuditEventType.claim_deleted,
        claim_id=claim_id,
        session_id=session_id,
        actor=actor,
        pipeline_stage="Manual deletion",
        timestamp=_now(),
        before=before,
        after=None,
        meta=meta or {},
    )
    _store(event)
    return event
