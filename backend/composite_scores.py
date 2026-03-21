"""
Composite clinical scoring for AleXiona.

Computes well-validated bedside scores from the structured claim set:
  - qSOFA   (quick Sepsis-related Organ Failure Assessment)
  - Wells PE (Wells score for pulmonary embolism)
  - GRACE   (Global Registry of Acute Coronary Events — simplified)

Each scorer returns a CompositeScore containing:
  - score        : numeric result
  - interpretation : clinical meaning (low / intermediate / high risk)
  - criteria_met : which criteria fired
  - criteria_missing : which criteria couldn't be determined
  - as_claim     : dict ready to be injected into the claim store as a
                   source_type="guideline", claim_type="finding" claim
"""
from __future__ import annotations
from dataclasses import dataclass, field
from lab_parser import qualitative_for_token, parse_lab_value


@dataclass
class CompositeScore:
    name:              str
    score:             int | float
    interpretation:    str           # "low" | "intermediate" | "high"
    criteria_met:      list[str]
    criteria_missing:  list[str]
    as_claim:          dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.as_claim = {
            "text":                   self._claim_text(),
            "claim_type":             "finding",
            "source_type":            "guideline",
            "evidence_support_score": self._ess(),
            "status":                 "active",
            "entities":               [self.name],
            "relations":              [],
        }

    def _claim_text(self) -> str:
        return (
            f"{self.name} score {self.score} "
            f"({self.interpretation} risk) — "
            f"criteria: {', '.join(self.criteria_met) if self.criteria_met else 'none'}"
        )

    def _ess(self) -> float:
        """Map risk interpretation to evidence_support_score."""
        return {"high": 0.90, "intermediate": 0.65, "low": 0.30}.get(
            self.interpretation, 0.5
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _text_matches_any(text: str, terms: list[str]) -> bool:
    t = text.lower()
    return any(term in t for term in terms)


def _claim_has_term(claims: list[dict], terms: list[str], status: str = "active") -> bool:
    for c in claims:
        if c.get("status") != status:
            continue
        if _text_matches_any(c.get("text", ""), terms):
            return True
    return False


def _negation_present(claims: list[dict], terms: list[str]) -> bool:
    """True if any claim explicitly negates all of *terms* (e.g. 'no DVT')."""
    import re
    _NEG = re.compile(
        r'\b(no|not|without|kein[e]?|nicht|ohne|absent|negativ|ruled out)\b',
        re.IGNORECASE,
    )
    for c in claims:
        if c.get("status") != "active":
            continue
        text = c.get("text", "").lower()
        if _NEG.search(text) and any(t in text for t in terms):
            return True
    return False


# ── qSOFA ─────────────────────────────────────────────────────────────────────

def compute_qsofa(all_claims: list[dict]) -> CompositeScore:
    """Quick Sepsis-related Organ Failure Assessment (Singer et al., JAMA 2016).

    Criteria (1 point each):
      1. Respiratory rate ≥ 22 /min
      2. Altered mentation  (GCS < 15)
      3. Systolic BP ≤ 100 mmHg

    Score ≥ 2 → high risk of sepsis-related organ dysfunction.
    """
    criteria_met:     list[str] = []
    criteria_missing: list[str] = []

    # 1. RR ≥ 22
    rr_qual = qualitative_for_token("respiratory_rate", all_claims)
    if rr_qual == "high":
        criteria_met.append("RR ≥ 22/min")
    elif rr_qual is None:
        if _claim_has_term(all_claims, ["tachypnea", "tachypnoea", "respiratory rate", "atemfrequenz"]):
            criteria_met.append("RR ≥ 22/min (textual)")
        else:
            criteria_missing.append("Respiratory rate")

    # 2. Altered mentation (GCS < 15)
    gcs_qual = qualitative_for_token("gcs", all_claims)
    if gcs_qual == "low":
        criteria_met.append("GCS < 15")
    elif gcs_qual is None:
        if _claim_has_term(all_claims, ["confusion", "altered mental", "disoriented",
                                        "agitation", "verwirrt", "desorientiert", "bewusstsein"]):
            criteria_met.append("Altered mentation (textual)")
        else:
            criteria_missing.append("Mental status / GCS")

    # 3. SBP ≤ 100
    sbp_qual = qualitative_for_token("systolic_bp", all_claims)
    if sbp_qual == "low":
        criteria_met.append("SBP ≤ 100 mmHg")
    elif sbp_qual is None:
        if _claim_has_term(all_claims, ["hypotension", "hypotonie", "low blood pressure"]):
            criteria_met.append("Hypotension (textual)")
        else:
            criteria_missing.append("Systolic blood pressure")

    score = len(criteria_met)
    if score >= 2:
        interpretation = "high"
    elif score == 1:
        interpretation = "intermediate"
    else:
        interpretation = "low"

    return CompositeScore(
        name="qSOFA",
        score=score,
        interpretation=interpretation,
        criteria_met=criteria_met,
        criteria_missing=criteria_missing,
    )


# ── Wells PE ──────────────────────────────────────────────────────────────────

def compute_wells_pe(all_claims: list[dict]) -> CompositeScore:
    """Wells score for pulmonary embolism (Wells et al., Thromb Haemost 2000).

    Points:
      +3   Clinical signs / symptoms of DVT
      +3   PE is #1 diagnosis (or equally likely)
      +1.5 HR > 100 bpm
      +1.5 Immobilisation ≥ 3 days OR surgery in past 4 weeks
      +1.5 Previous DVT or PE
      +1   Haemoptysis
      +1   Active malignancy (treatment / palliation within 6 months)

    Score > 6  → high (approx. 67% PE probability)
    Score 2-6  → intermediate (approx. 28%)
    Score < 2  → low (approx. 4%)
    """
    criteria_met:     list[str] = []
    criteria_missing: list[str] = []
    points: float = 0.0

    # DVT signs
    if _claim_has_term(all_claims, ["dvt", "deep vein thrombosis", "deep venous thrombosis",
                                     "beinvenenthrombose", "bvt", "calf swelling", "leg swelling"]):
        criteria_met.append("DVT signs/symptoms (+3)")
        points += 3
    else:
        criteria_missing.append("DVT clinical exam")

    # PE as leading diagnosis (already in graph as leading hypothesis)
    if _claim_has_term(all_claims, ["pulmonary embolism", "pe ", "lungenembolie"]):
        criteria_met.append("PE leading diagnosis (+3)")
        points += 3

    # HR > 100
    hr_qual = qualitative_for_token("heart_rate", all_claims)
    if hr_qual == "high":
        criteria_met.append("HR > 100 bpm (+1.5)")
        points += 1.5
    elif hr_qual is None:
        if _claim_has_term(all_claims, ["tachycardia", "tachykardie", "rapid heart"]):
            criteria_met.append("Tachycardia textual (+1.5)")
            points += 1.5
        else:
            criteria_missing.append("Heart rate")

    # Immobilisation / surgery
    if _claim_has_term(all_claims, ["immobilised", "immobilized", "immobilisation",
                                     "surgery", "operation", "bettlägerig", "postop"]):
        criteria_met.append("Immobilisation/surgery (+1.5)")
        points += 1.5
    else:
        criteria_missing.append("Immobilisation / recent surgery")

    # Previous DVT/PE
    if _claim_has_term(all_claims, ["previous dvt", "prior dvt", "previous pe",
                                     "prior pe", "vorherige", "vorbekannt"]):
        criteria_met.append("Prior DVT/PE (+1.5)")
        points += 1.5

    # Haemoptysis
    if _claim_has_term(all_claims, ["haemoptysis", "hemoptysis", "bluthusten"]):
        criteria_met.append("Haemoptysis (+1)")
        points += 1

    # Active malignancy
    if _claim_has_term(all_claims, ["cancer", "malignancy", "tumour", "tumor",
                                     "karzinom", "malignom", "neoplasie"]):
        criteria_met.append("Active malignancy (+1)")
        points += 1

    if points > 6:
        interpretation = "high"
    elif points >= 2:
        interpretation = "intermediate"
    else:
        interpretation = "low"

    return CompositeScore(
        name="Wells-PE",
        score=round(points, 1),
        interpretation=interpretation,
        criteria_met=criteria_met,
        criteria_missing=criteria_missing,
    )


# ── GRACE (simplified) ────────────────────────────────────────────────────────

def compute_grace_acs(all_claims: list[dict]) -> CompositeScore:
    """Simplified GRACE risk assessment for ACS (Fox et al., BMJ 2006).

    Full GRACE uses 8 continuous variables → not feasible without structured data.
    This simplified version uses categorical risk factors to produce a
    low / intermediate / high stratification.

    Factors (1 point each unless noted):
      +2  Elevated troponin
      +2  ST changes on ECG
      +1  Age ≥ 75
      +1  Killip class > 1 (pulmonary rales / hypotension / cardiogenic shock)
      +1  Cardiac arrest on presentation
      +1  Elevated creatinine (renal impairment)
      +1  Tachycardia (HR > 100)
    """
    criteria_met:     list[str] = []
    criteria_missing: list[str] = []
    points: int = 0

    # Elevated troponin
    trop_qual = qualitative_for_token("troponin", all_claims)
    if trop_qual == "high":
        criteria_met.append("Troponin elevated (+2)")
        points += 2
    elif trop_qual is None:
        if _claim_has_term(all_claims, ["troponin elevated", "elevated troponin",
                                         "troponin positive", "troponin high"]):
            criteria_met.append("Troponin elevated textual (+2)")
            points += 2
        else:
            criteria_missing.append("Troponin")

    # ST changes
    if _claim_has_term(all_claims, ["st elevation", "st depression", "st change",
                                     "stemi", "nstemi", "ecg change", "ekg veränderung"]):
        criteria_met.append("ECG ST-changes (+2)")
        points += 2
    else:
        criteria_missing.append("ECG / ST changes")

    # Age ≥ 75 (heuristic from text)
    if _claim_has_term(all_claims, ["75", "76", "77", "78", "79", "80", "81", "82",
                                     "83", "84", "85", "86", "87", "88", "89", "90",
                                     "years old", "jahre alt"]):
        criteria_met.append("Age ≥ 75 (+1)")
        points += 1

    # Killip class
    if _claim_has_term(all_claims, ["pulmonary rales", "rale", "cardiogenic shock",
                                     "hypotension", "cardiac decompensation",
                                     "herzinsuffizienz akut"]):
        criteria_met.append("Killip > 1 (+1)")
        points += 1

    # Cardiac arrest
    if _claim_has_term(all_claims, ["cardiac arrest", "reanimation", "kreislaufstillstand",
                                     "resuscitation", "cpr"]):
        criteria_met.append("Cardiac arrest (+1)")
        points += 1

    # Renal impairment
    creat_qual = qualitative_for_token("creatinine", all_claims)
    if creat_qual == "high":
        criteria_met.append("Elevated creatinine (+1)")
        points += 1
    elif creat_qual is None:
        criteria_missing.append("Creatinine")

    # Tachycardia
    hr_qual = qualitative_for_token("heart_rate", all_claims)
    if hr_qual == "high":
        criteria_met.append("Tachycardia HR > 100 (+1)")
        points += 1

    if points >= 5:
        interpretation = "high"
    elif points >= 3:
        interpretation = "intermediate"
    else:
        interpretation = "low"

    return CompositeScore(
        name="GRACE-ACS",
        score=points,
        interpretation=interpretation,
        criteria_met=criteria_met,
        criteria_missing=criteria_missing,
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────

_SCORE_RELEVANCE: dict[str, list[str]] = {
    "qSOFA":    ["sepsis", "septic shock", "urosepsis"],
    "Wells-PE": ["pulmonary embolism", "lungenembolie", "pe "],
    "GRACE-ACS": ["myocardial infarction", "stemi", "nstemi", "acs",
                  "acute coronary", "herzinfarkt"],
}


def compute_relevant_scores(all_claims: list[dict]) -> list[CompositeScore]:
    """Compute only the composite scores relevant to the active hypotheses.

    Returns a list of CompositeScore objects sorted by score severity (high first).
    """
    active_texts = " ".join(
        c.get("text", "").lower()
        for c in all_claims
        if c.get("status") == "active"
           and c.get("claim_type") in ("hypothesis", "diagnosis")
    )

    scores: list[CompositeScore] = []

    if any(term in active_texts for term in _SCORE_RELEVANCE["qSOFA"]):
        scores.append(compute_qsofa(all_claims))

    if any(term in active_texts for term in _SCORE_RELEVANCE["Wells-PE"]):
        scores.append(compute_wells_pe(all_claims))

    if any(term in active_texts for term in _SCORE_RELEVANCE["GRACE-ACS"]):
        scores.append(compute_grace_acs(all_claims))

    # Sort high-risk first
    order = {"high": 0, "intermediate": 1, "low": 2}
    return sorted(scores, key=lambda s: order.get(s.interpretation, 3))
