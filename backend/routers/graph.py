from fastapi import APIRouter, HTTPException
from models import GraphData, NodeUpdate, CounterfactualResult, Claim, ClaimType, SourceType, ClaimStatus, ClaimTrend, _clamp_ess, _normalize_time_offset
from pydantic import BaseModel, field_validator
from typing import Optional
from neo4j_client import get_db
from llm_client import run_counterfactual, analyze_reasoning
from conflict_engine import detect_conflicts
from api_errors import internal_error, validation_error, not_found


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
            existing_ids = {c["id"] for c in db.get_all_claims_for_session(session_id)}
            unknown = [i for i in payload.derived_from if i not in existing_ids]
            if unknown:
                raise validation_error(
                    f"Unknown claim IDs in derived_from: {unknown}",
                    code="invalid_derived_from",
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


@router.patch("/claim/{claim_id}")
async def update_claim(claim_id: str, update: NodeUpdate):
    try:
        get_db().update_claim(claim_id, update.model_dump(exclude_none=True))
        return {"status": "updated"}
    except Exception as e:
        raise internal_error(e)


@router.delete("/claim/{claim_id}")
async def delete_claim(claim_id: str):
    try:
        get_db().delete_claim(claim_id)
        return {"status": "deleted"}
    except Exception as e:
        raise internal_error(e)
