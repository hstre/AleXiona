"""MED Engine — Minimal Evidence to Decision.

Answers: "Which single test would change the clinical decision most?"

Algorithm
---------
1. Baseline: rank_hypotheses(claims) → leading hypothesis H0 with score S0
2. For each candidate test T not yet evidenced:
   a. For each possible outcome O of T:
      - Append a synthetic claim dict for O to a copy of claims
      - Re-run rank_hypotheses() → leading Hk with score Sk
      - score_delta = Sk − S0 (signed: positive if outcome supports H0 more)
      - hypothesis_flipped = (Hk != H0)
   b. impact_score(T) = mean(|delta_O|) + 0.3 × flip_fraction
3. Rank tests by impact_score descending
4. Return top _MAX_RESULTS tests

The simulation is entirely rule-based (no LLM calls) — O(n_tests × n_outcomes × n_hypotheses).
Typical latency: <50 ms for 15 claims.

Test catalogue
--------------
Each entry defines possible outcome claim texts crafted to produce meaningful
key-term overlap with existing hypothesis texts (the currency of score_hypothesis()).
- "Positive" outcomes carry hypothesis-confirming terms.
- "Negative" outcomes contain "ruled out" / "normal" / "negative" to trigger
  the negation logic in _key_terms_with_negation() → conflict.
"""

from __future__ import annotations

import uuid

from models import MEDOutcome, MEDResult, MEDTestResult

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_RESULTS     = 6    # max tests returned in the MED set
_FLIP_BONUS      = 0.30 # added per outcome that causes a hypothesis flip

# ── Test catalogue ────────────────────────────────────────────────────────────
# Each test: category, rationale, differentiates, outcomes[]
# Each outcome: label, text, claim_type, source_type, evidence_tier, evidence_support_score
# Texts are engineered so that key-term overlap works with score_hypothesis():
#   - confirming outcomes → direct key-term overlap with hypothesis text
#   - excluding outcomes  → "ruled out" / "negative" / "normal" near the key term
#     → triggers _key_terms_with_negation() → conflict penalty

