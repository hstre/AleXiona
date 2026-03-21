"""
Clinical Orchestrator — the single authoritative reasoning layer for AleXiona.

This module is the "Dirigent": it takes all partial signals from the five
sub-engines and produces ONE unified clinical state with a single leading
hypothesis, a transparent score breakdown, a German verdict, and a concrete
next action.

Sub-engines consumed (all synchronous, no LLM calls):
  • reasoning_engine   — evidence scoring, guideline compliance, temporal decay
  • composite_scores   — validated bedside risk scores (Wells, qSOFA, GRACE …)
  • conflict_engine    — structural and epistemic conflicts
  • med_engine         — NOT called here (async/LLM); missing tests from guideline only

Output: OrchestratorState (see models.py)

Weighting rationale
───────────────────
  Evidence   40 % — the core: what the clinical record actually says
  Guideline  25 % — structure: does the diagnosis follow a validated pathway?
  Composite  15 % — external validation: do risk tools confirm the direction?
  Temporal   10 % — recency: how fresh is the supporting evidence?
  Conflict  -10 % — integrity: how contested is this hypothesis?
"""
from __future__ import annotations
from datetime import datetime, timezone
from reasoning_engine import (
    rank_hypotheses,
    evaluate_all_guidelines,
    guideline_score,
    _temporal_weight,                       # internal — same package
    _composite_boost_for_hypothesis,
    _COMPOSITE_BOOST_CAP,
)
from conflict_engine import detect_conflicts
from composite_scores import compute_all_scores

# ── Weights ────────────────────────────────────────────────────────────────────

WEIGHT_EVIDENCE   = 0.40
WEIGHT_GUIDELINE  = 0.25
WEIGHT_COMPOSITE  = 0.15
WEIGHT_TEMPORAL   = 0.10
WEIGHT_CONFLICT   = 0.10   # applied as negative penalty

# ── Status thresholds ─────────────────────────────────────────────────────────

_CONFIDENT_MIN      = 0.52   # orchestrated_score ≥ this → "confident"
_INSUFFICIENT_MAX   = 0.25   # orchestrated_score < this → "insufficient"
_CONTESTED_CONFLICTS = 3     # ≥ this many conflicts → "contested"
_MIN_SUPPORTING     = 2      # < this many supporting claims → "insufficient"

# ── Severity ordering for conflict prioritisation ─────────────────────────────

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _temporal_factor(supporting_ids: list[str], all_claims: list[dict]) -> float:
    """Average temporal freshness (0–1) of a set of supporting claim IDs."""
    by_id = {c["id"]: c for c in all_claims}
    weights = [_temporal_weight(by_id[cid]) for cid in supporting_ids if cid in by_id]
    return round(sum(weights) / len(weights), 3) if weights else 0.5


def _conflict_norm(n: int) -> float:
    """Normalise conflict count to [0, 1] (5 conflicts = max penalty)."""
    return min(n / 5.0, 1.0)


def _orchestrated_score(
    base_evidence:   float,
    g_score:         float,
    comp_contrib:    float,
    temporal:        float,
    n_conflicts:     int,
) -> float:
    comp_norm = comp_contrib / _COMPOSITE_BOOST_CAP if _COMPOSITE_BOOST_CAP > 0 else 0.0
    raw = (
        base_evidence * WEIGHT_EVIDENCE
        + g_score     * WEIGHT_GUIDELINE
        + comp_norm   * WEIGHT_COMPOSITE
        + temporal    * WEIGHT_TEMPORAL
        - _conflict_norm(n_conflicts) * WEIGHT_CONFLICT
    )
    return round(max(0.0, min(1.0, raw)), 3)


def _status(
    score:          float,
    n_conflicts:    int,
    n_supporting:   int,
    n_hypotheses:   int,
) -> str:
    if n_hypotheses == 0:
        return "insufficient"
    if n_supporting < _MIN_SUPPORTING or score < _INSUFFICIENT_MAX:
        return "insufficient"
    if n_conflicts >= _CONTESTED_CONFLICTS:
        return "contested"
    if score >= _CONFIDENT_MIN:
        return "confident"
    return "undecided"


def _next_action(
    status:           str,
    key_conflicts:    list[str],
    missing_critical: list[str],
    hypothesis:       str | None,
) -> str:
    if status == "insufficient":
        return ("Weitere klinische Befunde dokumentieren — "
                "Evidenzlage für eine zuverlässige Priorisierung unzureichend.")
    if status == "contested" and key_conflicts:
        return f"Konflikte klären, bevor die Therapie festgelegt wird: {key_conflicts[0]}"
    if missing_critical:
        return f"Diagnostik vervollständigen: {missing_critical[0]}"
    if hypothesis:
        return ("Führende Diagnose klinisch verifizieren und "
                "leitliniengerechte Therapie einleiten.")
    return "Klinischen Befund weiter dokumentieren."


# ── Public API ────────────────────────────────────────────────────────────────

