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
from lab_parser import parse_lab_value, qualitative_for_token, lab_summary, LAB_THRESHOLDS
from composite_scores import compute_relevant_scores

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

_EVIDENCE_TYPES  = {"finding", "lab", "imaging", "symptom"}
_LEAD_TYPES      = {"diagnosis", "hypothesis"}
# Statuses that count as "epistemically active" in scoring.
# refuted / withdrawn / resolved / superseded are excluded.
# contested is included — it means under review, not invalidated.
_ACTIVE_STATUSES = {"active", "observed", "inferred", "confirmed", "contested"}

# Source-weight boost applied to evidence claims with status="confirmed"
_CONFIRMED_BOOST = 1.5

# ── Hypothesis alias map ──────────────────────────────────────────────────────
# Maps canonical guideline keys to common synonyms/abbreviations.
# Used by normalize_hypothesis() so CAP, community-acquired pneumonia, etc.
# all resolve to the "pneumonia" guideline key.
HYPOTHESIS_ALIASES: dict[str, list[str]] = {
    "pneumonia": [
        "pneumonia", "cap", "community acquired pneumonia",
        "community-acquired pneumonia", "pneumonie",
    ],
    "pulmonary embolism": [
        "pulmonary embolism", "lung embolism", "lungenembolie", "pe ", "pe-",
    ],
    "sepsis": [
        "sepsis", "septic shock", "septischer schock", "urosepsis",
    ],
    "myocardial infarction": [
        "myocardial infarction", "heart attack", "stemi", "nstemi",
        "acute coronary", "acs", "herzinfarkt",
    ],
    "heart failure": [
        "heart failure", "cardiac failure", "herzinsuffizienz", "chf",
    ],
}

# ── Source-type weights ───────────────────────────────────────────────────────
# Epistemic authority hierarchy.  Patient-generated sources are weighted lower
# than clinical instruments — not because they are less valuable as signals, but
# because their error profiles differ and they must not be treated as
# clinical-grade evidence without normalization.
_SOURCE_WEIGHTS: dict[str, float] = {
    # Clinical / institutional
    "guideline":         2.0,
    "lab_system":        1.5,
    "clinician":         1.2,
    "imaging_model":     1.0,
    "imported_document": 1.0,
    "llm":               0.5,
    # Patient-generated (own epistemic tier)
    "wearable":          0.7,
    "home_device":       0.6,
    "caregiver_report":  0.5,
    "patient_report":    0.4,
}

# Patient-generated source types — subject to extra safeguards in scoring
_PATIENT_SOURCES = {"patient_report", "wearable", "home_device", "caregiver_report"}

# ── Trend signal scoring ──────────────────────────────────────────────────────
# TrendSignals stored as Claims carry a clinical_flag in brackets, e.g.
# "heart_rate rising 15.2% over 3.1h [tachycardia_trend]"
# When a trend claim with a relevant clinical_flag co-occurs with a hypothesis,
# its base support contribution is multiplied by _TREND_BOOST.
_TREND_FLAG_RE = re.compile(r'\[([a-z_]+_trend)\]')
_TREND_BOOST   = 1.4   # 40% boost — directional signals are strong evidence

