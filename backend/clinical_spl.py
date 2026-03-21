"""
Clinical SPL Adapter — AleXiona
================================
Bridges the Alexandria Semantic Projection Layer (spl.py) with the
AleXiona Clinical Claim model.

Pipeline per claim dict from the LLM extractor:

    llm_claim_dict
        → SemanticUnit       (claim text as minimal epistemic fragment)
        → SemanticProjection (ESS + claim_type → P_r over 13 clinical relations)
        → EmissionEngine     (E0–E3 rules applied)
        → Claim              (with spl_* provenance fields)

Emission outcomes
-----------------
E1  ESS ≥ 0.90 → high-confidence singular emission; uncertainty_flag as-is
E2  ESS 0.62–0.90 → moderate confidence; top candidate selected; uncertainty_flag as-is
E3  ESS < 0.62 → AMBIGUOUS: Claim written with uncertainty_flag=True, status=tentative
E0  Structural violation: claim discarded (rare in LLM output)

Clinical rationale for E3 pass-through
---------------------------------------
Unlike the general Alexandria protocol (which discards E3 results), AleXiona
propagates them as tentative claims to avoid silently losing patient-reported
symptoms.  The spl_emission_rule="E3" field marks them for human review.

Clinical thresholds (tuned for 13-relation space)
---------------------------------------------------
tau_1=0.85  E1 singular dominance     (ESS must exceed this)
tau_2=0.25  E1 entropy ceiling        (H_norm must be below this)
tau_3=0.65  E3 ambiguity block floor  (H_norm above this → AMBIGUOUS)
tau_4=0.40  E4 JSD (unchanged)

With 13 clinical relations these produce empirical breakpoints:
    ESS ≥ 0.90  → E1
    0.62 ≤ ESS < 0.90  → E2
    ESS < 0.62  → E3
"""
from __future__ import annotations

import uuid
from typing import Optional

from spl import (
    SemanticUnit,
    SemanticProjection,
    ClaimCandidate,
    EmissionEngine,
    EmissionRule,
    EmissionStatus,
    SPLThresholds,
    compute_h_norm,
)


# ── Clinical relation space ℛ ─────────────────────────────────────────────────

CLINICAL_RELATIONS: list[str] = [
    "has_symptom",
    "has_finding",
    "has_diagnosis",
    "has_vital",
    "has_lab_result",
    "has_medication",
    "has_history",
    "has_risk_factor",
    "rules_out",
    "confirms",
    "worsens",
    "improves",
    "is_associated_with",
]

# Maps ClaimType (string) → dominant relation in ℛ
_TYPE_TO_RELATION: dict[str, str] = {
    "symptom":     "has_symptom",
    "finding":     "has_finding",
    "diagnosis":   "has_diagnosis",
    "vital":       "has_vital",
    "lab":         "has_lab_result",
    "imaging":     "has_finding",
    "medication":  "has_medication",
    "therapy":     "has_medication",
    "history":     "has_history",
    "risk_factor": "has_risk_factor",
    "hypothesis":  "is_associated_with",
    "guideline":   "is_associated_with",
}

# Clinical thresholds — tuned for a 13-relation space
CLINICAL_THRESHOLDS = SPLThresholds(
    tau_0=0.50,   # structural rejection: unchanged
    tau_1=0.85,   # E1 singular dominance: ESS must exceed this
    tau_2=0.25,   # E1 entropy ceiling: H_norm must be below this
    tau_3=0.65,   # E3 ambiguity block: H_norm ≥ 0.65 → AMBIGUOUS
    tau_4=0.40,   # E4 JSD: unchanged
)

_MATRIX_VERSION = "clinical-v1.0"
_ENGINE = EmissionEngine(CLINICAL_THRESHOLDS)

_N_RELATIONS = len(CLINICAL_RELATIONS)


# ── P_r construction ──────────────────────────────────────────────────────────

def _build_P_r(claim_type: str, ess: float) -> dict[str, float]:
    """
    Build a relational probability distribution P_r over CLINICAL_RELATIONS.

    The dominant relation (determined by claim_type) receives probability ess.
    The remaining probability (1 - ess) is distributed equally across all other
    relations.  This produces the entropy profile:

        ESS ≥ 0.90  → H_norm ≈ 0.22 → E1 (below tau_2=0.25)
        0.62 ≤ ESS < 0.90 → H_norm 0.30–0.63 → E2
        ESS < 0.62  → H_norm > tau_3=0.65 → E3
    """
    primary  = _TYPE_TO_RELATION.get(claim_type, "is_associated_with")
    residual = (1.0 - ess) / (_N_RELATIONS - 1)
    P_r = {r: residual for r in CLINICAL_RELATIONS}
    P_r[primary] = ess
    # Normalise to guard against floating-point drift
    total = sum(P_r.values())
    return {k: v / total for k, v in P_r.items()}


