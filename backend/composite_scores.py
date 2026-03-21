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


# ── HEART Score ───────────────────────────────────────────────────────────────

def compute_heart(all_claims: list[dict]) -> CompositeScore:
    """HEART Score for major adverse cardiac events (Backus et al., 2010).

    H: History       — 0 (slightly suspicious) / 1 (moderately) / 2 (highly)
    E: ECG           — 0 (normal) / 1 (non-specific) / 2 (significant)
    A: Age           — 0 (<45) / 1 (45–64) / 2 (≥65)
    R: Risk factors  — 0 (none) / 1 (1–2) / 2 (≥3 or known atherosclerosis)
    T: Troponin      — 0 (≤normal) / 1 (1–3× normal) / 2 (>3× normal)

    Score ≤3 → low (1.7% MACE); 4–6 → intermediate (12–65%); ≥7 → high (>65%)
    """
    criteria_met:     list[str] = []
    criteria_missing: list[str] = []
    points: int = 0

    # H — History (chest pain characteristics)
    if _claim_has_term(all_claims, ["typical chest pain", "typical angina", "klassische angina",
                                     "crushing", "radiation arm", "radiation jaw",
                                     "typical cardiac", "exertional chest"]):
        criteria_met.append("H: Highly suspicious history (+2)")
        points += 2
    elif _claim_has_term(all_claims, ["chest pain", "chest pressure", "chest tightness",
                                       "brustschmerz", "brustdruck", "palpitations"]):
        criteria_met.append("H: Moderately suspicious history (+1)")
        points += 1
    else:
        criteria_missing.append("H: Cardiac history characterisation")

    # E — ECG
    if _claim_has_term(all_claims, ["st elevation", "stemi", "lbbb", "left bundle branch",
                                     "st depression", "t wave inversion", "significant ecg"]):
        criteria_met.append("E: Significant ECG changes (+2)")
        points += 2
    elif _claim_has_term(all_claims, ["non-specific", "non specific", "lvh", "early repolarisation",
                                       "bundle branch", "ecg change", "ekg veränderung", "nstemi"]):
        criteria_met.append("E: Non-specific ECG changes (+1)")
        points += 1
    elif _claim_has_term(all_claims, ["normal ecg", "normal ekg", "ecg normal", "sinus rhythm"]):
        criteria_met.append("E: Normal ECG (+0)")
    else:
        criteria_missing.append("E: ECG")

    # A — Age
    if _claim_has_term(all_claims, ["65", "66", "67", "68", "69", "70", "71", "72", "73",
                                     "74", "75", "76", "77", "78", "79", "80",
                                     "81", "82", "83", "84", "85", "86", "87", "88", "89",
                                     "90", "91", "92", "93", "94", "95"]):
        criteria_met.append("A: Age ≥65 (+2)")
        points += 2
    elif _claim_has_term(all_claims, ["45", "46", "47", "48", "49", "50", "51", "52", "53",
                                       "54", "55", "56", "57", "58", "59", "60", "61", "62",
                                       "63", "64", "years old", "jahre alt"]):
        criteria_met.append("A: Age 45–64 (+1)")
        points += 1
    else:
        criteria_missing.append("A: Age")

    # R — Risk factors (hypertension, hyperlipidaemia, diabetes, obesity, smoking, family history)
    risk_terms = ["hypertension", "hyperlipidaemia", "hyperlipidemia", "diabetes",
                   "obesity", "obese", "smoking", "smoker", "family history cardiac",
                   "koronare", "cad", "coronary artery disease", "atherosclerosis",
                   "hypertonus", "hypercholesterinämie", "raucher"]
    risk_count = sum(
        1 for term in risk_terms
        if _claim_has_term(all_claims, [term])
    )
    known_cad = _claim_has_term(all_claims, ["known cad", "prior mi", "prior stemi",
                                               "coronary artery disease", "percutaneous",
                                               "bypass", "stent"])
    if risk_count >= 3 or known_cad:
        criteria_met.append(f"R: ≥3 risk factors or known atherosclerosis (+2)")
        points += 2
    elif risk_count >= 1:
        criteria_met.append(f"R: {risk_count} risk factor(s) (+1)")
        points += 1
    else:
        criteria_missing.append("R: Cardiovascular risk factors")

    # T — Troponin
    trop_qual = qualitative_for_token("troponin", all_claims)
    if trop_qual == "high":
        # Check if markedly elevated (>3× normal)
        if _claim_has_term(all_claims, ["highly elevated", "markedly elevated",
                                         "3x", "3 times", "dreifach", ">3"]):
            criteria_met.append("T: Troponin >3× normal (+2)")
            points += 2
        else:
            criteria_met.append("T: Troponin 1–3× normal (+1)")
            points += 1
    elif trop_qual == "normal" or trop_qual == "low":
        criteria_met.append("T: Troponin ≤normal (+0)")
    else:
        if _claim_has_term(all_claims, ["elevated troponin", "troponin positive",
                                          "troponin erhöht"]):
            criteria_met.append("T: Troponin elevated (textual, +1)")
            points += 1
        else:
            criteria_missing.append("T: Troponin")

    if points >= 7:
        interpretation = "high"
    elif points >= 4:
        interpretation = "intermediate"
    else:
        interpretation = "low"

    return CompositeScore(
        name="HEART",
        score=points,
        interpretation=interpretation,
        criteria_met=criteria_met,
        criteria_missing=criteria_missing,
    )


