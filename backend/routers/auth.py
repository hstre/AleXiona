"""Auth router — session token creation and introspection."""

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from auth import create_token, require_user, UserSession
from fastapi import Depends

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SessionRequest(BaseModel):
    role: str = "clinician"   # "clinician" | "demo"


class SessionResponse(BaseModel):
    token:   str
    user_id: str
    role:    str


@router.post("/session", response_model=SessionResponse)
def create_session(body: SessionRequest, request: Request):
    """
    Issue a new signed session token.

    Body: {"role": "clinician"}   →  clinician session (full access)
    Body: {"role": "demo"}        →  demo session (read + seed only)

    In a production deployment this endpoint would verify credentials
    before issuing a token.  For now it trusts the caller.
    """
    if body.role not in ("clinician", "demo"):
        raise HTTPException(status_code=422, detail="role must be 'clinician' or 'demo'")

    token = create_token(body.role)
    # Decode to extract the generated user_id without storing state
    from auth import decode_token
    user = decode_token(token)

    log.info("session_created", user_id=user.user_id, role=user.role,
             remote=request.client.host if request.client else "unknown")
    return SessionResponse(token=token, user_id=user.user_id, role=user.role)


@router.get("/session", response_model=SessionResponse)
def introspect_session(user: UserSession = Depends(require_user)):
    """Return the currently authenticated user's session info."""
    return SessionResponse(token="", user_id=user.user_id, role=user.role)