# ── SemanticUnit factory ──────────────────────────────────────────────────────

def make_semantic_unit(claim_text: str, source_ref: str = "") -> SemanticUnit:
    """Wrap a claim text string in a SemanticUnit."""
    return SemanticUnit.new(
        source_text=claim_text,
        source_ref=source_ref,
        fragmentation_signal="llm_claim_boundary",
    )


# ── SemanticProjection factory ────────────────────────────────────────────────

def make_projection(
    unit: SemanticUnit,
    claim_type: str,
    ess: float,
    subject: str = "",
    object_: str = "",
) -> SemanticProjection:
    """
    Build a SemanticProjection from LLM claim metadata.

    P_r is constructed from (claim_type, ess); subject/object are
    extracted entity hints passed through to the ClaimCandidate.
    """
    ess_clamped = max(0.0, min(1.0, ess))
    P_r = _build_P_r(claim_type, ess_clamped)

    # Modality distribution inferred from ESS
    if ess_clamped >= 0.85:
        P_modality = {"asserted": 0.80, "suggested": 0.15, "hypothesized": 0.05}
    elif ess_clamped >= 0.65:
        P_modality = {"asserted": 0.40, "suggested": 0.45, "hypothesized": 0.15}
    else:
        P_modality = {"asserted": 0.20, "suggested": 0.40, "hypothesized": 0.40}

    return SemanticProjection(
        projection_id=str(uuid.uuid4()),
        unit_id=unit.unit_id,
        builder_origin="alpha",
        matrix_version=_MATRIX_VERSION,
        P_r=P_r,
        subject_candidates=[subject] if subject else [],
        object_candidates=[object_]  if object_  else [],
        P_modality=P_modality,
        p_illegal=0.0,   # structural violations handled by epistemic safeguards upstream
    )


# ── Emission result → Claim fields ───────────────────────────────────────────

class SPLEmissionResult:
    """
    Carries the SPL provenance fields to be merged into a Claim.

    Fields
    ------
    unit_id          SemanticUnit.unit_id
    projection_id    SemanticProjection.projection_id
    emission_rule    "E1" | "E2" | "E3" | "E0"
    h_norm           Normalised Shannon entropy of the projection
    relation_score   Probability mass of the selected relation (top candidate)
    blocked          True if E3 or E0 fired (no READY_FOR_CLAIM candidate)
    force_uncertain  True if the engine flagged ambiguity (E3)
    """

    def __init__(
        self,
        unit: SemanticUnit,
        projection: SemanticProjection,
        candidate: Optional[ClaimCandidate],
    ):
        self.unit_id       = unit.unit_id
        self.projection_id = projection.projection_id
        self.h_norm        = projection.h_norm

        if projection.emission_rule is not None:
            self.emission_rule = projection.emission_rule.value
        else:
            self.emission_rule = "unknown"

        if candidate is not None:
            self.relation_score = candidate.relation_score
            self.blocked        = False
            self.force_uncertain = (projection.status == EmissionStatus.AMBIGUOUS)
        else:
            # E0 or E3
            self.relation_score  = 0.0
            self.blocked         = (projection.status == EmissionStatus.STRUCTURAL_VIOLATION)
            self.force_uncertain = (projection.status == EmissionStatus.AMBIGUOUS)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_spl_pipeline(
    claim_text: str,
    claim_type: str,
    ess: float,
    source_ref: str = "",
    subject: str = "",
    object_: str = "",
) -> SPLEmissionResult:
    """
    Run the full SPL pipeline for a single LLM claim dict.

    Returns an SPLEmissionResult containing:
    - spl_unit_id, spl_projection_id, spl_emission_rule, spl_h_norm
    - force_uncertain: True if E3 fired (caller should set uncertainty_flag=True)
    - blocked: True if E0 fired (caller should discard the claim)

    Raises nothing — all errors are absorbed and reported as E3/uncertain.
    """
    try:
        unit       = make_semantic_unit(claim_text, source_ref)
        projection = make_projection(unit, claim_type, ess, subject, object_)
        candidates = _ENGINE.emit(projection, k=3)
        top        = candidates[0] if candidates else None
        return SPLEmissionResult(unit, projection, top)
    except Exception:
        # Fail-safe: never let SPL errors break the extraction pipeline
        import traceback, logging
        logging.getLogger(__name__).warning(
            "SPL pipeline error for %r — falling back to uncertainty",
            claim_text[:60], exc_info=True,
        )
        # Return a synthetic E3-like result
        unit = make_semantic_unit(claim_text, source_ref)
        fallback_projection = SemanticProjection(
            projection_id=str(uuid.uuid4()),
            unit_id=unit.unit_id,
            builder_origin="alpha",
            matrix_version=_MATRIX_VERSION,
            P_r={"is_associated_with": 1.0},
            subject_candidates=[],
            object_candidates=[],
            h_norm=1.0,
            status=EmissionStatus.AMBIGUOUS,
            emission_rule=EmissionRule.E3,
        )
        return SPLEmissionResult(unit, fallback_projection, None)


