"""
Rule-based hypothesis scoring for AleXiona.

Computes evidence_support_score for each hypothesis/diagnosis claim
based on supporting and conflicting evidence in the claim set.

score(H) = Σ(ess_i × overlap_weight_i for supporting i)
           − 2 × conflict_count
clamped to [0.0, 1.0]

Only `derived_from` carries epistemic weight for conflict rules.
`related_to` is semantic proximity and does NOT influence scoring.
"""
import re
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


def _key_terms(text: str) -> set[str]:
    return set(_KEY_TERM_RE.findall(text.lower()))


def _overlap_weight(overlap_count: int) -> float:
    """Non-linear weight: 2 terms → 0.4, 3 → 0.6, 4+ → 0.8."""
    return min(0.8, 0.2 * overlap_count)


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
    support_score    = 0.0
    conflict_count   = 0
    supporting_ids:  list[str] = []
    conflicting_ids: list[str] = []

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
            conflict_count += 1
            conflicting_ids.append(c["id"])
        else:
            support_score += ess * weight
            supporting_ids.append(c["id"])

    raw   = support_score - 2.0 * conflict_count
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
    uncovered_b = unique_b - covered

    hints = []
    if uncovered_a:
        hints.append(f"Evidence covering: {', '.join(sorted(uncovered_a)[:3])}")
    if uncovered_b:
        hints.append(f"Evidence covering: {', '.join(sorted(uncovered_b)[:3])}")
    return hints


def build_reasoning_context(all_claims: list[dict]) -> str:
    """
    Build a structured context string for the LLM reasoning prompt that includes
    rule-based hypothesis scores as anchor points.
    """
    ranked = rank_hypotheses(all_claims)
    lines = []

    if ranked:
        lines.append("=== RULE-BASED HYPOTHESIS SCORES (use as anchors, refine with clinical context) ===")
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
