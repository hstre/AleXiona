"""
MIVP — Model Identity Verification Protocol (lightweight, additive)
==================================================================

Binds every LLM-extracted claim to a *Composite Instance Hash* (CIH) of the
system that produced it: model + policy + runtime. This is the MIVP layer of the
Alexandria / DESi family, applied to AleXiona's NLP extraction.

It answers one audit question precisely:

    "Which exact system (model, governing policy, runtime config) produced this
     clinical claim?" — and: "has any of it silently changed since?"

CIH formula (faithful to Alexandria-MIVP/src/mivp_impl.py):

    CIH = SHA256( 0x04 || "MIVP-CIH-V1" || 0x00 || MH || PH || RH )

where MH/PH/RH are domain-separated SHA-256 digests of the model, policy and
runtime profiles.

A note on the model hash (MH)
-----------------------------
The canonical MIVP computes MH as a Merkle tree over model *weight files*.
AleXiona uses a *hosted API model* (DeepSeek / OpenAI) — there are no local
weights. We therefore use MIVP's **declared-profile** variant: MH is the digest
of a declared model identity (provider + model name). This is honest: it binds
the claim to the *declared* model, not to verified weights. A provider switching
the model silently behind the same name is out of scope here (documented limit).

This module is pure (hashlib + json only) and has no side effects, so it cannot
affect the clinical decision path. It only produces metadata.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache

# Schema version for the MIVP profile written onto claims. Bump on any change to
# how MH/PH/RH profiles are constructed (so old stamps remain interpretable).
PROFILE_VERSION = "mivp-1"


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _canonical_json(obj: dict) -> bytes:
    """Deterministic JSON: sorted keys, no insignificant whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def model_hash(model_profile: dict) -> bytes:
    """MH — declared model identity (provider + model name + any declared meta)."""
    return _sha256(b"\x01" + b"MIVP-MH-DECLARED-V1" + b"\x00" + _canonical_json(model_profile))


def policy_hash(policy_profile: dict) -> bytes:
    """PH — the governing policy: SPL thresholds + extraction prompt fingerprint."""
    return _sha256(b"\x02" + b"MIVP-PH-V1" + b"\x00" + _canonical_json(policy_profile))


def runtime_hash(runtime_profile: dict) -> bytes:
    """RH — runtime configuration (decoding params, response format, versions)."""
    return _sha256(b"\x03" + b"MIVP-RH-V1" + b"\x00" + _canonical_json(runtime_profile))


def composite_instance_hash(mh: bytes, ph: bytes, rh: bytes) -> bytes:
    """CIH = SHA256(0x04 || "MIVP-CIH-V1" || 0x00 || MH || PH || RH)."""
    return _sha256(b"\x04" + b"MIVP-CIH-V1" + b"\x00" + mh + ph + rh)


def build_profile(
    *,
    provider: str,
    model: str,
    extraction_prompt: str,
    spl_thresholds: dict,
    temperature: float,
    response_format: str = "json_object",
    model_meta: dict | None = None,
) -> dict:
    """Compute the full MIVP profile (MH/PH/RH/CIH, hex) for the current system.

    Pure function — pass the live values in; nothing is read from globals here.
    Cached by the caller (the config is constant within a process run).
    """
    model_profile = {"provider": provider, "model": model}
    if model_meta:
        model_profile["meta"] = model_meta

    policy_profile = {
        "spl_thresholds": spl_thresholds,
        # Hash the prompt text rather than embedding it (keeps the profile small,
        # still substitution-sensitive: any prompt edit changes PH).
        "extraction_prompt_sha256": hashlib.sha256(extraction_prompt.encode("utf-8")).hexdigest(),
    }
    runtime_profile = {
        "temperature": round(float(temperature), 4),
        "response_format": response_format,
        "profile_version": PROFILE_VERSION,
    }

    mh = model_hash(model_profile)
    ph = policy_hash(policy_profile)
    rh = runtime_hash(runtime_profile)
    cih = composite_instance_hash(mh, ph, rh)

    return {
        "cih": cih.hex(),
        "mh": mh.hex(),
        "ph": ph.hex(),
        "rh": rh.hex(),
        "model": f"{provider}:{model}",
        "profile_version": PROFILE_VERSION,
    }


@lru_cache(maxsize=8)
def _cached_profile(frozen_key: tuple) -> dict:
    provider, model, extraction_prompt, thresholds_json, temperature, response_format = frozen_key
    return build_profile(
        provider=provider,
        model=model,
        extraction_prompt=extraction_prompt,
        spl_thresholds=json.loads(thresholds_json),
        temperature=temperature,
        response_format=response_format,
    )


def current_profile(
    *,
    provider: str,
    model: str,
    extraction_prompt: str,
    spl_thresholds: dict,
    temperature: float,
    response_format: str = "json_object",
) -> dict:
    """Memoised wrapper — the CIH is constant for a given configuration."""
    key = (
        provider,
        model,
        extraction_prompt,
        json.dumps(spl_thresholds, sort_keys=True),
        round(float(temperature), 4),
        response_format,
    )
    return _cached_profile(key)
