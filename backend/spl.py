"""
Alexandria Semantic Projection Layer (SPL) — Core Library
Source: https://github.com/hstre/Alexandria-Semantic-Projection-Layer

Ported verbatim from upstream; only the ClaimCandidateConverter class is
omitted because it imports from the Alexandria schema package which is not
a dependency here.  All other classes, functions and enums are unchanged.

The clinical adapter for AleXiona lives in clinical_spl.py.
"""
from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

# ── Emission Status (WP2 §7.2, Appendix I.1) ─────────────────────────────────

class EmissionStatus(StrEnum):
    """
    Status of a SemanticProjection after emission rule evaluation.

    WP2 Appendix I.1 defines five statuses:
        PROJECTED        — projection computed, emission not yet evaluated
        READY_FOR_CLAIM  — E1 or E2: candidate(s) emitted, eligible for protocol
        AMBIGUOUS        — E3: H_norm >= τ₃, no emission (projection too uncertain)
        BRANCH_CANDIDATE — E4: JSD(A,B) > τ₄, dual-builder divergence too large
        STRUCTURAL_VIOLATION — E0: P_illegal > τ₀, ontological shield triggered
    """
    PROJECTED             = "projected"
    READY_FOR_CLAIM       = "ready_for_claim"
    AMBIGUOUS             = "ambiguous"
    BRANCH_CANDIDATE      = "branch_candidate"
    STRUCTURAL_VIOLATION  = "structural_violation"


class EmissionRule(StrEnum):
    """Which emission rule produced this result. WP2 §7.2."""
    E0 = "E0"   # Structural rejection
    E1 = "E1"   # Singular emission (argmax)
    E2 = "E2"   # Multiple emission (top-k)
    E3 = "E3"   # Ambiguity block
    E4 = "E4"   # Branch on builder divergence


# ── Thresholds Θ (WP2 §7.2, Appendix I.1) ────────────────────────────────────

@dataclass
class SPLThresholds:
    """
    Parameter set Θ = {τ₀, τ₁, τ₂, τ₃, τ₄}.

    WP2 Appendix I.1 recommended initial values:
        τ₀ ≈ 0.50  structural rejection threshold
        τ₁ ≈ 0.60  singular emission: max(P_r) must exceed this
        τ₂ ≈ 0.25  singular emission: H_norm must be below this
        τ₃ ≈ 0.65  ambiguity block threshold
        τ₄ ≈ 0.40  builder divergence branch threshold
    """
    tau_0: float = 0.50
    tau_1: float = 0.60
    tau_2: float = 0.25
    tau_3: float = 0.65
    tau_4: float = 0.40

    def validate(self) -> list[str]:
        errors = []
        if not (0 < self.tau_0 < 1):
            errors.append(f"tau_0={self.tau_0} must be in (0,1)")
        if not (0 < self.tau_1 < 1):
            errors.append(f"tau_1={self.tau_1} must be in (0,1)")
        if not (0 < self.tau_2 < self.tau_3 <= 1):
            errors.append(f"tau_2={self.tau_2} must be < tau_3={self.tau_3}")
        if not (0 < self.tau_4 < 1):
            errors.append(f"tau_4={self.tau_4} must be in (0,1)")
        return errors


# ── SemanticUnit (WP2 §3.1) ──────────────────────────────────────────────────

@dataclass
class SemanticUnit:
    """
    The smallest extractable text fragment that can carry a relational
    epistemic assertion.
    """
    unit_id:              str
    source_text:          str
    source_ref:           str
    offset_start:         int = 0
    offset_end:           int = 0
    fragmentation_signal: str = ""
    created_at:           float = field(default_factory=time.time)

    @classmethod
    def new(cls, source_text: str, source_ref: str,
            offset_start: int = 0, offset_end: int = 0,
            fragmentation_signal: str = "") -> SemanticUnit:
        return cls(
            unit_id=str(uuid.uuid4()),
            source_text=source_text,
            source_ref=source_ref,
            offset_start=offset_start,
            offset_end=offset_end,
            fragmentation_signal=fragmentation_signal,
        )

    def to_dict(self) -> dict:
        return {
            "unit_id":              self.unit_id,
            "source_text":          self.source_text,
            "source_ref":           self.source_ref,
            "offset_start":         self.offset_start,
            "offset_end":           self.offset_end,
            "fragmentation_signal": self.fragmentation_signal,
            "created_at":           self.created_at,
        }


