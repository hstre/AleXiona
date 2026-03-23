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
    """Delete a session.  Ownership enforced by explicit check and middleware."""
    # Middleware enforces token.sid == path sid when token carries a session_id.
    # Explicit check covers the edge case of tokens without a bound session_id
    # (old/demo tokens) which would otherwise bypass the middleware guard.
    if not user.session_id or user.session_id != session_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        get_db().delete_session(session_id)
        return {"status": "deleted"}
    except Exception as e:
        raise internal_error(e)
