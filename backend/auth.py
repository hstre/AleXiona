"""
Minimal session-token auth for AleXiona.

Design goals
    - No JWT complexity (no public-key crypto, no JWKS, no token refresh dance)
    - Signed server-side: token cannot be forged without SECRET_KEY
    - Stateless validation: no DB round-trip on every request
    - Two roles: clinician | demo
    - Easy to swap later for a full auth service

Token format
    itsdangerous URLSafeTimedSerializer(SECRET_KEY)
    Payload: {"uid": "<uuid>", "role": "clinician" | "demo"}
    Signed with HMAC-SHA1, max age = SESSION_MAX_AGE_HOURS (default 12)

Usage
    # Any protected endpoint:
    from auth import require_user
    from fastapi import Depends

    @router.get("/protected")
    def endpoint(user: UserSession = Depends(require_user)):
        ...

    # LLM endpoints additionally call require_clinician to reject demo tokens:
    @router.post("/expensive")
    def endpoint(user: UserSession = Depends(require_clinician)):
        ...
"""

import os
import uuid
import structlog
from dataclasses import dataclass
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Depends, HTTPException, Request, status

log = structlog.get_logger(__name__)

_SECRET_KEY    = os.getenv("SECRET_KEY", "change-me-in-production-please")
_MAX_AGE       = int(os.getenv("SESSION_MAX_AGE_HOURS", "12")) * 3600
_SALT          = "alexiona-session-v1"

_serializer = URLSafeTimedSerializer(_SECRET_KEY, salt=_SALT)

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class UserSession:
    user_id: str
    role:    str          # "clinician" | "demo"

    @property
    def is_clinician(self) -> bool:
        return self.role == "clinician"

# ── Token helpers ─────────────────────────────────────────────────────────────

def create_token(role: str) -> str:
    """Create a signed, time-limited session token."""
    if role not in ("clinician", "demo"):
        raise ValueError(f"Unknown role: {role!r}")
    payload = {"uid": str(uuid.uuid4()), "role": role}
    return _serializer.dumps(payload)


def decode_token(token: str) -> UserSession:
    """Decode and validate a session token.  Raises ValueError on any problem."""
    try:
        payload = _serializer.loads(token, max_age=_MAX_AGE)
    except SignatureExpired:
        raise ValueError("Session expired — please log in again")
    except BadSignature:
        raise ValueError("Invalid session token")
    return UserSession(user_id=payload["uid"], role=payload["role"])

# ── FastAPI dependencies ───────────────────────────────────────────────────────

def _extract_token(request: Request) -> str | None:
    """Read token from Authorization header or X-Session-Token."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.headers.get("X-Session-Token")


def require_user(request: Request) -> UserSession:
    """FastAPI dependency: require a valid session token (any role)."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session token required")
    try:
        user = decode_token(token)
    except ValueError as e:
        log.warning("auth_failed", reason=str(e),
                    remote=request.client.host if request.client else "unknown")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=str(e))
    return user


def require_clinician(request: Request) -> UserSession:
    """FastAPI dependency: require clinician role (rejects demo tokens)."""
    user = require_user(request)
    if not user.is_clinician:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Clinician access required")
    return user