_MED_TEST_CATALOG: dict[str, dict] = {
    "D-Dimer": {
        "category":            "lab",
        "rationale":           "High sensitivity for PE/thrombosis; normal value effectively rules out PE",
        "differentiates":      ["pulmonary embolism", "pneumonia", "sepsis"],
        "already_terms":       ["d-dimer", "d dimer", "ddimer"],
        "outcomes": [
            {
                "label": "elevated (>0.5 µg/mL)",
                "text":  "D-Dimer markedly elevated — thrombosis active, pulmonary embolism highly likely",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.93,
            },
            {
                "label": "normal (<0.5 µg/mL)",
                "text":  "D-Dimer normal, pulmonary embolism ruled out — thrombosis excluded",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.95,
            },
        ],
    },
    "Troponin": {
        "category":            "lab",
        "rationale":           "Myocardial injury marker; serial values confirm or exclude ACS/NSTEMI",
        "differentiates":      ["myocardial infarction", "pulmonary embolism", "sepsis"],
        "already_terms":       ["troponin", "troponin i", "troponin t", "hs-troponin"],
        "outcomes": [
            {
                "label": "elevated",
                "text":  "Troponin elevated — myocardial injury confirmed, cardiac damage, ACS likely",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.90,
            },
            {
                "label": "normal",
                "text":  "Troponin normal — no myocardial injury, cardiac damage ruled out, ACS not confirmed",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.92,
            },
        ],
    },
    "Chest Imaging (CT/X-Ray)": {
        "category":            "imaging",
        "rationale":           "Differentiates pulmonary consolidation (pneumonia) from vascular cause (PE)",
        "differentiates":      ["pneumonia", "pulmonary embolism", "heart failure", "ards"],
        "already_terms":       ["chest x-ray", "ct chest", "chest ct", "chest imaging", "consolidation", "infiltrate"],
        "outcomes": [
            {
                "label": "consolidation / infiltrate",
                "text":  "Chest CT: pulmonary infiltrate, consolidation right lower lobe — pneumonia confirmed",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.97,
            },
            {
                "label": "normal parenchyma",
                "text":  "Chest CT: normal parenchyma, no consolidation, pneumonia ruled out — no infiltrate",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.95,
            },
            {
                "label": "pleural effusion",
                "text":  "Chest CT: bilateral pleural effusion, cardiomegaly — heart failure likely",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.88,
            },
        ],
    },
    "Blood Cultures": {
        "category":            "lab",
        "rationale":           "Confirms bacteremia/sepsis; guides antibiotic therapy",
        "differentiates":      ["sepsis", "pneumonia", "endocarditis"],
        "already_terms":       ["blood culture", "bacteremia", "blood cultures"],
        "outcomes": [
            {
                "label": "positive (gram-negative)",
                "text":  "Blood culture positive — bacteremia confirmed, gram-negative sepsis likely",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.97,
            },
            {
                "label": "negative",
                "text":  "Blood culture negative after 48h — bacteremia not confirmed, systemic infection less likely",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.70,
            },
        ],
    },
    "Lactate": {
        "category":            "lab",
        "rationale":           "Elevated lactate confirms tissue hypoperfusion; key sepsis criterion (Sepsis-3)",
        "differentiates":      ["sepsis", "heart failure", "pulmonary embolism"],
        "already_terms":       ["lactate", "laktat"],
        "outcomes": [
            {
                "label": "elevated (>2 mmol/L)",
                "text":  "Lactate elevated — tissue hypoperfusion, sepsis criteria met, hypotension confirmed",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.91,
            },
            {
                "label": "normal (<2 mmol/L)",
                "text":  "Lactate normal — no significant hypoperfusion, sepsis hypotension not confirmed",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.88,
            },
        ],
    },
    "BNP / NT-proBNP": {
        "category":            "lab",
        "rationale":           "Cardiac stress marker; elevated confirms heart failure, also rises in massive PE",
        "differentiates":      ["heart failure", "pulmonary embolism", "pneumonia"],
        "already_terms":       ["bnp", "nt-probnp", "proBNP"],
        "outcomes": [
            {
                "label": "elevated",
                "text":  "BNP markedly elevated — cardiac stress, heart failure likely, ventricular overload",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.88,
            },
            {
                "label": "normal",
                "text":  "BNP normal — heart failure ruled out, no significant cardiac overload",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.87,
            },
        ],
    },
    "ECG": {
        "category":            "ecg",
        "rationale":           "Acute coronary/right heart changes; S1Q3T3 supports PE, ST changes support ACS",
        "differentiates":      ["myocardial infarction", "pulmonary embolism", "sepsis"],
        "already_terms":       ["ecg", "ekg", "electrocardiogram", "s1q3t3", "st elevation"],
        "outcomes": [
            {
                "label": "ST elevation / depression",
                "text":  "ECG: ST elevation / ST depression — acute coronary ischemia, myocardial infarction likely",
                "claim_type": "finding", "source_type": "clinician",
                "evidence_tier": "clinician_observed", "evidence_support_score": 0.90,
            },
            {
                "label": "S1Q3T3 pattern",
                "text":  "ECG: S1Q3T3 pattern — right heart strain, pulmonary embolism likely",
                "claim_type": "finding", "source_type": "clinician",
                "evidence_tier": "clinician_observed", "evidence_support_score": 0.82,
            },
            {
                "label": "normal sinus rhythm",
                "text":  "ECG: normal sinus rhythm, no ischemic changes, no right heart strain pattern",
                "claim_type": "finding", "source_type": "clinician",
                "evidence_tier": "clinician_observed", "evidence_support_score": 0.78,
            },
        ],
    },
    "CT Pulmonary Angiography (CT-PA)": {
        "category":            "imaging",
        "rationale":           "Gold standard for PE; direct visualization of filling defects",
        "differentiates":      ["pulmonary embolism", "pneumonia"],
        "already_terms":       ["ct-pa", "ct pulmonary", "ctpa", "pulmonary angiography", "filling defect"],
        "outcomes": [
            {
                "label": "filling defect present",
                "text":  "CT-PA: bilateral filling defect, pulmonary embolism confirmed — saddle embolus",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.99,
            },
            {
                "label": "no filling defect",
                "text":  "CT-PA: no filling defect, pulmonary embolism ruled out — normal pulmonary vasculature",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.99,
            },
        ],
    },
    "Echocardiography": {
        "category":            "imaging",
        "rationale":           "Right ventricular assessment; key for PE severity and heart failure",
        "differentiates":      ["heart failure", "pulmonary embolism", "myocardial infarction"],
        "already_terms":       ["echo", "echocardiograph", "right ventricular", "ejection fraction"],
        "outcomes": [
            {
                "label": "reduced EF / RV dilation",
                "text":  "Echo: reduced ejection fraction, right ventricular dilation — heart failure, cardiac dysfunction",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.90,
            },
            {
                "label": "normal",
                "text":  "Echo: normal ejection fraction, no right ventricular dilation, heart failure ruled out",
                "claim_type": "imaging", "source_type": "imaging_model",
                "evidence_tier": "instrument_measured", "evidence_support_score": 0.88,
            },
        ],
    },
    "Procalcitonin (PCT)": {
        "category":            "lab",
        "rationale":           "Bacterial infection marker; high specificity for bacterial vs viral cause",
        "differentiates":      ["sepsis", "pneumonia", "viral infection"],
        "already_terms":       ["procalcitonin", "pct"],
        "outcomes": [
            {
                "label": "elevated (>0.5 ng/mL)",
                "text":  "Procalcitonin elevated — bacterial infection confirmed, sepsis, pneumonia bacterial",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.88,
            },
            {
                "label": "normal (<0.1 ng/mL)",
                "text":  "Procalcitonin normal — bacterial infection less likely, viral aetiology possible",
                "claim_type": "lab", "source_type": "lab_system",
                "evidence_tier": "lab_confirmed", "evidence_support_score": 0.75,
            },
        ],
    },
}