def orchestrate(session_id: str, all_claims: list[dict]) -> dict:
    """
    Produce ONE unified clinical state from all sub-engine signals.

    Returns a dict matching the OrchestratorState Pydantic model.
    All computation is synchronous and deterministic — no LLM calls.
    """
    ranked     = rank_hypotheses(all_claims)
    conflicts  = detect_conflicts(all_claims)
    comp_all   = compute_all_scores(all_claims)

    # ── No hypotheses ─────────────────────────────────────────────────────────
    if not ranked:
        return {
            "session_id":        session_id,
            "leading_hypothesis": None,
            "orchestrated_score": 0.0,
            "status":            "insufficient",
            "why":               "Keine aktiven Hypothesen im Evidenzgraphen vorhanden.",
            "key_conflicts":     [],
            "missing_critical":  [],
            "next_action":       "Klinische Befunde dokumentieren um Hypothesen zu generieren.",
            "score_breakdown":   _zero_breakdown(),
            "alternatives":      [],
            "generated_at":      datetime.now(timezone.utc).isoformat(),
        }

    top            = ranked[0]
    comp_contrib   = top.get("composite_score_contribution", 0.0)
    # base_evidence = score before composite boost was added by rank_hypotheses
    base_evidence  = round(top["rule_based_score"] - comp_contrib, 3)
    n_support      = len(top["supporting_claim_ids"])
    n_conflict     = len(top["conflicting_claim_ids"])

    guidelines     = evaluate_all_guidelines(all_claims)
    g              = guidelines.get(top["text"], {})
    g_score        = guideline_score(top["text"], all_claims)
    req_missing    = g.get("required_missing", [])

    temporal       = _temporal_factor(top["supporting_claim_ids"], all_claims)

    o_score = _orchestrated_score(
        base_evidence, g_score, comp_contrib, temporal, n_conflict
    )

    st = _status(o_score, n_conflict, n_support, len(ranked))

    # ── Key conflicts (top 3, error-first) ───────────────────────────────────
    sorted_conflicts = sorted(
        conflicts,
        key=lambda c: (_SEVERITY_ORDER.get(c.severity, 9), 0),
    )
    key_conflicts = [c.message for c in sorted_conflicts[:3]]

    # ── Missing critical: required guideline criteria first, then supporting ──
    missing_critical = req_missing[:3] or g.get("supporting_missing", [])[:3]

    # ── Composite score triggers for the leading hypothesis ───────────────────
    _, triggered_scores = _composite_boost_for_hypothesis(top["text"], comp_all)

    # ── Why (German verdict) ─────────────────────────────────────────────────
    why_parts = [
        f"'{top['text']}' führt mit einem Gesamtscore von {o_score:.0%}"
        f" (Status: {st})."
    ]
    if n_support > 0:
        why_parts.append(
            f"{n_support} unterstützende Befunde liefern eine Evidenzstärke von "
            f"{base_evidence:.0%}."
        )
    if triggered_scores:
        why_parts.append(
            f"Klinische Scores bestätigen die Richtung: {', '.join(triggered_scores)}."
        )
    if g.get("rule_found") and g_score >= 0.5:
        why_parts.append(
            f"Leitlinienkriterien zu {g_score:.0%} erfüllt."
        )
    if n_conflict > 0:
        why_parts.append(
            f"{n_conflict} widersprüchliche Befunde reduzieren die Konfidenz."
        )
    if missing_critical:
        why_parts.append(
            f"Fehlende Schlüsselbefunde: {', '.join(missing_critical[:2])}."
        )

    # ── Alternatives (ranked 2 onward) ───────────────────────────────────────
    alternatives = [
        {
            "text":  h["text"],
            "score": h["rule_based_score"],
            "composite_score_contribution": h.get("composite_score_contribution", 0.0),
        }
        for h in ranked[1:4]
    ]

    # ── Score breakdown (contribution of each factor to orchestrated_score) ──
    comp_norm    = comp_contrib / _COMPOSITE_BOOST_CAP if _COMPOSITE_BOOST_CAP > 0 else 0.0
    breakdown = {
        "evidence":  round(base_evidence  * WEIGHT_EVIDENCE,  3),
        "guideline": round(g_score        * WEIGHT_GUIDELINE, 3),
        "composite": round(comp_norm      * WEIGHT_COMPOSITE, 3),
        "temporal":  round(temporal       * WEIGHT_TEMPORAL,  3),
        "conflict":  round(-_conflict_norm(n_conflict) * WEIGHT_CONFLICT, 3),
    }

    return {
        "session_id":         session_id,
        "leading_hypothesis": top["text"],
        "orchestrated_score": o_score,
        "status":             st,
        "why":                " ".join(why_parts),
        "key_conflicts":      key_conflicts,
        "missing_critical":   missing_critical,
        "next_action":        _next_action(st, key_conflicts, missing_critical, top["text"]),
        "score_breakdown":    breakdown,
        "alternatives":       alternatives,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
    }


def _zero_breakdown() -> dict:
    return {"evidence": 0.0, "guideline": 0.0, "composite": 0.0,
            "temporal": 0.0, "conflict": 0.0}
