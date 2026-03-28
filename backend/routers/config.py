"""LLM configuration router.

GET  /api/config/llm       — current provider/model (no key value returned)
POST /api/config/llm       — reconfigure provider, key, model, base_url at runtime
POST /api/config/llm/test  — make a minimal LLM call to verify the configuration
"""
from __future__ import annotations

import time
import structlog
import httpx
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth import UserSession, require_clinician
from llm_config import get_model, get_provider_info, reconfigure, sync_client, _PRESETS

log    = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/config", tags=["config"])

_VALID_PROVIDERS = list(_PRESETS.keys())

# Only allow Ollama discovery against local hosts to prevent SSRF.
_ALLOWED_OLLAMA_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _validate_ollama_url(url: str) -> None:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    if host not in _ALLOWED_OLLAMA_HOSTS:
        raise HTTPException(
            status_code=422,
            detail="base_url must point to a local host (localhost, 127.0.0.1, host.docker.internal)",
        )


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
        log.error("llm_reconfigure_error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Konfiguration konnte nicht gespeichert werden.")


@router.post("/llm/test")
def test_llm_config(_user: UserSession = Depends(require_clinician)):
    """Make a minimal LLM call to verify the current configuration works."""
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


@router.get("/ollama/models")
async def get_ollama_models(
    base_url: str = Query(default="http://localhost:11434/v1"),
    _user: UserSession = Depends(require_clinician),
):
    """Fetch available model names from a running Ollama instance.

    Returns {"models": [...]} — empty list if Ollama is unreachable.
    """
    _validate_ollama_url(base_url)
    # Strip /v1 suffix to get the Ollama base (e.g. http://localhost:11434)
    tags_base = base_url.rstrip("/")
    if tags_base.endswith("/v1"):
        tags_base = tags_base[:-3]
    tags_url = f"{tags_base}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(tags_url)
            resp.raise_for_status()
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return {"models": models}
    except Exception as exc:
        log.info("ollama_models_unavailable", url=tags_url, error=str(exc))
        return {"models": []}
