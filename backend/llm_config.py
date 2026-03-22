"""
LLM provider configuration for AleXiona.

Supported providers and the required environment variables:

  LLM_PROVIDER   Which provider to use. Defaults to "openai".
                 Values: openai | groq | mistral | ollama |
                         openai_compatible | anthropic

  LLM_MODEL      Model name, overrides the provider default.

  LLM_API_KEY    API key. Falls back to OPENAI_API_KEY for backwards
                 compatibility. Not required for ollama (local, no auth).

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
"""
from __future__ import annotations

import os
import logging
from typing import Any

log = logging.getLogger(__name__)

# ── Read configuration ─────────────────────────────────────────────────────────

PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
MODEL    = os.getenv("LLM_MODEL", "")
API_KEY  = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
BASE_URL = os.getenv("LLM_BASE_URL", "")

# ── Provider presets ──────────────────────────────────────────────────────────

_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "base_url":      None,
        "default_model": "gpt-4o",
        "api_key":       None,    # uses API_KEY
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
        "base_url":      BASE_URL or "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "api_key":       "ollama",          # ollama ignores the key but SDK requires one
    },
    "openai_compatible": {
        "base_url":      BASE_URL,
        "default_model": MODEL or "gpt-4o",
        "api_key":       None,
    },
    "anthropic": {
        "base_url":      None,              # handled separately via Anthropic SDK
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
            # Return the wrapper directly — it is an async iterable, not a coroutine.
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

def _build() -> tuple[Any, Any, str]:
    """Return (sync_client, async_client, model_name)."""
    preset = _PRESETS.get(PROVIDER)
    if preset is None:
        raise RuntimeError(
            f"Unknown LLM_PROVIDER '{PROVIDER}'. "
            f"Valid values: {', '.join(_PRESETS)}"
        )

    effective_model = MODEL or preset["default_model"]

    # ── Anthropic (native SDK) ────────────────────────────────────────────────
    if PROVIDER == "anthropic":
        try:
            import anthropic as _anth
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic requires the 'anthropic' package. "
                "Install it with:  pip install anthropic"
            ) from exc
        sync_native  = _anth.Anthropic(api_key=API_KEY)
        async_native = _anth.AsyncAnthropic(api_key=API_KEY)
        log.info("LLM provider: anthropic | model: %s", effective_model)
        return (
            _AnthropicSyncAdapter(sync_native,  effective_model),
            _AnthropicAsyncAdapter(async_native, effective_model),
            effective_model,
        )

    # ── OpenAI-compatible providers ───────────────────────────────────────────
    from openai import OpenAI, AsyncOpenAI

    if PROVIDER == "openai_compatible" and not preset["base_url"]:
        raise RuntimeError(
            "LLM_PROVIDER=openai_compatible requires LLM_BASE_URL to be set."
        )

    api_key = preset.get("api_key") or API_KEY or "none"
    kwargs: dict[str, Any] = {"api_key": api_key}
    if preset["base_url"]:
        kwargs["base_url"] = preset["base_url"]

    log.info("LLM provider: %s | model: %s | base_url: %s",
             PROVIDER, effective_model, preset["base_url"] or "(default)")
    return OpenAI(**kwargs), AsyncOpenAI(**kwargs), effective_model


# ── Module-level exports ──────────────────────────────────────────────────────

sync_client, async_client, MODEL = _build()
