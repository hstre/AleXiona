import os
import uuid as _uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

load_dotenv()

# ── Logging (must happen before any other import that creates a logger) ────────
from log_config import configure_logging
configure_logging()

import structlog
log = structlog.get_logger(__name__)

# ── Sentry (errors only, disabled if SENTRY_DSN not set) ──────────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(),
        ],
        # Only capture unhandled exceptions — no performance tracing
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        send_default_pii=False,   # GDPR: no PII in Sentry payloads
    )
    log.info("sentry_enabled", dsn=_SENTRY_DSN[:20] + "…")
else:
    log.info("sentry_disabled", hint="set SENTRY_DSN env var to enable")

# ── Rate limiting (slowapi) ───────────────────────────────────────────────────
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from rate_limit import limiter

# ── App + router imports ──────────────────────────────────────────────────────
from routers import chat, graph, sessions, demo, intake, audit
from routers.auth import router as auth_router
from routers.config import router as config_router
from auth import decode_token


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup", service="AleXiona Backend")
    yield
    log.info("shutdown", service="AleXiona Backend")
    try:
        from neo4j_client import _instance
        if _instance is not None:
            _instance.close()
    except Exception as exc:
        log.warning("neo4j_shutdown_failed", error=str(exc), exc_info=True)


app = FastAPI(title="AleXiona API", version="0.1.0", lifespan=lifespan)

# Attach rate-limiter state and error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
_allowed_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-Session-Token"],
)

# ── Auth middleware ───────────────────────────────────────────────────────────
# Public paths that do not require a session token.
_PUBLIC_PATHS = {"/health", "/api/auth/session", "/api/graph/report-types"}


def _path_session_id(path: str) -> str | None:
    """
    Extract the session_id UUID segment from API paths such as
      /api/graph/{session_id}/...
      /api/sessions/{session_id}
      /api/chat/{session_id}
    Returns None when the path carries no session_id (e.g. /api/sessions list).
    """
    parts = [p for p in path.split("/") if p]
    # parts: ['api', '<router>', '<maybe-session-id>', ...]
    if len(parts) >= 3:
        candidate = parts[2]
        try:
            _uuid.UUID(candidate)
            return candidate
        except ValueError:
            pass
    return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    Validate session token on every request except public paths.
    Missing or invalid token → HTTP 401.
    Mismatched session_id (token vs URL path) → HTTP 403.
    """
    path = request.url.path
    if path in _PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)

    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.headers.get("X-Session-Token")

    if token:
        try:
            user = decode_token(token)
            request.state.user = user
            # Bind user context to all log records in this request
            structlog.contextvars.bind_contextvars(
                user_id=user.user_id, role=user.role
            )
        except ValueError as e:
            log.warning("auth_invalid_token", reason=str(e), path=path)
            return JSONResponse({"detail": str(e)}, status_code=401)
    else:
        log.warning("auth_anonymous", path=path)
        return JSONResponse({"detail": "Session token required"}, status_code=401)

    # Session ownership check: if the token carries a session_id (sid) and the
    # URL contains a UUID in the session_id position, they must match.
    if user.session_id:
        path_sid = _path_session_id(path)
        if path_sid and path_sid != user.session_id:
            log.warning("session_mismatch",
                        token_sid=user.session_id, path_sid=path_sid, path=path)
            return JSONResponse({"detail": "Access denied"}, status_code=403)

    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    return response

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(sessions.router)
app.include_router(demo.router)
app.include_router(intake.router)
app.include_router(audit.router)
app.include_router(config_router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "AleXiona Backend"}
