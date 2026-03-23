from fastapi import APIRouter, Depends, Request
from neo4j_client import get_db
from api_errors import internal_error
from auth import UserSession, require_user
from rate_limit import limiter

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
@limiter.limit("20/minute")
async def list_sessions(request: Request, user: UserSession = Depends(require_user)):
    """Return only the session belonging to the current token."""
    try:
        if not user.session_id:
            # Token has no bound session_id (e.g. old/demo token) → expose nothing
            return []
        sessions = get_db().list_sessions()
        return [s for s in sessions if s.get("session_id") == user.session_id]
    except Exception as e:
        raise internal_error(e)


@router.delete("/{session_id}")
@limiter.limit("5/minute")
async def delete_session(session_id: str, request: Request, user: UserSession = Depends(require_user)):
    """Delete a session.  Ownership enforced by middleware (token.sid == path sid) and require_user."""
    try:
        get_db().delete_session(session_id)
        return {"status": "deleted"}
    except Exception as e:
        raise internal_error(e)
