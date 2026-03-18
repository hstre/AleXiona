from fastapi import APIRouter, HTTPException
from models import GraphData, NodeUpdate
from neo4j_client import Neo4jClient

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