# ── E4 Dual-Builder ───────────────────────────────────────────────────────────

class DualSPLResult:
    """
    Result of an E4 dual-builder evaluation.

    When branched=True, both alpha and beta carry valid alternative
    interpretations of the same SemanticUnit and should be written as
    separate tentative Claims sharing the same spl_unit_id.

    When branched=False, the alpha result is authoritative (lower JSD
    means the builders agreed; use alpha's emission rule and score).
    """
    __slots__ = ("branched", "jsd", "alpha", "beta")

    def __init__(
        self,
        branched: bool,
        jsd: float,
        alpha: SPLEmissionResult,
        beta:  SPLEmissionResult,
    ):
        self.branched = branched
        self.jsd      = jsd
        self.alpha    = alpha
        self.beta     = beta


def run_dual_spl_pipeline(
    claim_text:      str,
    alpha_claim_type: str, alpha_ess: float,
    beta_claim_type:  str, beta_ess:  float,
    source_ref: str = "",
    subject:    str = "",
    object_:    str = "",
) -> DualSPLResult:
    """
    Run the full E4 dual-builder pipeline.

    Both builders receive the same SemanticUnit but produce independent
    SemanticProjections from their respective (claim_type, ess) inputs.
    `apply_e4()` then measures Jensen-Shannon Divergence between the
    two P_r distributions.

    E4 fires when:
    - Both builders are moderately confident (ESS ≥ 0.65, i.e. E2 range)
    - But their dominant relation differs (different claim_type)
    → JSD typically > 0.40

    E4 does NOT fire (JSD < tau_4) when:
    - Both are near maximum entropy (ESS < 0.60) — they agree on uncertainty
    - Both converge to the same primary relation

    Raises nothing.
    """
    try:
        unit         = make_semantic_unit(claim_text, source_ref)

        # Build projections for both builders from the same unit
        proj_alpha = make_projection(unit, alpha_claim_type, alpha_ess, subject, object_)
        proj_beta  = SemanticProjection(
            projection_id=str(uuid.uuid4()),
            unit_id=unit.unit_id,            # same unit — required by apply_e4
            builder_origin="beta",
            matrix_version=_MATRIX_VERSION,
            P_r=_build_P_r(beta_claim_type, max(0.0, min(1.0, beta_ess))),
            subject_candidates=[subject] if subject else [],
            object_candidates=[object_]  if object_  else [],
            P_modality={},
        )

        # E4 check: mutates status of both projections if JSD > tau_4
        jsd      = _ENGINE.apply_e4(proj_alpha, proj_beta)
        branched = jsd > CLINICAL_THRESHOLDS.tau_4

        if branched:
            # Both are BRANCH_CANDIDATE — emit neither through the normal rules
            cand_alpha = None
            cand_beta  = None
        else:
            # Not branched — run normal E0-E3 on alpha; use alpha as authoritative
            cands_alpha = _ENGINE.emit(proj_alpha, k=3)
            cand_alpha  = cands_alpha[0] if cands_alpha else None
            cands_beta  = _ENGINE.emit(proj_beta, k=3)
            cand_beta   = cands_beta[0]  if cands_beta  else None

        # For BRANCH_CANDIDATE, manually set emission metrics on projections
        if branched:
            import math as _math
            proj_alpha.h_norm = _math.log(1) if not proj_alpha.h_norm else proj_alpha.h_norm
            proj_beta.h_norm  = _math.log(1) if not proj_beta.h_norm  else proj_beta.h_norm
            # Compute h_norm for provenance
            from spl import compute_h_norm as _h
            proj_alpha.h_norm = _h(proj_alpha.P_r)
            proj_beta.h_norm  = _h(proj_beta.P_r)

        res_alpha = SPLEmissionResult(unit, proj_alpha, cand_alpha)
        res_beta  = SPLEmissionResult(unit, proj_beta,  cand_beta)
        # Override emission_rule for branch case
        if branched:
            res_alpha.emission_rule = "E4"
            res_beta.emission_rule  = "E4"

        return DualSPLResult(branched=branched, jsd=jsd, alpha=res_alpha, beta=res_beta)

    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Dual SPL pipeline error for %r — falling back to single alpha",
            claim_text[:60], exc_info=True,
        )
        alpha = run_spl_pipeline(claim_text, alpha_claim_type, alpha_ess, source_ref, subject, object_)
        return DualSPLResult(branched=False, jsd=0.0, alpha=alpha, beta=alpha)
