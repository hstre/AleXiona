"""Auth router — session token creation and introspection."""

import os
import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from auth import create_token, decode_token, require_user, UserSession

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# When set, clinician tokens require this secret in X-Bootstrap-Secret header.
# Leave unset in development to keep the open-access behaviour.
_BOOTSTRAP_SECRET = os.getenv("CLINICIAN_BOOTSTRAP_SECRET", "")


class SessionRequest(BaseModel):
    role:       str = "clinician"   # "clinician" | "demo"
    session_id: str = ""            # clinical session UUID to bind to this token


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

    # Gate clinician tokens behind bootstrap secret when configured in production.
    if body.role == "clinician" and _BOOTSTRAP_SECRET:
        provided = request.headers.get("X-Bootstrap-Secret", "")
        if provided != _BOOTSTRAP_SECRET:
            log.warning("clinician_bootstrap_rejected",
                        remote=request.client.host if request.client else "unknown")
            raise HTTPException(status_code=403, detail="Access denied")

    sid   = body.session_id or str(uuid.uuid4())
    token = create_token(body.role, sid)
    # Decode to extract the generated user_id without storing state
    user = decode_token(token)

    log.info("session_created", user_id=user.user_id, role=user.role,
             remote=request.client.host if request.client else "unknown")
    return SessionResponse(token=token, user_id=user.user_id, role=user.role)


@router.get("/session", response_model=SessionResponse)
def introspect_session(user: UserSession = Depends(require_user)):
    """Return the currently authenticated user's session info."""
    return SessionResponse(token="", user_id=user.user_id, role=user.role)