# ── PERC Rule ─────────────────────────────────────────────────────────────────

def compute_perc(all_claims: list[dict]) -> CompositeScore:
    """PERC Rule for PE exclusion in low pre-test probability (Kline et al., 2004).

    All 8 criteria must be ABSENT to rule out PE without D-Dimer.
    Any criterion PRESENT → PERC positive → further workup required.

    Criteria:
      Age ≥ 50 | HR ≥ 100 | SpO2 < 95% | Unilateral leg swelling
      Haemoptysis | Recent surgery/trauma | Prior DVT/PE | Hormone use
    """
    criteria_met:     list[str] = []   # criteria PRESENT (= PERC positive factors)
    criteria_missing: list[str] = []   # criteria not documented (cannot rule out)

    # Age ≥ 50
    age_terms = [str(i) for i in range(50, 100)] + ["years old", "jahre alt"]
    if _claim_has_term(all_claims, age_terms):
        criteria_met.append("Age ≥50")
    else:
        criteria_missing.append("Age")

    # HR ≥ 100
    hr_qual = qualitative_for_token("heart_rate", all_claims)
    if hr_qual == "high" or _claim_has_term(all_claims, ["tachycardia", "tachykardie", "hr > 100", "hr>100"]):
        criteria_met.append("HR ≥100 bpm")
    elif hr_qual is None:
        criteria_missing.append("Heart rate")

    # SpO2 < 95%
    spo2_qual = qualitative_for_token("spo2", all_claims)
    if spo2_qual == "low" or _claim_has_term(all_claims, ["hypoxia", "hypoxemia", "desaturation",
                                                            "spo2 < 95", "spo2 <95", "o2 sat low"]):
        criteria_met.append("SpO2 <95%")
    elif spo2_qual is None:
        criteria_missing.append("SpO2")

    # Unilateral leg swelling (DVT signs)
    if _claim_has_term(all_claims, ["leg swelling", "calf swelling", "unilateral swelling",
                                     "dvt", "beinvenenthrombose", "unterschenkelödem"]):
        criteria_met.append("Unilateral leg swelling")

    # Haemoptysis
    if _claim_has_term(all_claims, ["haemoptysis", "hemoptysis", "bluthusten", "blood in sputum"]):
        criteria_met.append("Haemoptysis")

    # Recent surgery / trauma (within 4 weeks)
    if _claim_has_term(all_claims, ["surgery", "operation", "trauma", "injury",
                                     "operation recent", "postoperative", "postop"]):
        criteria_met.append("Recent surgery/trauma")
    else:
        criteria_missing.append("Recent surgery/trauma")

    # Prior DVT / PE
    if _claim_has_term(all_claims, ["prior dvt", "prior pe", "previous dvt", "previous pe",
                                     "history of dvt", "history of pe", "vorherige embolie"]):
        criteria_met.append("Prior DVT/PE")

    # Hormone use (OCP, HRT)
    if _claim_has_term(all_claims, ["oral contraceptive", "ocp", "contraceptive pill",
                                     "hormone replacement", "hrt", "östrogen", "estrogen"]):
        criteria_met.append("Hormone use")

    # PERC NEGATIVE = no criteria present (rule out PE without D-Dimer)
    perc_negative = len(criteria_met) == 0
    score         = len(criteria_met)

    return CompositeScore(
        name="PERC",
        score=score,
        interpretation="low" if perc_negative else "high",
        criteria_met=criteria_met,   # present risk factors
        criteria_missing=criteria_missing,
    )


