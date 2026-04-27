from fastapi import APIRouter

from api_errors import internal_error
from neo4j_client import get_db

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions():
    try:
        return get_db().list_sessions()
    except Exception as e:
        raise internal_error(e)


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    try:
        get_db().delete_session(session_id)
        return {"status": "deleted"}
    except Exception as e:
        raise internal_error(e)
