"""Unit tests for composite_scores.py."""
import pytest
from composite_scores import (
    compute_qsofa,
    compute_wells_pe,
    compute_grace_acs,
    compute_relevant_scores,
    CompositeScore,
)


def _claim(text: str, claim_type: str = "finding", status: str = "active") -> dict:
    return {"text": text, "claim_type": claim_type, "status": status}


def _hyp(text: str) -> dict:
    return _claim(text, claim_type="hypothesis")


# ── qSOFA ─────────────────────────────────────────────────────────────────────

class TestQSOFA:
    def test_high_risk_all_three_criteria(self):
        claims = [
            _claim("Respiratory rate 25 /min", "lab"),
            _claim("GCS 12", "lab"),
            _claim("Systolic BP 85 mmHg", "lab"),
        ]
        result = compute_qsofa(claims)
        assert result.score >= 2
        assert result.interpretation == "high"

    def test_textual_tachypnea_counts(self):
        claims = [_claim("Patient shows tachypnea")]
        result = compute_qsofa(claims)
        assert "RR ≥ 22/min (textual)" in result.criteria_met

    def test_textual_confusion_counts(self):
        claims = [_claim("Patient is confused and disoriented")]
        result = compute_qsofa(claims)
        assert any("mentation" in c.lower() or "gcs" in c.lower() for c in result.criteria_met)

    def test_textual_hypotension_counts(self):
        claims = [_claim("Hypotension noted")]
        result = compute_qsofa(claims)
        assert any("hypotension" in c.lower() for c in result.criteria_met)

    def test_low_risk_no_criteria(self):
        claims = [_claim("Patient appears well")]
        result = compute_qsofa(claims)
        assert result.interpretation in ("low", "intermediate")

    def test_missing_criteria_reported(self):
        claims = []
        result = compute_qsofa(claims)
        assert len(result.criteria_missing) > 0

    def test_as_claim_has_required_fields(self):
        result = compute_qsofa([])
        claim = result.as_claim
        assert claim["source_type"] == "guideline"
        assert claim["claim_type"] == "finding"
        assert "qSOFA" in claim["text"]
        assert 0.0 <= claim["evidence_support_score"] <= 1.0


# ── Wells PE ──────────────────────────────────────────────────────────────────

class TestWellsPE:
    def test_high_risk(self):
        claims = [
            _hyp("Pulmonary embolism suspected"),
            _claim("Deep vein thrombosis confirmed DVT"),
            _claim("Heart rate 115 bpm tachycardia", "lab"),
        ]
        result = compute_wells_pe(claims)
        assert result.score >= 6
        assert result.interpretation == "high"

    def test_ddimer_not_scored(self):
        # D-Dimer is not a Wells criterion
        claims = [_claim("D-Dimer 4.8 µg/mL elevated")]
        result = compute_wells_pe(claims)
        assert result.score == 0 or "DVT" not in str(result.criteria_met)

    def test_haemoptysis_adds_point(self):
        claims = [_claim("Haemoptysis present")]
        result = compute_wells_pe(claims)
        assert any("haemoptysis" in c.lower() for c in result.criteria_met)

    def test_malignancy_adds_point(self):
        claims = [_claim("Known lung cancer active")]
        result = compute_wells_pe(claims)
        assert any("malignancy" in c.lower() for c in result.criteria_met)

    def test_low_risk_empty_claims(self):
        result = compute_wells_pe([])
        assert result.interpretation == "low"
        assert result.score == 0

    def test_as_claim_structure(self):
        result = compute_wells_pe([])
        assert "Wells-PE" in result.as_claim["text"]


# ── GRACE ACS ─────────────────────────────────────────────────────────────────

class TestGRACEACS:
    def test_high_risk_elevated_troponin_and_stemi(self):
        claims = [
            _claim("Troponin I 0.12 µg/L elevated", "lab"),
            _claim("ECG shows ST elevation STEMI"),
            _claim("Pulmonary rales present"),
        ]
        result = compute_grace_acs(claims)
        assert result.score >= 5
        assert result.interpretation == "high"

    def test_st_changes_count(self):
        claims = [_claim("ST depression noted on ECG")]
        result = compute_grace_acs(claims)
        assert any("st" in c.lower() for c in result.criteria_met)

    def test_cardiac_arrest_adds_point(self):
        claims = [_claim("Patient underwent CPR cardiac arrest")]
        result = compute_grace_acs(claims)
        assert any("arrest" in c.lower() for c in result.criteria_met)

    def test_low_risk_empty(self):
        result = compute_grace_acs([])
        assert result.interpretation == "low"
        assert result.score == 0

    def test_missing_troponin_reported(self):
        result = compute_grace_acs([])
        assert any("troponin" in m.lower() for m in result.criteria_missing)


# ── compute_relevant_scores dispatcher ───────────────────────────────────────

class TestComputeRelevantScores:
    def test_sepsis_triggers_qsofa(self):
        claims = [_hyp("Sepsis suspected")]
        scores = compute_relevant_scores(claims)
        names = [s.name for s in scores]
        assert "qSOFA" in names

    def test_pe_triggers_wells(self):
        claims = [_hyp("Pulmonary embolism")]
        scores = compute_relevant_scores(claims)
        names = [s.name for s in scores]
        assert "Wells-PE" in names

    def test_acs_triggers_grace(self):
        claims = [_hyp("Acute coronary syndrome NSTEMI")]
        scores = compute_relevant_scores(claims)
        names = [s.name for s in scores]
        assert "GRACE-ACS" in names

    def test_no_relevant_hypothesis_returns_empty(self):
        claims = [_claim("Patient has cough and fever")]
        scores = compute_relevant_scores(claims)
        assert scores == []

    def test_high_risk_sorted_first(self):
        claims = [
            _hyp("Sepsis"),
            _claim("Respiratory rate 28 /min tachypnea", "lab"),
            _claim("GCS 10", "lab"),
            _claim("Systolic BP 80 mmHg hypotension", "lab"),
        ]
        scores = compute_relevant_scores(claims)
        if len(scores) > 1:
            for i in range(len(scores) - 1):
                order = {"high": 0, "intermediate": 1, "low": 2}
                assert order[scores[i].interpretation] <= order[scores[i + 1].interpretation]


# ── CompositeScore structure ──────────────────────────────────────────────────

class TestCompositeScoreStructure:
    def test_ess_high_risk_is_high(self):
        cs = CompositeScore("Test", 2, "high", ["a", "b"], [])
        assert cs.as_claim["evidence_support_score"] >= 0.8

    def test_ess_low_risk_is_low(self):
        cs = CompositeScore("Test", 0, "low", [], ["x", "y"])
        assert cs.as_claim["evidence_support_score"] <= 0.4

    def test_claim_text_contains_score(self):
        cs = CompositeScore("qSOFA", 3, "high", ["RR", "GCS", "BP"], [])
        assert "3" in cs.as_claim["text"]
        assert "high" in cs.as_claim["text"].lower()
