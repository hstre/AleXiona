"""
LLM provider configuration for AleXiona.

Supported providers and the required environment variables:

  LLM_PROVIDER   Which provider to use. Defaults to "openai".
                 Values: openai | groq | mistral | ollama |
                         openai_compatible | anthropic

  LLM_MODEL      Model name, overrides the provider default.

  LLM_API_KEY    API key. Falls back to OPENAI_API_KEY for backwards
                 compatibility. Not required for ollama (local, no auth).
                 Can also be set at runtime via POST /api/config/llm.

  LLM_BASE_URL   Base URL for openai_compatible or a non-default ollama host.

Provider defaults
─────────────────
  openai             gpt-4o                        (api.openai.com/v1)
  groq               llama-3.3-70b-versatile       (api.groq.com/openai/v1)
  mistral            mistral-large-latest           (api.mistral.ai/v1)
  ollama             llama3.2                       (localhost:11434/v1)
  openai_compatible  (LLM_MODEL required)           (LLM_BASE_URL required)
  anthropic          claude-sonnet-4-5              (native Anthropic SDK —
                                                    requires: pip install anthropic)

All non-Anthropic providers are accessed via the OpenAI Python SDK with
a custom base_url — no additional packages required.

Runtime reconfiguration
───────────────────────
  Call reconfigure(provider, api_key, model, base_url) to swap the active
  LLM client without restarting the server.  The proxy objects sync_client
  and async_client always delegate to the current active client.
"""
from __future__ import annotations

import json
import os
import structlog
from dataclasses import dataclass
from typing import Any

log = structlog.get_logger(__name__)

# Config persisted here so it survives container restarts (backend dir is volume-mounted).
_CONFIG_FILE = os.path.join(os.path.dirname(__file__), ".llm_config.json")

# ── Provider presets ──────────────────────────────────────────────────────────

_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url":      None,
        "default_model": "gpt-4o",
        "api_key":       None,    # uses provided api_key
    },
    "groq": {
        "base_url":      "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "api_key":       None,
    },
    "mistral": {
        "base_url":      "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "api_key":       None,
    },
    "ollama": {
        "base_url":      None,   # resolved at build time from base_url param
        "default_model": "llama3.2",
        "api_key":       "ollama",   # ollama ignores the key but SDK requires one
    },
    "openai_compatible": {
        "base_url":      None,   # must be provided
        "default_model": "gpt-4o",
        "api_key":       None,
    },
    "anthropic": {
        "base_url":      None,   # handled separately via Anthropic SDK
        "default_model": "claude-sonnet-4-5",
        "api_key":       None,
    },
}


# ── Anthropic adapter ─────────────────────────────────────────────────────────
# Wraps the Anthropic SDK to expose an OpenAI-compatible interface so that
# llm_client.py can use client.chat.completions.create() without changes.

class _FakeMessage:
    __slots__ = ("content",)
    def __init__(self, text: str) -> None:
        self.content = text

class _FakeDelta:
    __slots__ = ("content",)
    def __init__(self, text: str) -> None:
        self.content = text

class _FakeChoice:
    __slots__ = ("message", "delta")
    def __init__(self, text: str) -> None:
        self.message = _FakeMessage(text)
        self.delta   = _FakeDelta("")

class _FakeDeltaChoice:
    __slots__ = ("delta",)
    def __init__(self, text: str) -> None:
        self.delta = _FakeDelta(text)

class _FakeCompletion:
    __slots__ = ("choices",)
    def __init__(self, text: str) -> None:
        self.choices = [_FakeChoice(text)]