# ── CURB-65 ───────────────────────────────────────────────────────────────────

def compute_curb65(all_claims: list[dict]) -> CompositeScore:
    """CURB-65 pneumonia severity score (Lim et al., Thorax 2003).

    C: Confusion      — new confusion / disorientation
    U: Urea > 7 mmol/L (BUN > 19 mg/dL)
    R: Respiratory rate ≥ 30/min
    B: Blood pressure — SBP < 90 or DBP ≤ 60 mmHg
    65: Age ≥ 65

    Score 0–1: low (outpatient); 2: intermediate (brief admission);
    Score 3–5: high (ICU consideration)
    """
    criteria_met:     list[str] = []
    criteria_missing: list[str] = []
    points: int = 0

    # C — Confusion
    gcs_qual = qualitative_for_token("gcs", all_claims)
    if gcs_qual == "low" or _claim_has_term(all_claims, ["confusion", "confused", "disoriented",
                                                           "altered mental", "verwirrt",
                                                           "desorientiert", "agitation"]):
        criteria_met.append("C: Confusion (+1)")
        points += 1
    else:
        criteria_missing.append("C: Confusion / mental status")

    # U — Urea > 7 mmol/L
    bun_qual = qualitative_for_token("bun", all_claims)
    urea_qual = qualitative_for_token("urea", all_claims)
    if bun_qual == "high" or urea_qual == "high":
        criteria_met.append("U: Urea/BUN elevated (+1)")
        points += 1
    elif bun_qual is None and urea_qual is None:
        if _claim_has_term(all_claims, ["elevated bun", "elevated urea", "harnstoff erhöht"]):
            criteria_met.append("U: Urea elevated (textual, +1)")
            points += 1
        else:
            criteria_missing.append("U: Urea/BUN")

    # R — RR ≥ 30/min
    rr_qual = qualitative_for_token("respiratory_rate", all_claims)
    if rr_qual == "high" or _claim_has_term(all_claims, ["tachypnea", "tachypnoea",
                                                           "rr 30", "atemfrequenz erhöht",
                                                           "respiratory distress"]):
        criteria_met.append("R: RR ≥30/min (+1)")
        points += 1
    else:
        criteria_missing.append("R: Respiratory rate")

    # B — Low BP
    sbp_qual = qualitative_for_token("systolic_bp", all_claims)
    dbp_qual = qualitative_for_token("diastolic_bp", all_claims)
    if (sbp_qual == "low" or dbp_qual == "low"
            or _claim_has_term(all_claims, ["hypotension", "hypotonie", "low bp",
                                             "low blood pressure", "blutdruckabfall"])):
        criteria_met.append("B: Low BP (+1)")
        points += 1
    else:
        criteria_missing.append("B: Blood pressure")

    # 65 — Age ≥ 65
    age_terms_65 = [str(i) for i in range(65, 100)] + ["years old", "jahre alt"]
    if _claim_has_term(all_claims, age_terms_65):
        criteria_met.append("65: Age ≥65 (+1)")
        points += 1
    else:
        criteria_missing.append("65: Age")

    if points >= 3:
        interpretation = "high"
    elif points == 2:
        interpretation = "intermediate"
    else:
        interpretation = "low"

    return CompositeScore(
        name="CURB-65",
        score=points,
        interpretation=interpretation,
        criteria_met=criteria_met,
        criteria_missing=criteria_missing,
    )


# ── Dispatcher ────────────────────────────────────────────────────────────────

