"""LLM configuration router.

GET  /api/config/llm       — current provider/model (no key value returned)
POST /api/config/llm       — reconfigure provider, key, model, base_url at runtime
POST /api/config/llm/test  — make a minimal LLM call to verify the configuration
"""
from __future__ import annotations

import time
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import UserSession, require_clinician
from llm_config import get_model, get_provider_info, reconfigure, _PRESETS

log    = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/config", tags=["config"])

_VALID_PROVIDERS = list(_PRESETS.keys())


class LLMConfigRequest(BaseModel):
    provider: str
    api_key:  str = ""
    model:    str = ""
    base_url: str = ""


@router.get("/llm")
def get_llm_config(_user: UserSession = Depends(require_clinician)):
    """Return the active LLM provider and model.  API key is never returned."""
    return get_provider_info()


@router.post("/llm")
def update_llm_config(
    body:  LLMConfigRequest,
    _user: UserSession = Depends(require_clinician),
):
    """Reconfigure the active LLM client.  Takes effect immediately, no restart needed."""
    if body.provider not in _VALID_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown provider '{body.provider}'. Valid: {', '.join(_VALID_PROVIDERS)}",
        )
    try:
        reconfigure(body.provider, body.api_key, body.model, body.base_url)
        log.info("llm_reconfigured_via_api", provider=body.provider)
        return get_provider_info()
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/test")
def test_llm_config(_user: UserSession = Depends(require_clinician)):
    """Make a minimal LLM call to verify the current configuration works."""
    from llm_config import sync_client
    t0 = time.time()
    try:
        sync_client.chat.completions.create(
            model=get_model(),
            messages=[{"role": "user", "content": "Reply with one word: ok"}],
            max_tokens=5,
            temperature=0.0,
            timeout=10.0,
        )
        latency_ms = int((time.time() - t0) * 1000)
        log.info("llm_test_ok", latency_ms=latency_ms)
        return {"ok": True, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - t0) * 1000)
        log.warning("llm_test_failed", error=str(e))
        return {"ok": False, "error": str(e), "latency_ms": latency_ms}