# clinical_flag → hypothesis keywords that this trend strengthens
_TREND_HYPOTHESIS_KEYWORDS: dict[str, list[str]] = {
    "hypoxia_trend":      ["pneumonia", "embolism", "ards", "respiratory", "hypoxia"],
    "tachycardia_trend":  ["sepsis", "embolism", "failure", "shock", "tachycardia"],
    "bradycardia_trend":  ["block", "hypothyroid", "vagal"],
    "fever_trend":        ["sepsis", "pneumonia", "infection", "meningitis", "endocarditis"],
    "tachypnea_trend":    ["pneumonia", "ards", "embolism", "acidosis", "tachypnea"],
    "hypotension_trend":  ["sepsis", "embolism", "failure", "shock", "hypotension"],
    "hypertension_trend": ["hypertension", "renal", "hyperaldosteronism"],
    "hyperglycemia_trend":["sepsis", "diabetes", "pancreatitis", "hyperglycemia"],
    "hypoglycemia_trend": ["sepsis", "hepatic", "insulin", "hypoglycemia"],
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

# ── Temporal decay ─────────────────────────────────────────────────────────────
# Evidence loses relevance over time.  Each claim type has a "half-life" in hours:
# after that many hours the weight is 0.5; it is clamped to a floor of 0.25.
_TEMPORAL_HALF_LIFE_H: dict[str, float] = {
    "lab":     12.0,   # lab values: short half-life (results change quickly)
    "finding": 48.0,   # clinical findings: moderate
    "symptom": 72.0,   # symptoms: slower to change
    "imaging": 96.0,   # imaging: stable longer
}

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


def _key_terms_with_negation(text: str) -> set[str]:
    """Extract key terms, prefixing terms immediately after a negation with 'negated_'.

    E.g. "no fever present"       → {"negated_fever", "present"}
         "fever confirmed"         → {"fever", "confirmed"}
         "kein Fieber vorhanden"   → {"negated_fieber", "vorhanden"}
    """
    t = text.lower()
    negation_end_positions = [m.end() for m in _NEGATION_RE.finditer(t)]
    result: set[str] = set()
    for m in _KEY_TERM_RE.finditer(t):
        word = m.group(0)
        pos  = m.start()
        # Negation must end within 20 chars before this word starts
        is_negated = any(ne <= pos <= ne + 20 for ne in negation_end_positions)
        result.add(f"negated_{word}" if is_negated else word)
    return result


def normalize_hypothesis(text: str) -> str:
    """Map hypothesis text to its canonical guideline key via alias lookup.

    Falls back to direct GUIDELINES substring match, then the lowercased text.
    """
    t = text.lower()
    for canonical, aliases in HYPOTHESIS_ALIASES.items():
        if any(alias in t for alias in aliases):
            return canonical
    for key in GUIDELINES:
        if key in t or t in key:
            return key
    return t


def _overlap_weight(overlap_count: int) -> float:
    """Non-linear weight: 2 terms → 0.4, 3 → 0.6, 4+ → 0.8."""
    return min(0.8, 0.2 * overlap_count)


def _parse_offset_hours(time_offset) -> float | None:
    """Extract numeric hours from a time_offset string like 't+6h' or '24h'."""
    if not time_offset:
        return None
    m = re.match(r'^(?:t\+)?(\d+(?:\.\d+)?)h?$', str(time_offset).strip(), re.IGNORECASE)
    return float(m.group(1)) if m else None


def _hours_since_event(claim: dict) -> float | None:
    """Compute how many hours old the claim's event is.

    Priority:
      1. event_time (absolute datetime — most precise)
      2. time_offset (relative hours — legacy)
    Returns None if no temporal information is available.
    """
    # 1. Absolute event_time (Alexandria principle — preferred)
    event_time = claim.get("event_time")
    if event_time is not None:
        now = datetime.now(timezone.utc)
        if isinstance(event_time, str):
            try:
                from datetime import datetime as _dt
                event_time = _dt.fromisoformat(event_time.replace("Z", "+00:00"))
            except ValueError:
                event_time = None
        if event_time is not None:
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            delta_h = (now - event_time).total_seconds() / 3600
            return max(0.0, delta_h)

    # 2. Fallback: relative time_offset
    return _parse_offset_hours(claim.get("time_offset"))


def _temporal_weight(claim: dict) -> float:
    """Return a [0.25, 1.0] decay multiplier based on claim age and type.

    Uses event_time (absolute) when available, falls back to time_offset.
    Exponential half-life decay:  w = 0.5 ** (hours / half_life)
    Clamped to [0.25, 1.0] — old evidence down-weighted but never ignored.
    """
    hours      = _hours_since_event(claim)
    if hours is None:
        return 1.0  # no temporal info → no decay applied
    claim_type = claim.get("claim_type", "finding")
    half_life  = _TEMPORAL_HALF_LIFE_H.get(claim_type, 48.0)
    weight     = 0.5 ** (hours / half_life)
    return max(0.25, weight)


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


class ClaimContributionData(TypedDict):
    claim_id:          str
    claim_text:        str
    claim_type:        str
    source_type:       str
    evidence_tier:     str | None
    spl_emission_rule: str | None
    direction:         str    # "supporting" | "conflicting"
    contribution:      float  # always positive magnitude; direction carries the sign
    ess:               float
    overlap_weight:    float  # 0.0 for conflicting claims
    source_weight:     float
    temporal_weight:   float
    trend_boosted:     bool


class HypothesisExplanationData(TypedDict):
    id:               str
    text:             str
    claim_type:       str
    rule_based_score: float
    total_support:    float
    total_conflict:   float
    contributions:    list[ClaimContributionData]
    guideline:        dict


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
        c_status = c.get("status", "active")
        if c_status not in _ACTIVE_STATUSES:
            continue
        if c.get("claim_type") not in _EVIDENCE_TYPES:
            continue

        c_terms_neg = _key_terms_with_negation(c["text"])
        negated_c   = {t[8:] for t in c_terms_neg if t.startswith("negated_")}
        c_positive  = {t for t in c_terms_neg if not t.startswith("negated_")}

        # Negated term directly matches a hypothesis term → conflict even with
        # only 1-term overlap (catches "no fever" vs "fever" patterns)
        negated_overlap = len(negated_c & hyp_terms)
        if negated_overlap > 0:
            conflict_total += _conflict_penalty(c["text"])
            conflicting_ids.append(c["id"])
            continue

        overlap = len(hyp_terms & c_positive)
        if overlap < 2:
            continue

        weight = _overlap_weight(overlap)
        ess    = float(c.get("evidence_support_score", 0.5))

        if _is_contradicting(c["text"], hypothesis["text"]):
            conflict_total += _conflict_penalty(c["text"])
            conflicting_ids.append(c["id"])
        else:
            src_type = c.get("source_type", "llm")
            src_w    = _source_weight(src_type)
            t_w      = _temporal_weight(c)
            # Safeguard: patient-generated evidence never receives the confirmed boost
            # (1.0 instead of 1.5); and is halved when supporting a diagnosis-type
            # hypothesis — patient data can contribute at symptom/finding level, but
            # should not directly confirm a clinical diagnosis.
            is_patient    = src_type in _PATIENT_SOURCES
            is_diagnosis  = hypothesis.get("claim_type") == "diagnosis"
            confirm_w     = 1.0 if is_patient else (_CONFIRMED_BOOST if c_status == "confirmed" else 1.0)
            patient_diag_w = 0.5 if (is_patient and is_diagnosis) else 1.0
            support_score += ess * weight * src_w * t_w * confirm_w * patient_diag_w
            supporting_ids.append(c["id"])

    # ── Trend signal boost ────────────────────────────────────────────────────
    # Trend claims (source_ref starts with "trend:") carry a clinical_flag in
    # brackets.  When the flag maps to keywords present in the hypothesis text,
    # multiply the trend claim's marginal support by _TREND_BOOST.
    hyp_text_lower = hypothesis["text"].lower()
    for c in all_claims:
        src_ref = c.get("source_ref", "")
        if not (src_ref.startswith("trend:") or src_ref.startswith("trend_signal:")):
            continue
        if c.get("status", "active") not in _ACTIVE_STATUSES:
            continue
        flag_match = _TREND_FLAG_RE.search(c.get("text", ""))
        if not flag_match:
            continue
        flag     = flag_match.group(1)
        keywords = _TREND_HYPOTHESIS_KEYWORDS.get(flag, [])
        if not any(kw in hyp_text_lower for kw in keywords):
            continue
        # Compute the trend claim's base contribution and apply boost
        ess   = float(c.get("evidence_support_score", 0.5))
        src_w = _source_weight(c.get("source_type", "wearable"))
        t_w   = _temporal_weight(c)
        # Trend boost is added as additional support (not replacing base scoring)
        boost = ess * src_w * t_w * (_TREND_BOOST - 1.0)
        support_score += boost
        if c["id"] not in supporting_ids:
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
    Hypotheses with status="refuted" are hard-excluded from the ranking.
    """
    hypotheses = [
        c for c in all_claims
        if c.get("claim_type") in _LEAD_TYPES
        and c.get("status") in _ACTIVE_STATUSES  # refuted/withdrawn → hard excluded
    ]
    scored = [score_hypothesis(h, all_claims) for h in hypotheses]
    return sorted(scored, key=lambda x: x["rule_based_score"], reverse=True)


def _explain_single_hypothesis(
    hypothesis: dict,
    all_claims: list[dict],
) -> HypothesisExplanationData:
    """
    Like score_hypothesis() but captures per-claim contribution breakdown.
    Returns HypothesisExplanationData with full ClaimContributionData list.
    """
    hyp_terms      = _key_terms(hypothesis["text"])
    hyp_text_lower = hypothesis["text"].lower()

    support_score:  float                       = 0.0
    conflict_total: float                       = 0.0
    contributions:  list[ClaimContributionData] = []
    seen_ids:       set[str]                    = set()

    for c in all_claims:
        if c["id"] == hypothesis.get("id"):
            continue
        c_status = c.get("status", "active")
        if c_status not in _ACTIVE_STATUSES:
            continue
        if c.get("claim_type") not in _EVIDENCE_TYPES:
            continue

        c_terms_neg = _key_terms_with_negation(c["text"])
        negated_c   = {t[8:] for t in c_terms_neg if t.startswith("negated_")}
        c_positive  = {t for t in c_terms_neg if not t.startswith("negated_")}

        # Negated overlap → conflict
        negated_overlap = len(negated_c & hyp_terms)
        if negated_overlap > 0:
            penalty = _conflict_penalty(c["text"])
            conflict_total += penalty
            contributions.append(ClaimContributionData(
                claim_id=c["id"],
                claim_text=c["text"],
                claim_type=c.get("claim_type", "finding"),
                source_type=c.get("source_type", "llm"),
                evidence_tier=c.get("evidence_tier"),
                spl_emission_rule=c.get("spl_emission_rule"),
                direction="conflicting",
                contribution=round(penalty, 4),
                ess=float(c.get("evidence_support_score", 0.5)),
                overlap_weight=0.0,
                source_weight=round(_source_weight(c.get("source_type", "llm")), 3),
                temporal_weight=round(_temporal_weight(c), 3),
                trend_boosted=False,
            ))
            seen_ids.add(c["id"])
            continue

        overlap = len(hyp_terms & c_positive)
        if overlap < 2:
            continue

        weight = _overlap_weight(overlap)
        ess    = float(c.get("evidence_support_score", 0.5))

        if _is_contradicting(c["text"], hypothesis["text"]):
            penalty = _conflict_penalty(c["text"])
            conflict_total += penalty
            contributions.append(ClaimContributionData(
                claim_id=c["id"],
                claim_text=c["text"],
                claim_type=c.get("claim_type", "finding"),
                source_type=c.get("source_type", "llm"),
                evidence_tier=c.get("evidence_tier"),
                spl_emission_rule=c.get("spl_emission_rule"),
                direction="conflicting",
                contribution=round(penalty, 4),
                ess=ess,
                overlap_weight=round(weight, 3),
                source_weight=round(_source_weight(c.get("source_type", "llm")), 3),
                temporal_weight=round(_temporal_weight(c), 3),
                trend_boosted=False,
            ))
        else:
            src_type    = c.get("source_type", "llm")
            src_w       = _source_weight(src_type)
            t_w         = _temporal_weight(c)
            is_patient   = src_type in _PATIENT_SOURCES
            is_diagnosis = hypothesis.get("claim_type") == "diagnosis"
            confirm_w    = 1.0 if is_patient else (_CONFIRMED_BOOST if c_status == "confirmed" else 1.0)
            patient_diag_w = 0.5 if (is_patient and is_diagnosis) else 1.0
            contrib = ess * weight * src_w * t_w * confirm_w * patient_diag_w
            support_score += contrib
            contributions.append(ClaimContributionData(
                claim_id=c["id"],
                claim_text=c["text"],
                claim_type=c.get("claim_type", "finding"),
                source_type=c.get("source_type", "llm"),
                evidence_tier=c.get("evidence_tier"),
                spl_emission_rule=c.get("spl_emission_rule"),
                direction="supporting",
                contribution=round(contrib, 4),
                ess=ess,
                overlap_weight=round(weight, 3),
                source_weight=round(src_w, 3),
                temporal_weight=round(t_w, 3),
                trend_boosted=False,
            ))
        seen_ids.add(c["id"])

    # Trend signal boost — mark boosted claims
    for c in all_claims:
        src_ref = c.get("source_ref", "")
        if not (src_ref.startswith("trend:") or src_ref.startswith("trend_signal:")):
            continue
        if c.get("status", "active") not in _ACTIVE_STATUSES:
            continue
        flag_match = _TREND_FLAG_RE.search(c.get("text", ""))
        if not flag_match:
            continue
        flag     = flag_match.group(1)
        keywords = _TREND_HYPOTHESIS_KEYWORDS.get(flag, [])
        if not any(kw in hyp_text_lower for kw in keywords):
            continue
        ess   = float(c.get("evidence_support_score", 0.5))
        src_w = _source_weight(c.get("source_type", "wearable"))
        t_w   = _temporal_weight(c)
        boost = ess * src_w * t_w * (_TREND_BOOST - 1.0)
        support_score += boost
        # Update existing entry if seen, else append new
        existing = next((x for x in contributions if x["claim_id"] == c["id"]), None)
        if existing:
            existing["contribution"] = round(existing["contribution"] + boost, 4)
            existing["trend_boosted"] = True
        else:
            contributions.append(ClaimContributionData(
                claim_id=c["id"],
                claim_text=c["text"],
                claim_type=c.get("claim_type", "finding"),
                source_type=c.get("source_type", "wearable"),
                evidence_tier=c.get("evidence_tier"),
                spl_emission_rule=c.get("spl_emission_rule"),
                direction="supporting",
                contribution=round(boost, 4),
                ess=ess,
                overlap_weight=0.0,
                source_weight=round(src_w, 3),
                temporal_weight=round(t_w, 3),
                trend_boosted=True,
            ))

    raw   = support_score - conflict_total
    score = max(0.0, min(1.0, raw))

    # Sort contributions: supporting first (desc), then conflicting (desc by magnitude)
    contributions.sort(key=lambda x: (x["direction"] != "supporting", -x["contribution"]))

    return HypothesisExplanationData(
        id=hypothesis.get("id", ""),
        text=hypothesis["text"],
        claim_type=hypothesis.get("claim_type", "hypothesis"),
        rule_based_score=round(score, 3),
        total_support=round(support_score, 3),
        total_conflict=round(conflict_total, 3),
        contributions=contributions,
        guideline=evaluate_guideline(hypothesis["text"], all_claims),
    )


def explain_hypothesis_scores(
    all_claims: list[dict],
) -> list[HypothesisExplanationData]:
    """
    Full per-claim contribution breakdown for all active hypotheses.

    Returns one HypothesisExplanationData per hypothesis, sorted by
    rule_based_score descending — same order as rank_hypotheses().

    Each entry contains:
    - contributions: ordered list of ClaimContributionData with
      direction, contribution magnitude, ess, source_weight,
      temporal_weight, spl_emission_rule, and trend_boosted flag
    - total_support / total_conflict: raw sums before clamping
    - guideline: evaluate_guideline() output for the hypothesis
    """
    hypotheses = [
        c for c in all_claims
        if c.get("claim_type") in _LEAD_TYPES
        and c.get("status") in _ACTIVE_STATUSES
    ]
    explained = [_explain_single_hypothesis(h, all_claims) for h in hypotheses]
    return sorted(explained, key=lambda x: x["rule_based_score"], reverse=True)


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
    Uses normalize_hypothesis() for alias-aware matching. Returns [] if unknown.
    """
    label = normalize_hypothesis(hypothesis)
    return GUIDELINES.get(label, {}).get("required", [])


def _term_present_in_claims(term: str, claims: list[dict]) -> bool:
    """True if *term* appears non-negated in any active evidence claim text.

    For terms that correspond to a known lab token (e.g. "crp", "troponin"),
    the function also considers whether a parsed numeric value confirms the
    expected qualitative direction (high/low).  A claim saying "CRP 145 mg/L"
    matches the guideline term "crp" even without the word "elevated".
    """
    t_lower = term.lower()

    # Check if the term maps to a known lab token with a quantitative threshold.
    # This lets "CRP 145 mg/L" match the guideline term "crp" or "crp elevated".
    lab_token: Optional[str] = None
    for token, spec in LAB_THRESHOLDS.items():
        if t_lower in spec["aliases"] or token == t_lower:
            lab_token = token
            break

    for c in claims:
        if c.get("status") not in _ACTIVE_STATUSES or c.get("claim_type") not in _EVIDENCE_TYPES:
            continue
        text = c["text"].lower()

        # Quantitative lab match: "CRP 145 mg/L" confirms "crp"/"crp elevated"
        if lab_token:
            parsed = parse_lab_value(c["text"])
            if parsed and parsed.token == lab_token:
                # Only count as "present" if the value is in the expected direction.
                # "elevated" or bare token name → requires high; "low" → requires low.
                needs_high = any(w in t_lower for w in ("elevated", "high", "erhöht", "angestiegen"))
                needs_low  = any(w in t_lower for w in ("low", "normal", "niedrig", "erniedrigt"))
                if needs_high and parsed.qualitative == "high":
                    return True
                if needs_low and parsed.qualitative in ("low", "normal"):
                    return True
                if not needs_high and not needs_low:
                    # bare token — any non-negated numeric match qualifies
                    return True

        # Text substring match with negation guard
        idx = text.find(t_lower)
        if idx == -1:
            continue
        context_before = text[max(0, idx - 25):idx]
        if not _NEGATION_RE.search(context_before):
            return True
    return False


# Type alias for Optional used in _term_present_in_claims above
from typing import Optional  # noqa: E402 (already imported implicitly via TypedDict)


def evaluate_guideline(hypothesis_text: str, all_claims: list[dict]) -> dict:
    """Evaluate how well current claims satisfy guideline criteria for a hypothesis.

    Returns:
        label                - canonical guideline key (or lowercased text if unknown)
        rule_found           - whether a guideline entry exists
        eligible             - True if at least half of required terms are present
        required_present     - required terms currently evidenced
        required_missing     - required terms with no active evidence
        supporting_present   - supporting terms currently evidenced
        conflicting_present  - conflicting terms currently evidenced
        missing_priority     - ordered list: required_missing first, then missing supporting
    """
    label = normalize_hypothesis(hypothesis_text)
    rule  = GUIDELINES.get(label)
    if not rule:
        return {
            "label":               label,
            "rule_found":          False,
            "eligible":            False,
            "required_present":    [],
            "required_missing":    [],
            "supporting_present":  [],
            "conflicting_present": [],
            "missing_priority":    [],
        }

    required_present    = [r for r in rule["required"]   if _term_present_in_claims(r, all_claims)]
    required_missing    = [r for r in rule["required"]   if r not in required_present]
    supporting_present  = [s for s in rule["supporting"] if _term_present_in_claims(s, all_claims)]
    conflicting_present = [cf for cf in rule["conflicts"] if _term_present_in_claims(cf, all_claims)]

    # Eligible when at least half of required terms have active evidence
    min_required = max(1, (len(rule["required"]) + 1) // 2)
    eligible = len(required_present) >= min_required

    supporting_missing = [s for s in rule["supporting"] if s not in supporting_present]
    missing_priority   = required_missing + supporting_missing

    return {
        "label":               label,
        "rule_found":          True,
        "eligible":            eligible,
        "required_present":    required_present,
        "required_missing":    required_missing,
        "supporting_present":  supporting_present,
        "conflicting_present": conflicting_present,
        "missing_priority":    missing_priority,
    }


def guideline_score(hypothesis_text: str, all_claims: list[dict]) -> float:
    """Weighted guideline-layer score for a hypothesis.

    Weights:
        +2.0 per required  term present
        +1.5 per supporting term present
        −2.5 per conflicting term present
        −3.0 if hypothesis is not eligible (< half of required terms met)
    """
    result = evaluate_guideline(hypothesis_text, all_claims)
    if not result["rule_found"]:
        return 0.0
    score = (
        2.0 * len(result["required_present"])
        + 1.5 * len(result["supporting_present"])
        - 2.5 * len(result["conflicting_present"])
    )
    if not result["eligible"]:
        score -= 3.0
    return score


def evaluate_all_guidelines(all_claims: list[dict]) -> dict[str, dict]:
    """Evaluate guideline criteria for every active/confirmed hypothesis/diagnosis claim."""
    hypotheses = [
        c for c in all_claims
        if c.get("claim_type") in _LEAD_TYPES
        and c.get("status") in _ACTIVE_STATUSES
    ]
    return {h["text"]: evaluate_guideline(h["text"], all_claims) for h in hypotheses}


def prioritize_missing(guideline_result: dict) -> list[str]:
    """Return missing evidence terms sorted by priority: required first, then supporting."""
    required_missing   = guideline_result.get("required_missing", [])
    supporting_missing = [
        s for s in guideline_result.get("missing_priority", [])
        if s not in required_missing
    ]
    return required_missing + supporting_missing


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
    rule-based hypothesis scores, guideline evaluations, composite clinical scores,
    and a parsed lab summary as anchor points.
    """
    ranked     = rank_hypotheses(all_claims)
    confidence = get_confident_leading(ranked)
    guidelines = evaluate_all_guidelines(all_claims)
    lines: list[str] = []

    if ranked:
        lines.append("=== RULE-BASED HYPOTHESIS SCORES (source-weighted; use as anchors) ===")
        if confidence["status"] == "insufficient":
            lines.append(f"  ⚠ {confidence['reason']}")
        for h in ranked:
            g = guidelines.get(h["text"], {})
            g_score  = guideline_score(h["text"], all_claims)
            g_status = "✓ eligible" if g.get("eligible") else ("– no rule" if not g.get("rule_found") else "✗ not eligible")
            lines.append(
                f"  [{h['claim_type'].upper()}] {h['text'][:80]}"
                f" → rule_score={h['rule_based_score']:.2f}"
                f"  guideline_score={g_score:.1f} ({g_status})"
                f"  (supporting: {len(h['supporting_claim_ids'])}"
                f", conflicting: {len(h['conflicting_claim_ids'])})"
            )
            if g.get("missing_priority"):
                top_missing = prioritize_missing(g)[:3]
                lines.append(f"    missing: {', '.join(top_missing)}")
        lines.append("")

    # Composite clinical scores
    composite = compute_relevant_scores(all_claims)
    if composite:
        lines.append("=== COMPOSITE CLINICAL SCORES ===")
        for cs in composite:
            met_str = "; ".join(cs.criteria_met) if cs.criteria_met else "none"
            lines.append(
                f"  {cs.name}: {cs.score}  → {cs.interpretation.upper()} RISK"
                f"  (criteria: {met_str})"
            )
            if cs.criteria_missing:
                lines.append(f"    undetermined: {', '.join(cs.criteria_missing)}")
        lines.append("")

    # Parsed lab values summary
    labs = lab_summary(all_claims)
    if labs:
        lines.append("=== PARSED LAB VALUES ===")
        for token, r in sorted(labs.items()):
            lines.append(
                f"  {token}: {r.value} {r.unit}  [{r.qualitative.upper()}]"
                + (f"  — {r.clinical_note}" if r.clinical_note else "")
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