# ── SemanticProjection (WP2 §3.3) ────────────────────────────────────────────

@dataclass
class SemanticProjection:
    """
    The output of π(s): a probabilistic relational structure over the
    constrained relation space ℛ.
    """
    projection_id:      str
    unit_id:            str
    builder_origin:     str       # "alpha" | "beta"
    matrix_version:     str

    P_r:                dict[str, float]
    subject_candidates: list[str]
    object_candidates:  list[str]

    P_category:         dict[str, float] = field(default_factory=dict)
    P_modality:         dict[str, float] = field(default_factory=dict)
    P_scope:            dict[str, float] = field(default_factory=dict)

    h_norm:             float = 0.0
    status:             EmissionStatus = EmissionStatus.PROJECTED
    emission_rule:      EmissionRule | None = None
    p_illegal:          float = 0.0

    matrix_seal_hash:   str = ""
    created_at:         float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "projection_id":      self.projection_id,
            "unit_id":            self.unit_id,
            "builder_origin":     self.builder_origin,
            "matrix_version":     self.matrix_version,
            "P_r":                self.P_r,
            "subject_candidates": self.subject_candidates,
            "object_candidates":  self.object_candidates,
            "P_category":         self.P_category,
            "P_modality":         self.P_modality,
            "h_norm":             self.h_norm,
            "status":             self.status.value,
            "emission_rule":      self.emission_rule.value if self.emission_rule else None,
            "matrix_seal_hash":   self.matrix_seal_hash,
            "created_at":         self.created_at,
        }


# ── ClaimCandidate (WP2 §3.3.4, §7.2) ───────────────────────────────────────

@dataclass
class ClaimCandidate:
    """
    A discrete relational triple extracted from a SemanticProjection
    by one of the emission rules E1 or E2.
    """
    candidate_id:              str
    projection_id:             str
    unit_id:                   str
    source_ref:                str

    subject:                   str
    relation:                  str
    object:                    str

    relation_score:            float
    rank:                      int = 1
    emission_rule:             EmissionRule = EmissionRule.E1

    modality_hint:             str = "asserted"
    scope_hint:                str = ""
    semantic_category_hint:    str = ""
    h_norm:                    float = 0.0
    matrix_version:            str = ""
    builder_origin:            str = "alpha"

    created_at:                float = field(default_factory=time.time)

    @classmethod
    def new(
        cls,
        projection: SemanticProjection,
        subject: str,
        relation: str,
        object_: str,
        relation_score: float,
        rank: int = 1,
        emission_rule: EmissionRule = EmissionRule.E1,
    ) -> ClaimCandidate:
        return cls(
            candidate_id=str(uuid.uuid4()),
            projection_id=projection.projection_id,
            unit_id=projection.unit_id,
            source_ref="",
            subject=subject,
            relation=relation,
            object=object_,
            relation_score=relation_score,
            rank=rank,
            emission_rule=emission_rule,
            modality_hint=_dominant(projection.P_modality) or "asserted",
            semantic_category_hint=_dominant(projection.P_category) or "",
            h_norm=projection.h_norm,
            matrix_version=projection.matrix_version,
            builder_origin=projection.builder_origin,
        )

    def to_dict(self) -> dict:
        return {
            "candidate_id":           self.candidate_id,
            "projection_id":          self.projection_id,
            "unit_id":                self.unit_id,
            "source_ref":             self.source_ref,
            "subject":                self.subject,
            "relation":               self.relation,
            "object":                 self.object,
            "relation_score":         self.relation_score,
            "rank":                   self.rank,
            "emission_rule":          self.emission_rule.value,
            "modality_hint":          self.modality_hint,
            "semantic_category_hint": self.semantic_category_hint,
            "h_norm":                 self.h_norm,
            "matrix_version":         self.matrix_version,
            "builder_origin":         self.builder_origin,
            "created_at":             self.created_at,
        }


# ── JSD computation (WP2 §3.3.5) ─────────────────────────────────────────────

def compute_jsd(p: dict[str, float], q: dict[str, float]) -> float:
    """Jensen-Shannon Divergence between two relational distributions. Base-2 → JSD ∈ [0, 1]."""
    all_keys = set(p) | set(q)
    if not all_keys:
        return 0.0

    pv = {k: p.get(k, 0.0) for k in all_keys}
    qv = {k: q.get(k, 0.0) for k in all_keys}
    m  = {k: 0.5 * (pv[k] + qv[k]) for k in all_keys}

    def kl(a: dict, b: dict) -> float:
        s = 0.0
        for k in all_keys:
            if a[k] > 0 and b[k] > 0:
                s += a[k] * math.log2(a[k] / b[k])
        return s

    return 0.5 * kl(pv, m) + 0.5 * kl(qv, m)


