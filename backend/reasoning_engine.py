"""
Rule-based hypothesis scoring for AleXiona.

Computes evidence_support_score for each hypothesis/diagnosis claim
based on supporting and conflicting evidence in the claim set.

score(H) = Σ(ess_i × overlap_weight_i × source_weight_i for supporting i)
           − Σ(conflict_penalty_i for conflicting i)
clamped to [0.0, 1.0]

Only `derived_from` carries epistemic weight for conflict rules.
`related_to` is semantic proximity and does NOT influence scoring.
"""
import re
from datetime import datetime, timezone
from typing import TypedDict

_KEY_TERM_RE = re.compile(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b')
_NEGATION_RE = re.compile(
    r'\b(kein[e]?|nicht|nein|ohne|fehlt|negativ|absent|no\b|not\b|without|negative|ruled out)\b',
    re.IGNORECASE,
)
_HIGH_RE = re.compile(
    r'\b(elevated|increased|high|raised|positive|erhöht|angestiegen|hoch|positiv)\b',
    re.IGNORECASE,
)
_LOW_RE = re.compile(
    r'\b(decreased|low|normal|reduced|within normal|erniedrigt|gesunken|niedrig|normwertig|unauffällig)\b',
    re.IGNORECASE,
)

_EVIDENCE_TYPES = {"finding", "lab", "imaging", "symptom"}
_LEAD_TYPES     = {"diagnosis", "hypothesis"}

# ── Source-type weights ───────────────────────────────────────────────────────
# Guideline- and lab-system-sourced claims carry more epistemic authority;
# LLM-generated claims are down-weighted until confirmed by a clinician.
_SOURCE_WEIGHTS: dict[str, float] = {
    "guideline":         2.0,
    "lab_system":        1.5,
    "clinician":         1.2,
    "imaging_model":     1.0,
    "imported_document": 1.0,
    "llm":               0.5,
}

# ── Conflict-penalty weights ──────────────────────────────────────────────────
# Contradiction severity drives the penalty deducted from the hypothesis score.
# Direct negation ("no fever") is the hardest refutation; quantitative clash
# ("CRP normal" vs expected "elevated") is medium; other overlaps are mild.
_NEGATION_PENALTY     = 2.0
_QUANTITATIVE_PENALTY = 1.5
_DEFAULT_PENALTY      = 1.0

# ── Hard-stop thresholds ──────────────────────────────────────────────────────
_MIN_SUPPORT_SCORE = 0.2   # below this → insufficient evidence
_MAX_CONFLICT_IDS  = 3     # at or above this count → insufficient evidence

# ── Guideline layer ───────────────────────────────────────────────────────────
# Maps normalised diagnosis/hypothesis labels to required and supporting
# evidence terms. Used for missing-evidence detection and guideline-aware hints.
GUIDELINES: dict[str, dict[str, list[str]]] = {
    "pneumonia": {
        "required":   ["fever", "cough"],
        "supporting": ["infiltrate", "crp", "leukocytes", "consolidation"],
        "conflicts":  ["normal imaging"],
    },
    "pulmonary embolism": {
        "required":   ["dyspnea", "tachycardia"],
        "supporting": ["d-dimer", "troponin", "right heart strain", "wells score"],
        "conflicts":  ["normal d-dimer"],
    },
    "sepsis": {
        "required":   ["fever", "infection"],
        "supporting": ["hypotension", "lactate", "leukocytosis", "tachycardia"],
        "conflicts":  [],
    },
    "myocardial infarction": {
        "required":   ["chest pain", "troponin"],
        "supporting": ["ecg changes", "elevated troponin", "st elevation"],
        "conflicts":  ["normal troponin"],
    },
    "heart failure": {
        "required":   ["dyspnea", "edema"],
        "supporting": ["bnp", "cardiomegaly", "pleural effusion"],
        "conflicts":  ["normal bnp"],
    },
}


def _key_terms(text: str) -> set[str]:
    return set(_KEY_TERM_RE.findall(text.lower()))


def _overlap_weight(overlap_count: int) -> float:
    """Non-linear weight: 2 terms → 0.4, 3 → 0.6, 4+ → 0.8."""
    return min(0.8, 0.2 * overlap_count)


def _source_weight(source_type: str) -> float:
    """Return the epistemic multiplier for a given source_type."""
    return _SOURCE_WEIGHTS.get(source_type, 1.0)


def _is_contradicting(evidence_text: str, hypothesis_text: str) -> bool:
    """True if evidence text negates or quantitatively contradicts the hypothesis."""
    if _NEGATION_RE.search(evidence_text):
        return True
    e_high = bool(_HIGH_RE.search(evidence_text))
    e_low  = bool(_LOW_RE.search(evidence_text))
    h_high = bool(_HIGH_RE.search(hypothesis_text))
    h_low  = bool(_LOW_RE.search(hypothesis_text))
    if (e_high and h_low) or (e_low and h_high):
        return True
    return False


def _conflict_penalty(evidence_text: str) -> float:
    """
    Return the penalty to subtract from a hypothesis score for one conflicting
    evidence claim, weighted by the type of contradiction.

    - Direct negation ("no fever", "ruled out")         → 2.0
    - Quantitative clash (high vs low qualifier)         → 1.5
    - Generic overlap with no polarity signal            → 1.0
    """
    if _NEGATION_RE.search(evidence_text):
        return _NEGATION_PENALTY
    if _HIGH_RE.search(evidence_text) or _LOW_RE.search(evidence_text):
        return _QUANTITATIVE_PENALTY
    return _DEFAULT_PENALTY


class HypothesisScore(TypedDict):
    id:                     str
    text:                   str
    claim_type:             str
    rule_based_score:       float
    supporting_claim_ids:   list[str]
    conflicting_claim_ids:  list[str]


def score_hypothesis(hypothesis: dict, all_claims: list[dict]) -> HypothesisScore:
    """
    Compute a rule-based score for a single hypothesis/diagnosis claim.

    Args:
        hypothesis:  A claim dict with claim_type in {diagnosis, hypothesis}.
        all_claims:  All claims for the session (including hypothesis itself).

    Returns:
        HypothesisScore with rule_based_score in [0.0, 1.0].
    """
    hyp_terms = _key_terms(hypothesis["text"])
    support_score:    float     = 0.0
    conflict_total:   float     = 0.0
    supporting_ids:   list[str] = []
    conflicting_ids:  list[str] = []

    for c in all_claims:
        if c["id"] == hypothesis.get("id"):
            continue
        if c.get("status") != "active":
            continue
        if c.get("claim_type") not in _EVIDENCE_TYPES:
            continue

        c_terms  = _key_terms(c["text"])
        overlap  = len(hyp_terms & c_terms)
        if overlap < 2:
            continue

        weight = _overlap_weight(overlap)
        ess    = float(c.get("evidence_support_score", 0.5))

        if _is_contradicting(c["text"], hypothesis["text"]):
            conflict_total += _conflict_penalty(c["text"])
            conflicting_ids.append(c["id"])
        else:
            src_w = _source_weight(c.get("source_type", "llm"))
            support_score += ess * weight * src_w
            supporting_ids.append(c["id"])

    raw   = support_score - conflict_total
    score = max(0.0, min(1.0, raw))

    return HypothesisScore(
        id=hypothesis.get("id", ""),
        text=hypothesis["text"],
        claim_type=hypothesis.get("claim_type", "hypothesis"),
        rule_based_score=round(score, 3),
        supporting_claim_ids=supporting_ids,
        conflicting_claim_ids=conflicting_ids,
    )


def rank_hypotheses(all_claims: list[dict]) -> list[HypothesisScore]:
    """
    Score and rank all hypothesis/diagnosis claims in the claim set.
    Returns list sorted by rule_based_score descending.
    """
    hypotheses = [
        c for c in all_claims
        if c.get("claim_type") in _LEAD_TYPES and c.get("status") == "active"
    ]
    scored = [score_hypothesis(h, all_claims) for h in hypotheses]
    return sorted(scored, key=lambda x: x["rule_based_score"], reverse=True)


def get_missing_evidence_for_differential(
    hypothesis_a: str,
    hypothesis_b: str,
    all_claims: list[dict],
) -> list[str]:
    """
    Return claim texts that would help differentiate hypothesis_a from hypothesis_b
    but are currently missing (not present in the claim set).

    Heuristic: identify key terms unique to each hypothesis and check if any
    lab/imaging/finding claims cover them.
    """
    terms_a = _key_terms(hypothesis_a)
    terms_b = _key_terms(hypothesis_b)
    unique_a = terms_a - terms_b
    unique_b = terms_b - terms_a

    covered: set[str] = set()
    for c in all_claims:
        if c.get("claim_type") in _EVIDENCE_TYPES and c.get("status") == "active":
            covered |= _key_terms(c["text"])

    uncovered_a = unique_a - covered
    uncovered_b = unique_b - terms_a  # relative to the shared context

    hints = []
    if uncovered_a:
        hints.append(f"Evidence covering: {', '.join(sorted(uncovered_a)[:3])}")
    if uncovered_b:
        hints.append(f"Evidence covering: {', '.join(sorted(uncovered_b)[:3])}")
    return hints


def explain_leading(
    ranked: list[HypothesisScore],
    all_claims: list[dict],
) -> dict:
    """
    Explain why the top-ranked hypothesis is currently leading.

    Returns a dict with:
      - leading:      hypothesis text
      - score:        rule_based_score
      - supporting:   texts of claims that support it
      - conflicting:  texts of claims that conflict with it
      - key_missing:  terms/tests that would help differentiate from runner-up
    """
    if not ranked:
        return {"error": "No active hypotheses to explain"}

    top = ranked[0]
    claim_by_id = {c["id"]: c for c in all_claims}

    supporting_texts = [
        claim_by_id[cid]["text"]
        for cid in top["supporting_claim_ids"]
        if cid in claim_by_id
    ]
    conflicting_texts = [
        claim_by_id[cid]["text"]
        for cid in top["conflicting_claim_ids"]
        if cid in claim_by_id
    ]
    key_missing = (
        get_missing_evidence_for_differential(
            top["text"],
            ranked[1]["text"],
            all_claims,
        )
        if len(ranked) > 1
        else []
    )

    return {
        "leading":     top["text"],
        "score":       top["rule_based_score"],
        "supporting":  supporting_texts,
        "conflicting": conflicting_texts,
        "key_missing": key_missing,
    }


def required_evidence_for(hypothesis: str) -> list[str]:
    """
    Return the required evidence terms for a known guideline-defined hypothesis.
    Matching is substring-based (case-insensitive). Returns [] if unknown.
    """
    normalized = hypothesis.lower()
    for key, val in GUIDELINES.items():
        if key in normalized or normalized in key:
            return val.get("required", [])
    return []


def get_confident_leading(ranked: list[HypothesisScore]) -> dict:
    """
    Return the leading hypothesis with a confidence status, or fire a hard stop
    when evidence is insufficient for reliable prioritization.

    Hard stop fires when:
      - No hypotheses exist, OR
      - Top score < MIN_SUPPORT_SCORE (too little supporting evidence), OR
      - Top hypothesis has >= MAX_CONFLICT_IDS conflicting claims (too contested)

    Returns:
      {"status": "confident",    "leading": ..., "score": ...}   or
      {"status": "insufficient", "reason": ..., [optional context]}
    """
    if not ranked:
        return {
            "status": "insufficient",
            "reason": "No active hypotheses found",
        }

    top = ranked[0]
    conflict_count = len(top["conflicting_claim_ids"])

    if top["rule_based_score"] < _MIN_SUPPORT_SCORE:
        return {
            "status":         "insufficient",
            "reason":         "Insufficient evidence for reliable prioritization",
            "leading":        top["text"],
            "score":          top["rule_based_score"],
            "conflict_count": conflict_count,
        }

    if conflict_count >= _MAX_CONFLICT_IDS:
        return {
            "status":         "insufficient",
            "reason":         "Insufficient evidence for reliable prioritization",
            "leading":        top["text"],
            "score":          top["rule_based_score"],
            "conflict_count": conflict_count,
        }

    return {
        "status":  "confident",
        "leading": top["text"],
        "score":   top["rule_based_score"],
    }


def build_case_snapshot(all_claims: list[dict]) -> dict:
    """
    Create a point-in-time snapshot of the case state.

    Returns a dict with timestamp, ranked hypotheses, and claim counts — suitable
    for audit trails, longitudinal comparison, and state diffing.
    """
    ranked = rank_hypotheses(all_claims)
    leading = ranked[0] if ranked else None
    confidence = get_confident_leading(ranked)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "leading_hypothesis": leading["text"] if leading else None,
        "leading_score":      leading["rule_based_score"] if leading else None,
        "confidence_status":  confidence["status"],
        "ranked_hypotheses": [
            {
                "id":    h["id"],
                "text":  h["text"],
                "score": h["rule_based_score"],
                "supporting_count":  len(h["supporting_claim_ids"]),
                "conflicting_count": len(h["conflicting_claim_ids"]),
            }
            for h in ranked
        ],
        "active_claim_count": sum(
            1 for c in all_claims if c.get("status") == "active"
        ),
        "total_claim_count": len(all_claims),
    }


def build_reasoning_context(all_claims: list[dict]) -> str:
    """
    Build a structured context string for the LLM reasoning prompt that includes
    rule-based hypothesis scores as anchor points.
    """
    ranked = rank_hypotheses(all_claims)
    confidence = get_confident_leading(ranked)
    lines = []

    if ranked:
        lines.append("=== RULE-BASED HYPOTHESIS SCORES (source-weighted; use as anchors) ===")
        if confidence["status"] == "insufficient":
            lines.append(f"  ⚠ {confidence['reason']}")
        for h in ranked:
            lines.append(
                f"  [{h['claim_type'].upper()}] {h['text'][:80]}"
                f" → rule_score={h['rule_based_score']:.2f}"
                f" (supporting: {len(h['supporting_claim_ids'])}"
                f", conflicting: {len(h['conflicting_claim_ids'])})"
            )
        lines.append("")

    lines.append("=== ALL CLAIMS ===")
    for c in all_claims:
        lines.append(
            f"- [{c.get('claim_type', 'finding').upper()}] {c['text']} "
            f"(ess={int(c.get('evidence_support_score', 0.8)*100)}%"
            f", src={c.get('source_type', 'llm')}"
            f", status={c.get('status', 'active')})"
        )

    return "\n".join(lines)