_SCORE_RELEVANCE: dict[str, list[str]] = {
    "qSOFA":     ["sepsis", "septic shock", "urosepsis"],
    "Wells-PE":  ["pulmonary embolism", "lungenembolie", "pe "],
    "GRACE-ACS": ["myocardial infarction", "stemi", "nstemi", "acs",
                  "acute coronary", "herzinfarkt"],
    "HEART":     ["chest pain", "brustschmerz", "myocardial infarction",
                  "acs", "coronary", "cardiac"],
    "PERC":      ["pulmonary embolism", "lungenembolie", "pe ", "pe-"],
    "CURB-65":   ["pneumonia", "pneumonie", "cap"],
}

# Human-readable recommendation per score level
_RECOMMENDATIONS: dict[str, dict[str, str]] = {
    "HEART": {
        "low":          "Consider discharge with outpatient follow-up (1.7% MACE risk)",
        "intermediate": "Observation unit, serial troponin, stress test (12–65% MACE risk)",
        "high":         "Early invasive strategy recommended (>65% MACE risk)",
    },
    "PERC": {
        "low":          "PERC NEGATIVE — PE can be excluded without D-Dimer in low pre-test probability",
        "high":         "PERC POSITIVE — D-Dimer or imaging required",
    },
    "CURB-65": {
        "low":          "Low severity — outpatient treatment appropriate (30-day mortality ~1%)",
        "intermediate": "Moderate severity — brief hospitalisation recommended (~9% mortality)",
        "high":         "Severe — hospitalisation/ICU consideration required (>22% mortality)",
    },
    "qSOFA": {
        "low":          "Low sepsis risk — monitor clinically",
        "intermediate": "Intermediate risk — assess organ function",
        "high":         "High sepsis risk — immediate assessment, blood cultures, IV antibiotics",
    },
    "Wells-PE": {
        "low":          "Low probability — D-Dimer to rule out (PERC first if applicable)",
        "intermediate": "Intermediate probability — D-Dimer or CT-PA depending on clinical context",
        "high":         "High probability — CT-PA or empiric anticoagulation",
    },
    "GRACE-ACS": {
        "low":          "Low risk ACS — conservative management, non-urgent angiography",
        "intermediate": "Intermediate risk — semi-urgent angiography within 24–72h",
        "high":         "High risk ACS — urgent angiography within 24h",
    },
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


def compute_all_scores(all_claims: list[dict]) -> list[dict]:
    """
    Compute all six validated risk scores and return structured dicts.

    Each score runs regardless of active hypotheses (unlike compute_relevant_scores).
    The `relevant` flag indicates whether the score applies to the current
    differential based on active hypothesis texts.

    Returns a list sorted by: relevance first, then severity (high → low).
    """
    active_texts = " ".join(
        c.get("text", "").lower()
        for c in all_claims
        if c.get("status") in ("active", "observed", "confirmed")
           and c.get("claim_type") in ("hypothesis", "diagnosis")
    )

    all_scorers = [
        ("qSOFA",    compute_qsofa),
        ("Wells-PE", compute_wells_pe),
        ("GRACE-ACS",compute_grace_acs),
        ("HEART",    compute_heart),
        ("PERC",     compute_perc),
        ("CURB-65",  compute_curb65),
    ]

    results = []
    for score_name, scorer in all_scorers:
        cs        = scorer(all_claims)
        relevant  = any(term in active_texts for term in _SCORE_RELEVANCE.get(score_name, []))
        rec_map   = _RECOMMENDATIONS.get(score_name, {})
        results.append({
            "name":              cs.name,
            "score":             cs.score,
            "interpretation":    cs.interpretation,
            "criteria_met":      cs.criteria_met,
            "criteria_missing":  cs.criteria_missing,
            "relevant":          relevant,
            "recommendation":    rec_map.get(cs.interpretation, ""),
        })

    # Relevant + high-risk first; then irrelevant; within group by severity
    sev_order = {"high": 0, "intermediate": 1, "low": 2}
    results.sort(key=lambda r: (not r["relevant"], sev_order.get(r["interpretation"], 3)))
    return results
