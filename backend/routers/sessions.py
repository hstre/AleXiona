from fastapi import APIRouter, HTTPException
from neo4j_client import Neo4jClient

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions():
    db = Neo4jClient()
    try:
        return db.list_sessions()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    db = Neo4jClient()
    try:
        db.delete_session(session_id)
        return {"status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
