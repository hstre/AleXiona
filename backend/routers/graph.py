from fastapi import APIRouter, HTTPException
from models import GraphData, NodeUpdate, CounterfactualResult
from neo4j_client import Neo4jClient
from llm_client import run_counterfactual, analyze_reasoning
from conflict_engine import detect_conflicts

router = APIRouter(prefix="/api/graph", tags=["graph"])


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
