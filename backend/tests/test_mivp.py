"""Tests for the MIVP provenance layer (mivp.py).

Pure / offline — no LLM, no network. Verifies the Composite Instance Hash is
deterministic for a fixed configuration and changes when model, policy or
runtime changes (substitution detectability).
"""
from __future__ import annotations

import mivp

_BASE = dict(
    provider="deepseek",
    model="deepseek-chat",
    extraction_prompt="Extract clinical claims.",
    spl_thresholds={"tau_0": 0.5, "tau_1": 0.85, "tau_2": 0.25, "tau_3": 0.65, "tau_4": 0.40},
    temperature=0.1,
)


def _cih(**overrides) -> str:
    return mivp.build_profile(**{**_BASE, **overrides})["cih"]


def test_cih_is_64_hex_chars():
    cih = _cih()
    assert len(cih) == 64
    int(cih, 16)  # parses as hex


def test_cih_is_deterministic():
    assert _cih() == _cih()


def test_threshold_key_order_does_not_matter():
    reordered = {"tau_4": 0.40, "tau_0": 0.5, "tau_3": 0.65, "tau_1": 0.85, "tau_2": 0.25}
    assert _cih(spl_thresholds=reordered) == _cih()


def test_model_change_changes_cih():
    assert _cih(model="gpt-4o") != _cih()


def test_provider_change_changes_cih():
    assert _cih(provider="openai") != _cih()


def test_policy_change_changes_cih():
    assert _cih(spl_thresholds={**_BASE["spl_thresholds"], "tau_3": 0.70}) != _cih()


def test_prompt_change_changes_cih():
    assert _cih(extraction_prompt="Extract clinical claims. v2") != _cih()


def test_runtime_change_changes_cih():
    assert _cih(temperature=0.2) != _cih()


def test_components_present_and_distinct():
    prof = mivp.build_profile(**_BASE)
    for k in ("cih", "mh", "ph", "rh", "model", "profile_version"):
        assert prof[k]
    assert len({prof["mh"], prof["ph"], prof["rh"], prof["cih"]}) == 4
    assert prof["model"] == "deepseek:deepseek-chat"


def test_current_profile_matches_build_and_is_cached():
    a = mivp.current_profile(**_BASE)
    b = mivp.current_profile(**_BASE)
    assert a == b == mivp.build_profile(**_BASE)
