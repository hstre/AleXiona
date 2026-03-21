from fastapi import APIRouter, HTTPException
from models import GraphData, NodeUpdate, CounterfactualResult, HypothesisCounterfactualResult, Claim, ClaimType, SourceType, ClaimStatus, ClaimTrend, _clamp_ess, _normalize_time_offset, _parse_offset_hours, AuditActor
from pydantic import BaseModel, field_validator
from typing import Optional
from neo4j_client import get_db
from llm_client import run_counterfactual, run_hypothesis_counterfactual, analyze_reasoning, explain_conflict as _explain_conflict
from conflict_engine import detect_conflicts
from api_errors import internal_error, validation_error, not_found
from audit_log import log_created_batch, log_updated, log_deleted


class ManualClaimPayload(BaseModel):
    text:                   str
    claim_type:             ClaimType   = ClaimType.finding
    source_type:            SourceType  = SourceType.clinician
    source_ref:             str         = ""
    evidence_support_score: float       = 0.8
    time_offset:            Optional[str] = None
    trend:                  ClaimTrend  = ClaimTrend.unknown
    status:                 ClaimStatus = ClaimStatus.active
    derived_from:           list[str]   = []   # explicit claimIds chosen by the user

    @field_validator('evidence_support_score', mode='before')
    @classmethod
    def clamp_ess(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator('time_offset', mode='before')
    @classmethod
    def normalize_offset(cls, v: str | None) -> str | None:
        return _normalize_time_offset(v)


router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.post("/{session_id}/claims")
async def add_manual_claim(session_id: str, payload: ManualClaimPayload):
    db = get_db()
    try:
        if payload.derived_from:
            existing_claims = db.get_all_claims_for_session(session_id)
            existing_by_id  = {c["id"]: c for c in existing_claims}
            unknown = [i for i in payload.derived_from if i not in existing_by_id]
            if unknown:
                raise validation_error(
                    f"Unknown claim IDs in derived_from: {unknown}",
                    code="invalid_derived_from",
                )
            # Temporal consistency: new claim must not be earlier than any source
            child_h = _parse_offset_hours(payload.time_offset)
            if child_h is not None:
                for src_id in payload.derived_from:
                    src_h = _parse_offset_hours(existing_by_id[src_id].get("time_offset"))
                    if src_h is not None and child_h < src_h:
                        raise validation_error(
                            f"time_offset t+{child_h}h is earlier than source claim's "
                            f"t+{src_h}h — a derived claim cannot precede its source.",
                            code="temporal_inconsistency",
                        )
        claim = Claim(
            text=payload.text,
            entities=[], relations=[],
            evidence_support_score=payload.evidence_support_score,
            claim_type=payload.claim_type,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            status=payload.status,
            time_offset=payload.time_offset,
            trend=payload.trend,
            derived_from=payload.derived_from,
        )
        new_ids = db.store_claims([claim], session_id)
        if payload.derived_from and new_ids:
            db.link_explicit_derived_from(new_ids[0], payload.derived_from)
        log_created_batch(
            new_ids, [claim], session_id,
            actor=AuditActor.graph_manual,
            pipeline_stage="Manual claim creation via graph router",
        )
        return {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}", response_model=GraphData)
async def get_graph(session_id: str):
    try:
        return get_db().get_graph(session_id)
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/conflicts")
async def get_conflicts(session_id: str):
    try:
        claims = get_db().get_all_claims_for_session(session_id)
        return detect_conflicts(claims)
    except Exception as e:
        raise internal_error(e)


class HypothesisCounterfactualPayload(BaseModel):
    hypothesis: str


@router.post("/{session_id}/counterfactual/hypothesis", response_model=HypothesisCounterfactualResult)
async def hypothesis_counterfactual(session_id: str, payload: HypothesisCounterfactualPayload):
    """Ask: 'What would need to change for this hypothesis to be false?'"""
    db = get_db()
    try:
        all_claims = db.get_all_claims_for_session(session_id)
        result = run_hypothesis_counterfactual(payload.hypothesis, all_claims)
        if not result:
            raise validation_error("Could not compute hypothesis counterfactual",
                                   code="counterfactual_failed")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.post("/{session_id}/counterfactual/{claim_id}", response_model=CounterfactualResult)
async def counterfactual(session_id: str, claim_id: str):
    db = get_db()
    try:
        all_claims = db.get_all_claims_for_session(session_id)
        original_reasoning = analyze_reasoning(all_claims)
        if not original_reasoning:
            raise validation_error("Insufficient claims for counterfactual analysis",
                                   code="insufficient_claims")
        result = run_counterfactual(all_claims, original_reasoning, claim_id)
        if not result:
            raise not_found("Claim not found in session")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/entity-duplicates")
async def get_entity_duplicates(session_id: str):
    try:
        return get_db().get_entity_groups(session_id)
    except Exception as e:
        raise internal_error(e)


class MergeEntitiesPayload(BaseModel):
    canonical: str
    aliases:   list[str]


@router.post("/{session_id}/entities/merge")
async def merge_entities(session_id: str, payload: MergeEntitiesPayload):
    try:
        merged = get_db().merge_entities(payload.canonical, payload.aliases)
        return {"merged": merged}
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/export")
async def export_session(session_id: str):
    try:
        return get_db().export_session(session_id)
    except Exception as e:
        raise internal_error(e)


class ImportPayload(BaseModel):
    claims: list[dict]


@router.post("/{session_id}/import")
async def import_session(session_id: str, payload: ImportPayload):
    try:
        result = get_db().import_session(session_id, payload.claims)
        return result
    except Exception as e:
        raise internal_error(e)


class ConflictExplainPayload(BaseModel):
    type:                str
    severity:            str
    message:             str
    affected_claim_ids:  list[str] = []


@router.post("/{session_id}/conflicts/explain")
async def explain_conflict(session_id: str, payload: ConflictExplainPayload):
    try:
        claims = get_db().get_all_claims_for_session(session_id)
        explanation = _explain_conflict(payload.model_dump(), claims)
        if not explanation:
            raise validation_error("LLM explanation unavailable", code="llm_unavailable")
        return {"explanation": explanation}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/claims/{claim_id}/chain")
async def get_claim_chain(session_id: str, claim_id: str):
    """Return all claim IDs reachable via DERIVES_FROM edges (ancestors + descendants)."""
    try:
        db = get_db()
        claims = db.get_all_claims_for_session(session_id)
        claim_ids = {c["id"] for c in claims}
        if claim_id not in claim_ids:
            raise not_found("Claim not found in session")
        # Build adjacency from derived_from lists (stored on each claim)
        parents:  dict[str, list[str]] = {}   # claim -> list of sources it derives from
        children: dict[str, list[str]] = {}   # claim -> list of claims that derive from it
        for c in claims:
            cid = c["id"]
            parents.setdefault(cid, [])
            children.setdefault(cid, [])
            for src in c.get("derived_from") or []:
                if src in claim_ids:
                    parents[cid].append(src)
                    children.setdefault(src, []).append(cid)

        visited: set[str] = set()
        queue = [claim_id]
        while queue:
            cur = queue.pop()
            if cur in visited:
                continue
            visited.add(cur)
            queue.extend(parents.get(cur, []))
            queue.extend(children.get(cur, []))

        chain = list(visited - {claim_id})
        return {"claim_id": claim_id, "chain": chain}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.patch("/claim/{claim_id}")
async def update_claim(claim_id: str, update: NodeUpdate):
    db = get_db()
    try:
        before = db.get_claim_by_id(claim_id)
        session_id = (before or {}).get("session_id", "")
        changes = update.model_dump(exclude_none=True)
        db.update_claim(claim_id, changes)
        after = db.get_claim_by_id(claim_id)
        log_updated(
            claim_id, session_id,
            actor=AuditActor.graph_manual,
            before=before,
            after=after,
            meta={"changed_fields": list(changes.keys())},
        )
        return {"status": "updated"}
    except Exception as e:
        raise internal_error(e)


@router.delete("/claim/{claim_id}")
async def delete_claim(claim_id: str):
    db = get_db()
    try:
        before = db.get_claim_by_id(claim_id)
        session_id = (before or {}).get("session_id", "")
        db.delete_claim(claim_id)
        log_deleted(
            claim_id, session_id,
            actor=AuditActor.graph_manual,
            before=before,
        )
        return {"status": "deleted"}
    except Exception as e:
        raise internal_error(e)