def compute_h_norm(P_r: dict[str, float]) -> float:
    """Normalised Shannon entropy of a relational distribution. WP2 §7.1."""
    n = len(P_r)
    if n <= 1:
        return 0.0
    h = 0.0
    for p in P_r.values():
        if p > 0:
            h -= p * math.log2(p)
    return h / math.log2(n)


# ── Emission engine (WP2 §7.2, Appendix I.1) ─────────────────────────────────

class EmissionEngine:
    """
    Evaluates emission rules E0–E4 against a SemanticProjection.

    E0 — Structural rejection: P_illegal > τ₀ → STRUCTURAL_VIOLATION
    E1 — Singular: max(P_r) > τ₁ AND H_norm < τ₂ → single ClaimCandidate
    E2 — Multiple: max(P_r) ≤ τ₁ AND H_norm < τ₃ → top-k ClaimCandidates
    E3 — Block: H_norm ≥ τ₃ → AMBIGUOUS, no emission
    E4 — Branch: JSD(A, B) > τ₄ → BRANCH_CANDIDATE (dual-builder only)
    """

    def __init__(self, thresholds: SPLThresholds | None = None):
        self.Θ = thresholds or SPLThresholds()

    def emit(self, projection: SemanticProjection, k: int = 3) -> list[ClaimCandidate]:
        """Apply E0–E3 to a single projection. Returns list of ClaimCandidates."""
        if projection.p_illegal > self.Θ.tau_0:
            projection.status = EmissionStatus.STRUCTURAL_VIOLATION
            projection.emission_rule = EmissionRule.E0
            return []

        P_r = projection.P_r
        if not P_r:
            projection.status = EmissionStatus.AMBIGUOUS
            projection.emission_rule = EmissionRule.E3
            return []

        h = compute_h_norm(P_r)
        projection.h_norm = h

        max_rel  = max(P_r, key=P_r.get)
        max_prob = P_r[max_rel]

        # E3 — block (checked before E1/E2)
        if h >= self.Θ.tau_3:
            projection.status = EmissionStatus.AMBIGUOUS
            projection.emission_rule = EmissionRule.E3
            return []

        # E1 — singular
        if max_prob > self.Θ.tau_1 and h < self.Θ.tau_2:
            projection.status = EmissionStatus.READY_FOR_CLAIM
            projection.emission_rule = EmissionRule.E1
            subj = projection.subject_candidates[0] if projection.subject_candidates else ""
            obj  = projection.object_candidates[0]  if projection.object_candidates  else ""
            return [ClaimCandidate.new(projection, subj, max_rel, obj, max_prob,
                                       rank=1, emission_rule=EmissionRule.E1)]

        # E2 — multiple
        projection.status = EmissionStatus.READY_FOR_CLAIM
        projection.emission_rule = EmissionRule.E2
        top_k = sorted(P_r.items(), key=lambda x: -x[1])[:k]
        subj = projection.subject_candidates[0] if projection.subject_candidates else ""
        obj  = projection.object_candidates[0]  if projection.object_candidates  else ""
        return [
            ClaimCandidate.new(projection, subj, rel, obj, prob,
                               rank=i + 1, emission_rule=EmissionRule.E2)
            for i, (rel, prob) in enumerate(top_k)
        ]

    def apply_e4(self, proj_a: SemanticProjection, proj_b: SemanticProjection) -> float:
        """Compute JSD between two builders. If JSD > τ₄, marks both BRANCH_CANDIDATE."""
        jsd = compute_jsd(proj_a.P_r, proj_b.P_r)
        if jsd > self.Θ.tau_4:
            proj_a.status = EmissionStatus.BRANCH_CANDIDATE
            proj_b.status = EmissionStatus.BRANCH_CANDIDATE
            proj_a.emission_rule = EmissionRule.E4
            proj_b.emission_rule = EmissionRule.E4
        return jsd


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dominant(dist: dict[str, float]) -> str:
    """Return argmax of a distribution dict, or '' if empty."""
    if not dist:
        return ""
    return max(dist, key=dist.get)
