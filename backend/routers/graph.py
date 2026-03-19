from fastapi import APIRouter, HTTPException
from models import GraphData, NodeUpdate, CounterfactualResult, Claim, ClaimType, SourceType, ClaimStatus, ClaimTrend
from pydantic import BaseModel
from typing import Optional
from neo4j_client import Neo4jClient
from llm_client import run_counterfactual, analyze_reasoning
from conflict_engine import detect_conflicts


class ManualClaimPayload(BaseModel):
    text:                   str
    claim_type:             ClaimType   = ClaimType.finding
    source_type:            SourceType  = SourceType.clinician
    source_ref:             str         = ""
    evidence_support_score: float       = 0.8
    time_offset:            Optional[str] = None
    trend:                  ClaimTrend  = ClaimTrend.unknown
    status:                 ClaimStatus = ClaimStatus.active

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.post("/{session_id}/claims")
async def add_manual_claim(session_id: str, payload: ManualClaimPayload):
    db = Neo4jClient()
    try:
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
        )
        db.store_claims([claim], session_id)
        return {"status": "created"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{session_id}", response_model=GraphData)
async def get_graph(session_id: str):
    db = Neo4jClient()
    try:
        return db.get_graph(session_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{session_id}/conflicts")
async def get_conflicts(session_id: str):
    db = Neo4jClient()
    try:
        claims = db.get_all_claims_for_session(session_id)
        return detect_conflicts(claims)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/{session_id}/counterfactual/{claim_id}", response_model=CounterfactualResult)
async def counterfactual(session_id: str, claim_id: str):
    db = Neo4jClient()
    try:
        all_claims = db.get_all_claims_for_session(session_id)
        original_reasoning = analyze_reasoning(all_claims)
        if not original_reasoning:
            raise HTTPException(status_code=422, detail="Insufficient claims for counterfactual analysis")
        result = run_counterfactual(all_claims, original_reasoning, claim_id)
        if not result:
            raise HTTPException(status_code=404, detail="Claim not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.patch("/claim/{claim_id}")
async def update_claim(claim_id: str, update: NodeUpdate):
    db = Neo4jClient()
    try:
        db.update_claim(claim_id, update.text)
        return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.patch("/claim/{claim_id}/status")
async def update_claim_status(claim_id: str, payload: dict):
    db = Neo4jClient()
    try:
        db.update_claim_status(claim_id, payload.get("status", "active"))
        return {"status": "updated"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/claim/{claim_id}")
async def delete_claim(claim_id: str):
    db = Neo4jClient()
    try:
        db.delete_claim(claim_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