# Guideline missing-term → catalog test name (for pre-filtering relevant tests)
_TERM_TO_TEST: dict[str, str] = {
    "d-dimer":           "D-Dimer",
    "troponin":          "Troponin",
    "infiltrate":        "Chest Imaging (CT/X-Ray)",
    "consolidation":     "Chest Imaging (CT/X-Ray)",
    "imaging":           "Chest Imaging (CT/X-Ray)",
    "lactate":           "Lactate",
    "bnp":               "BNP / NT-proBNP",
    "ecg changes":       "ECG",
    "st elevation":      "ECG",
    "right heart strain":"CT Pulmonary Angiography (CT-PA)",
    "wells score":       "D-Dimer",
    "normal d-dimer":    "D-Dimer",
    "normal troponin":   "Troponin",
    "normal bnp":        "BNP / NT-proBNP",
    "normal imaging":    "Chest Imaging (CT/X-Ray)",
    "blood culture":     "Blood Cultures",
    "bacteremia":        "Blood Cultures",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_synthetic_claim(outcome: dict) -> dict:
    return {
        "id":                     f"med_sim_{uuid.uuid4().hex[:8]}",
        "text":                   outcome["text"],
        "claim_type":             outcome["claim_type"],
        "source_type":            outcome["source_type"],
        "evidence_support_score": outcome["evidence_support_score"],
        "evidence_tier":          outcome["evidence_tier"],
        "status":                 "observed",
        "trend":                  "unknown",
        "derived_from":           [],
        "related_to":             [],
        "time_offset":            None,
        "event_time":             None,
    }


def _is_already_evidenced(test_name: str, claims: list[dict]) -> bool:
    """Return True if the test result is already present in the claim graph."""
    terms = _MED_TEST_CATALOG[test_name].get("already_terms", [])
    all_text = " ".join(c.get("text", "").lower() for c in claims)
    return any(t in all_text for t in terms)


def _select_candidate_tests(claims: list[dict]) -> list[str]:
    """Return ordered list of test names to simulate.

    Priority order:
    1. Tests explicitly listed in guideline missing_priority for active hypotheses
    2. All remaining catalog entries not yet evidenced
    """
    from reasoning_engine import evaluate_guideline, rank_hypotheses

    ranked = rank_hypotheses(claims)
    guideline_tests: list[str] = []
    seen: set[str] = set()

    for hs in ranked[:3]:
        result = evaluate_guideline(hs.text, claims)
        for term in result.get("missing_priority", []):
            test = _TERM_TO_TEST.get(term)
            if test and test not in seen:
                guideline_tests.append(test)
                seen.add(test)

    # Add remaining catalog tests
    for name in _MED_TEST_CATALOG:
        if name not in seen:
            guideline_tests.append(name)

    return guideline_tests


# ── Main function ─────────────────────────────────────────────────────────────

def compute_med(claims: list[dict], session_id: str = "") -> MEDResult:
    """Compute the Minimal Evidence to Decision set for the current claim graph.

    Returns a MEDResult with tests ranked by information gain (impact_score).
    Fully rule-based — no LLM calls.
    """
    from reasoning_engine import rank_hypotheses

    if not claims:
        return MEDResult(
            session_id=session_id,
            current_leading="",
            current_score=0.0,
            minimal_decision_set=[],
        )

    # Baseline
    baseline = rank_hypotheses(claims)
    if not baseline:
        return MEDResult(
            session_id=session_id,
            current_leading="",
            current_score=0.0,
            minimal_decision_set=[],
        )

    current_leading = baseline[0].text
    current_score   = baseline[0].rule_based_score
    current_id      = baseline[0].id

    candidate_tests = _select_candidate_tests(claims)
    results: list[MEDTestResult] = []

    for test_name in candidate_tests:
        spec     = _MED_TEST_CATALOG[test_name]
        evidenced = _is_already_evidenced(test_name, claims)

        outcomes_sim: list[MEDOutcome] = []
        total_abs_delta = 0.0
        flip_count      = 0

        for outcome_def in spec["outcomes"]:
            synthetic = _make_synthetic_claim(outcome_def)
            augmented = claims + [synthetic]

            ranked_after = rank_hypotheses(augmented)
            if not ranked_after:
                continue

            leading_after       = ranked_after[0].text
            leading_score_after = ranked_after[0].rule_based_score
            leading_id_after    = ranked_after[0].id

            # Signed delta: positive = current leading hypothesis got stronger
            delta = leading_score_after - current_score
            flipped = (leading_id_after != current_id) if current_id else False

            total_abs_delta += abs(delta)
            if flipped:
                flip_count += 1

            outcomes_sim.append(MEDOutcome(
                label=outcome_def["label"],
                synthetic_text=outcome_def["text"],
                score_delta=round(delta, 3),
                leading_after=leading_after,
                leading_score_after=round(leading_score_after, 3),
                hypothesis_flipped=flipped,
            ))

        if not outcomes_sim:
            continue

        n_outcomes   = len(outcomes_sim)
        mean_delta   = total_abs_delta / n_outcomes
        flip_frac    = flip_count / n_outcomes
        impact_score = min(1.0, mean_delta + _FLIP_BONUS * flip_frac)

        # Don't include tests with no meaningful impact (unless guideline-driven)
        if impact_score < 0.05 and not evidenced:
            continue

        results.append(MEDTestResult(
            test=test_name,
            category=spec["category"],
            impact_score=round(impact_score, 3),
            rationale=spec["rationale"],
            differentiates_between=spec["differentiates"],
            outcomes=outcomes_sim,
            already_evidenced=evidenced,
        ))

    results.sort(key=lambda r: (r.already_evidenced, -r.impact_score))

    return MEDResult(
        session_id=session_id,
        current_leading=current_leading,
        current_score=round(current_score, 3),
        minimal_decision_set=results[:_MAX_RESULTS],
    )