class _FakeDeltaChunk:
    __slots__ = ("choices",)
    def __init__(self, text: str) -> None:
        self.choices = [_FakeDeltaChoice(text)]


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Separate OpenAI-style system messages from user/assistant turns.

    Anthropic's Messages API takes system as a top-level string, not as a
    message with role="system".
    """
    system_parts: list[str] = []
    turns: list[dict] = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            turns.append({"role": m["role"], "content": m["content"]})
    return "\n\n".join(system_parts), turns


class _SyncCompletions:
    """Synchronous completions adapter (mirrors OpenAI client.chat.completions)."""

    def __init__(self, native: Any, model: str) -> None:
        self._native = native
        self._model  = model

    def create(
        self,
        *,
        model: str | None = None,
        messages: list[dict],
        temperature: float = 0.1,
        response_format: dict | None = None,
        max_tokens: int = 4096,
        **_: Any,
    ) -> _FakeCompletion:
        system, turns = _split_system(messages)
        if response_format and response_format.get("type") == "json_object":
            system = (system + "\n\nRespond ONLY with valid JSON.").strip()
        kwargs: dict[str, Any] = {
            "model":       model or self._model,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    turns,
        }
        if system:
            kwargs["system"] = system
        resp = self._native.messages.create(**kwargs)
        return _FakeCompletion(resp.content[0].text)


class _SyncChat:
    def __init__(self, completions: _SyncCompletions) -> None:
        self.completions = completions


class _AsyncStream:
    """Async iterable that wraps Anthropic streaming to yield fake OpenAI chunks."""

    def __init__(self, native: Any, kwargs: dict) -> None:
        self._native = native
        self._kwargs = kwargs

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        async with self._native.messages.stream(**self._kwargs) as stream:
            async for text in stream.text_stream:
                yield _FakeDeltaChunk(text)


class _AsyncCompletions:
    """Async completions adapter (mirrors OpenAI async_client.chat.completions)."""

    def __init__(self, native: Any, model: str) -> None:
        self._native = native
        self._model  = model

    async def create(
        self,
        *,
        model: str | None = None,
        messages: list[dict],
        temperature: float = 0.1,
        response_format: dict | None = None,
        max_tokens: int = 4096,
        stream: bool = False,
        **_: Any,
    ) -> Any:
        system, turns = _split_system(messages)
        if response_format and response_format.get("type") == "json_object":
            system = (system + "\n\nRespond ONLY with valid JSON.").strip()
        kwargs: dict[str, Any] = {
            "model":       model or self._model,
            "max_tokens":  max_tokens,
            "temperature": temperature,
            "messages":    turns,
        }
        if system:
            kwargs["system"] = system
        if stream:
            return _AsyncStream(self._native, kwargs)
        resp = await self._native.messages.create(**kwargs)
        return _FakeCompletion(resp.content[0].text)


class _AsyncChat:
    def __init__(self, completions: _AsyncCompletions) -> None:
        self.completions = completions


class _AnthropicSyncAdapter:
    """Mimics the OpenAI sync client (client.chat.completions.create)."""
    def __init__(self, native: Any, model: str) -> None:
        self.chat = _SyncChat(_SyncCompletions(native, model))


class _AnthropicAsyncAdapter:
    """Mimics the OpenAI async client (async_client.chat.completions.create)."""
    def __init__(self, native: Any, model: str) -> None:
        self.chat = _AsyncChat(_AsyncCompletions(native, model))


# ── Builder ───────────────────────────────────────────────────────────────────

def _build(
    provider: str | None = None,
    api_key:  str | None = None,
    model:    str | None = None,
    base_url: str | None = None,
) -> tuple[Any, Any, str]:
    """Return (sync_client, async_client, model_name).

    Parameters take precedence over environment variables.
    """
    _provider = (provider or os.getenv("LLM_PROVIDER", "openai")).lower()
    _api_key  = api_key if api_key is not None else (
        os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    )
    _model    = model    or os.getenv("LLM_MODEL", "")
    _base_url = base_url or os.getenv("LLM_BASE_URL", "")

    preset = _PRESETS.get(_provider)
    if preset is None:
        raise RuntimeError(
            f"Unknown LLM provider '{_provider}'. "
            f"Valid values: {', '.join(_PRESETS)}"
        )

    effective_model = _model or preset["default_model"]

    # ── Anthropic (native SDK) ────────────────────────────────────────────────
    if _provider == "anthropic":
        try:
            import anthropic as _anth
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic requires the 'anthropic' package. "
                "Install it with:  pip install anthropic"
            ) from exc
        sync_native  = _anth.Anthropic(api_key=_api_key)
        async_native = _anth.AsyncAnthropic(api_key=_api_key)
        log.info("LLM provider: anthropic | model: %s", effective_model)
        return (
            _AnthropicSyncAdapter(sync_native,  effective_model),
            _AnthropicAsyncAdapter(async_native, effective_model),
            effective_model,
        )

    # ── OpenAI-compatible providers ───────────────────────────────────────────
    from openai import OpenAI, AsyncOpenAI

    # Resolve base_url: param > env > preset default
    resolved_base_url = (
        _base_url
        or (_provider == "ollama" and "http://localhost:11434/v1")
        or preset["base_url"]
        or None
    )

    if _provider == "openai_compatible" and not resolved_base_url:
        raise RuntimeError(
            "provider=openai_compatible requires base_url to be set."
        )

    effective_api_key = preset.get("api_key") or _api_key or "none"
    kwargs: dict[str, Any] = {"api_key": effective_api_key}
    if resolved_base_url:
        kwargs["base_url"] = resolved_base_url

    log.info("LLM provider: %s | model: %s | base_url: %s",
             _provider, effective_model, resolved_base_url or "(default)")
    return OpenAI(**kwargs), AsyncOpenAI(**kwargs), effective_model


# ── Mutable runtime state ─────────────────────────────────────────────────────

@dataclass
class _LLMState:
    sync_client:  Any
    async_client: Any
    model:        str
    provider:     str
    api_key_set:  bool


def _load_persisted() -> dict | None:
    """Load saved config from disk.  Returns None if file absent or corrupt."""
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "provider" in data:
            return data
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return None


def _save_persisted(provider: str, api_key: str, model: str, base_url: str) -> None:
    """Write current config to disk.  Failures are logged but never propagated."""
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"provider": provider, "api_key": api_key,
                 "model": model, "base_url": base_url},
                f,
            )
    except Exception as exc:
        log.warning("llm_config_persist_failed", error=str(exc))


def _init_state() -> _LLMState:
    """Initialise from persisted config first, env vars as fallback."""
    saved = _load_persisted()
    if saved:
        provider = saved.get("provider", "openai")
        api_key  = saved.get("api_key",  "")
        model    = saved.get("model",    "")
        base_url = saved.get("base_url", "")
        log.info("LLM config loaded from disk", provider=provider)
        sc, ac, m = _build(
            provider=provider,
            api_key=api_key or None,
            model=model or None,
            base_url=base_url or None,
        )
        return _LLMState(
            sync_client=sc, async_client=ac, model=m,
            provider=provider, api_key_set=bool(api_key),
        )
    # Fall back to environment variables
    _provider = os.getenv("LLM_PROVIDER", "openai").lower()
    _api_key  = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    sc, ac, m = _build()
    return _LLMState(
        sync_client=sc, async_client=ac, model=m,
        provider=_provider, api_key_set=bool(_api_key),
    )


_state: _LLMState = _init_state()


# ── Proxy objects (always delegate to current _state) ─────────────────────────
# Importers get a stable reference to the proxy; after reconfigure() the proxy
# transparently delegates to the new underlying client.

class _SyncProxy:
    """Proxy for the active sync LLM client."""
    def __getattr__(self, name: str) -> Any:
        return getattr(_state.sync_client, name)

class _AsyncProxy:
    """Proxy for the active async LLM client."""
    def __getattr__(self, name: str) -> Any:
        return getattr(_state.async_client, name)


sync_client  = _SyncProxy()
async_client = _AsyncProxy()


# ── Public API ────────────────────────────────────────────────────────────────

def get_model() -> str:
    """Return the currently active model name."""
    return _state.model


def get_provider_info() -> dict:
    """Return a safe summary of the current LLM configuration (no key value)."""
    return {
        "provider":    _state.provider,
        "model":       _state.model,
        "api_key_set": _state.api_key_set,
    }


def reconfigure(
    provider: str,
    api_key:  str,
    model:    str = "",
    base_url: str = "",
) -> None:
    """Swap the active LLM client at runtime without restarting the server.

    Raises RuntimeError on invalid provider or missing required fields.
    The proxy objects sync_client / async_client immediately reflect the
    new configuration on the next call.
    """
    global _state
    sc, ac, m = _build(
        provider=provider,
        api_key=api_key or None,
        model=model or None,
        base_url=base_url or None,
    )
    _state = _LLMState(
        sync_client=sc,
        async_client=ac,
        model=m,
        provider=provider.lower(),
        api_key_set=bool(api_key),
    )
    _save_persisted(provider.lower(), api_key, model, base_url)
    log.info("LLM reconfigured", provider=provider, model=m)
