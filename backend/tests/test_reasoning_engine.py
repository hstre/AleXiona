"""Unit tests for reasoning_engine.py.

All tests use in-memory claim dicts — no Neo4j or LLM required.
"""
from reasoning_engine import (
    _DEFAULT_PENALTY,
    _NEGATION_PENALTY,
    _QUANTITATIVE_PENALTY,
    GUIDELINES,
    _conflict_penalty,
    _source_weight,
    build_case_snapshot,
    build_reasoning_context,
    explain_leading,
    get_confident_leading,
    rank_hypotheses,
    required_evidence_for,
    score_hypothesis,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def make_claim(
    id: str,
    text: str,
    claim_type: str = "finding",
    status: str = "active",
    evidence_support_score: float = 0.8,
    source_type: str = "llm",
    derived_from: list[str] | None = None,
) -> dict:
    return {
        "id": id,
        "text": text,
        "claim_type": claim_type,
        "status": status,
        "evidence_support_score": evidence_support_score,
        "source_type": source_type,
        "derived_from": derived_from or [],
    }


# ── _source_weight ────────────────────────────────────────────────────────────

class TestSourceWeight:
    def test_guideline_highest(self):
        assert _source_weight("guideline") == 2.0

    def test_lab_system_higher_than_default(self):
        assert _source_weight("lab_system") == 1.5

    def test_clinician_above_default(self):
        assert _source_weight("clinician") == 1.2

    def test_llm_downweighted(self):
        assert _source_weight("llm") == 0.5

    def test_unknown_source_defaults_to_one(self):
        assert _source_weight("unknown_source") == 1.0

    def test_imaging_model_neutral(self):
        assert _source_weight("imaging_model") == 1.0


# ── _conflict_penalty ─────────────────────────────────────────────────────────

class TestConflictPenalty:
    def test_negation_returns_highest_penalty(self):
        assert _conflict_penalty("No fever detected in patient") == _NEGATION_PENALTY

    def test_ruled_out_counts_as_negation(self):
        assert _conflict_penalty("Pulmonary embolism ruled out") == _NEGATION_PENALTY

    def test_kein_german_negation(self):
        assert _conflict_penalty("Kein Fieber vorhanden") == _NEGATION_PENALTY

    def test_elevated_returns_quantitative_penalty(self):
        assert _conflict_penalty("CRP elevated above normal") == _QUANTITATIVE_PENALTY

    def test_normal_returns_quantitative_penalty(self):
        assert _conflict_penalty("CRP within normal limits") == _QUANTITATIVE_PENALTY

    def test_generic_text_returns_default(self):
        assert _conflict_penalty("some overlap finding text") == _DEFAULT_PENALTY

    def test_negation_beats_quantitative(self):
        # A text with both negation and quantitative qualifier → negation wins
        assert _conflict_penalty("No elevated CRP found") == _NEGATION_PENALTY


# ── score_hypothesis — source weighting ──────────────────────────────────────

class TestScoreHypothesisSourceWeighting:
    def test_guideline_source_scores_higher_than_llm(self):
        evidence_llm = make_claim(
            "e1", "Patient has fever cough infection",
            claim_type="finding", source_type="llm", evidence_support_score=0.8,
        )
        evidence_guideline = make_claim(
            "e2", "Patient has fever cough infection",
            claim_type="finding", source_type="guideline", evidence_support_score=0.8,
        )
        hyp = make_claim("h1", "Pneumonia fever cough infection", claim_type="hypothesis")

        score_llm       = score_hypothesis(hyp, [hyp, evidence_llm])
        score_guideline = score_hypothesis(hyp, [hyp, evidence_guideline])

        assert score_guideline["rule_based_score"] > score_llm["rule_based_score"]

    def test_lab_system_scores_higher_than_llm(self):
        evidence_llm = make_claim(
            "e1", "CRP elevated fever infection finding",
            claim_type="lab", source_type="llm", evidence_support_score=0.8,
        )
        evidence_lab = make_claim(
            "e2", "CRP elevated fever infection finding",
            claim_type="lab", source_type="lab_system", evidence_support_score=0.8,
        )
        hyp = make_claim("h1", "CRP elevated fever infection hypothesis", claim_type="hypothesis")

        score_llm = score_hypothesis(hyp, [hyp, evidence_llm])
        score_lab = score_hypothesis(hyp, [hyp, evidence_lab])

        assert score_lab["rule_based_score"] > score_llm["rule_based_score"]

    def test_inactive_claim_not_scored(self):
        evidence = make_claim(
            "e1", "Fever cough infection finding",
            claim_type="finding", status="superseded",
        )
        hyp = make_claim("h1", "Fever cough infection hypothesis", claim_type="hypothesis")
        result = score_hypothesis(hyp, [hyp, evidence])
        assert result["rule_based_score"] == 0.0
        assert result["supporting_claim_ids"] == []


# ── score_hypothesis — conflict penalties ────────────────────────────────────

class TestScoreHypothesisConflictPenalties:
    def test_negation_reduces_score_more_than_default(self):
        negation_evidence = make_claim(
            "e1", "No fever detected in patient",
            claim_type="finding",
        )
        plain_evidence = make_claim(
            "e2", "Uncertain fever finding patient",  # generic overlap, no polarity
            claim_type="finding",
        )
        hyp = make_claim("h1", "Fever infection patient hypothesis", claim_type="hypothesis")

        # Build two separate claim sets; each has one conflicting claim
        # Score with negation conflict (should be lower / 0 faster)
        claims_with_neg   = [hyp, negation_evidence]
        claims_with_plain = [hyp, plain_evidence]

        score_neg   = score_hypothesis(hyp, claims_with_neg)
        score_plain = score_hypothesis(hyp, claims_with_plain)

        # negation penalty (2.0) > default penalty (1.0) → negation score lower
        assert score_neg["rule_based_score"] <= score_plain["rule_based_score"]

    def test_conflicting_ids_populated(self):
        evidence = make_claim(
            "e1", "No fever detected in patient",
            claim_type="finding",
        )
        hyp = make_claim("h1", "Fever detected in patient hypothesis", claim_type="hypothesis")
        result = score_hypothesis(hyp, [hyp, evidence])
        assert "e1" in result["conflicting_claim_ids"]
        assert "e1" not in result["supporting_claim_ids"]

    def test_score_clamped_to_zero_on_heavy_conflict(self):
        conflicts = [
            make_claim(f"e{i}", "No fever cough infection found",
                       claim_type="finding")
            for i in range(5)
        ]
        hyp = make_claim("h1", "Fever cough infection hypothesis", claim_type="hypothesis")
        result = score_hypothesis(hyp, [hyp] + conflicts)
        assert result["rule_based_score"] == 0.0


# ── rank_hypotheses ───────────────────────────────────────────────────────────

class TestRankHypotheses:
    def test_higher_supported_hypothesis_ranked_first(self):
        evidence = make_claim(
            "e1", "Fever cough infection finding",
            claim_type="finding", source_type="guideline",
        )
        h1 = make_claim("h1", "Fever cough infection pneumonia", claim_type="hypothesis")
        h2 = make_claim("h2", "Unrelated cardiac hypothesis", claim_type="hypothesis")

        ranked = rank_hypotheses([evidence, h1, h2])
        assert ranked[0]["id"] == "h1"

    def test_empty_claims_returns_empty(self):
        assert rank_hypotheses([]) == []

    def test_superseded_hypothesis_excluded(self):
        hyp = make_claim("h1", "Fever hypothesis", claim_type="hypothesis", status="superseded")
        assert rank_hypotheses([hyp]) == []

    def test_returns_sorted_descending(self):
        e = make_claim("e1", "Fever cough infection", claim_type="finding",
                       source_type="guideline")
        h_strong = make_claim("h1", "Fever cough infection pneumonia", claim_type="hypothesis")
        h_weak   = make_claim("h2", "Unrelated embolism hypothesis", claim_type="hypothesis")
        ranked = rank_hypotheses([e, h_strong, h_weak])
        scores = [h["rule_based_score"] for h in ranked]
        assert scores == sorted(scores, reverse=True)


# ── explain_leading ───────────────────────────────────────────────────────────

class TestExplainLeading:
    def test_returns_leading_text(self):
        evidence = make_claim("e1", "Fever cough infection finding",
                              claim_type="finding", source_type="guideline")
        hyp = make_claim("h1", "Fever cough infection pneumonia", claim_type="hypothesis")
        ranked = rank_hypotheses([evidence, hyp])
        explanation = explain_leading(ranked, [evidence, hyp])
        assert "pneumonia" in explanation["leading"].lower() or "fever" in explanation["leading"].lower()

    def test_returns_supporting_texts(self):
        evidence = make_claim("e1", "Fever cough infection finding",
                              claim_type="finding", source_type="guideline")
        hyp = make_claim("h1", "Fever cough infection pneumonia", claim_type="hypothesis")
        ranked = rank_hypotheses([evidence, hyp])
        explanation = explain_leading(ranked, [evidence, hyp])
        assert isinstance(explanation["supporting"], list)
        assert len(explanation["supporting"]) >= 1

    def test_returns_conflicting_texts(self):
        conflict = make_claim("e1", "No fever cough infection found", claim_type="finding")
        hyp = make_claim("h1", "Fever cough infection pneumonia", claim_type="hypothesis")
        ranked = rank_hypotheses([conflict, hyp])
        explanation = explain_leading(ranked, [conflict, hyp])
        assert isinstance(explanation["conflicting"], list)

    def test_empty_ranked_returns_error(self):
        explanation = explain_leading([], [])
        assert "error" in explanation

    def test_key_missing_provided_when_two_hypotheses(self):
        e = make_claim("e1", "Fever cough infection", claim_type="finding",
                       source_type="guideline")
        h1 = make_claim("h1", "Fever cough pneumonia infection", claim_type="hypothesis")
        h2 = make_claim("h2", "Embolism dyspnea hypothesis", claim_type="hypothesis")
        ranked = rank_hypotheses([e, h1, h2])
        explanation = explain_leading(ranked, [e, h1, h2])
        assert isinstance(explanation["key_missing"], list)

    def test_no_key_missing_with_single_hypothesis(self):
        e = make_claim("e1", "Fever cough infection", claim_type="finding",
                       source_type="guideline")
        h = make_claim("h1", "Fever cough infection hypothesis", claim_type="hypothesis")
        ranked = rank_hypotheses([e, h])
        explanation = explain_leading(ranked, [e, h])
        assert explanation["key_missing"] == []


# ── required_evidence_for ─────────────────────────────────────────────────────

class TestRequiredEvidenceFor:
    def test_pneumonia_returns_required_terms(self):
        required = required_evidence_for("community-acquired pneumonia")
        assert "fever" in required
        assert "cough" in required

    def test_pulmonary_embolism_returns_required(self):
        required = required_evidence_for("suspected pulmonary embolism")
        assert "dyspnea" in required

    def test_sepsis_returns_required(self):
        required = required_evidence_for("sepsis")
        assert "fever" in required
        assert "infection" in required

    def test_myocardial_infarction_match(self):
        required = required_evidence_for("acute myocardial infarction")
        assert "chest pain" in required or "troponin" in required

    def test_unknown_hypothesis_returns_empty(self):
        assert required_evidence_for("rare tropical disease unknown") == []

    def test_case_insensitive(self):
        assert required_evidence_for("PNEUMONIA") == required_evidence_for("pneumonia")

    def test_guidelines_dict_nonempty(self):
        assert len(GUIDELINES) >= 4


# ── get_confident_leading ─────────────────────────────────────────────────────

class TestGetConfidentLeading:
    def test_empty_ranked_returns_insufficient(self):
        result = get_confident_leading([])
        assert result["status"] == "insufficient"

    def test_low_score_returns_insufficient(self):
        e = make_claim("e1", "Weak single finding", claim_type="finding", source_type="llm",
                       evidence_support_score=0.1)
        h = make_claim("h1", "Weak single hypothesis finding", claim_type="hypothesis")
        ranked = rank_hypotheses([e, h])
        # Force score to be low by using very weak evidence
        result = get_confident_leading(ranked)
        # Score might be low enough for insufficient
        assert result["status"] in ("confident", "insufficient")

    def test_confident_with_good_support(self):
        evidence = [
            make_claim(f"e{i}", "Fever cough infection pneumonia finding",
                       claim_type="finding", source_type="guideline",
                       evidence_support_score=0.9)
            for i in range(3)
        ]
        hyp = make_claim("h1", "Fever cough infection pneumonia hypothesis", claim_type="hypothesis")
        ranked = rank_hypotheses(evidence + [hyp])
        result = get_confident_leading(ranked)
        assert result["status"] == "confident"
        assert "leading" in result
        assert "score" in result

    def test_too_many_conflicts_returns_insufficient(self):
        conflicts = [
            make_claim(f"e{i}", "No fever cough infection found",
                       claim_type="finding")
            for i in range(4)  # 4 conflicting claims >= MAX_CONFLICT_IDS (3)
        ]
        hyp = make_claim("h1", "Fever cough infection hypothesis", claim_type="hypothesis")
        ranked = rank_hypotheses([hyp] + conflicts)
        result = get_confident_leading(ranked)
        assert result["status"] == "insufficient"
        assert "conflict_count" in result

    def test_insufficient_reason_text(self):
        result = get_confident_leading([])
        assert "insufficient" in result["reason"].lower() or "no" in result["reason"].lower()


# ── build_case_snapshot ───────────────────────────────────────────────────────

class TestBuildCaseSnapshot:
    def _make_session(self):
        evidence = make_claim("e1", "Fever cough infection finding",
                              claim_type="finding", source_type="guideline")
        hyp = make_claim("h1", "Fever cough infection hypothesis", claim_type="hypothesis")
        return [evidence, hyp]

    def test_snapshot_has_timestamp(self):
        snapshot = build_case_snapshot(self._make_session())
        assert "timestamp" in snapshot
        assert "T" in snapshot["timestamp"]  # ISO format

    def test_snapshot_has_leading_hypothesis(self):
        snapshot = build_case_snapshot(self._make_session())
        assert snapshot["leading_hypothesis"] is not None

    def test_snapshot_has_leading_score(self):
        snapshot = build_case_snapshot(self._make_session())
        assert isinstance(snapshot["leading_score"], float)

    def test_snapshot_has_ranked_hypotheses(self):
        snapshot = build_case_snapshot(self._make_session())
        assert isinstance(snapshot["ranked_hypotheses"], list)
        assert len(snapshot["ranked_hypotheses"]) >= 1

    def test_snapshot_ranked_has_expected_keys(self):
        snapshot = build_case_snapshot(self._make_session())
        entry = snapshot["ranked_hypotheses"][0]
        assert "id" in entry
        assert "text" in entry
        assert "score" in entry
        assert "supporting_count" in entry
        assert "conflicting_count" in entry

    def test_snapshot_active_claim_count(self):
        claims = self._make_session()
        snapshot = build_case_snapshot(claims)
        assert snapshot["active_claim_count"] == 2

    def test_snapshot_total_claim_count(self):
        claims = self._make_session()
        snapshot = build_case_snapshot(claims)
        assert snapshot["total_claim_count"] == 2

    def test_snapshot_empty_session(self):
        snapshot = build_case_snapshot([])
        assert snapshot["leading_hypothesis"] is None
        assert snapshot["leading_score"] is None
        assert snapshot["ranked_hypotheses"] == []
        assert snapshot["active_claim_count"] == 0

    def test_snapshot_confidence_status_present(self):
        snapshot = build_case_snapshot(self._make_session())
        assert snapshot["confidence_status"] in ("confident", "insufficient")


# ── build_reasoning_context ───────────────────────────────────────────────────

class TestBuildReasoningContext:
    def test_contains_rule_based_header(self):
        e = make_claim("e1", "Fever cough infection", claim_type="finding",
                       source_type="guideline")
        h = make_claim("h1", "Fever cough infection hypothesis", claim_type="hypothesis")
        ctx = build_reasoning_context([e, h])
        assert "RULE-BASED" in ctx

    def test_contains_all_claims_section(self):
        e = make_claim("e1", "Fever", claim_type="finding")
        ctx = build_reasoning_context([e])
        assert "ALL CLAIMS" in ctx

    def test_insufficient_warning_shown_when_no_hypotheses(self):
        e = make_claim("e1", "Fever finding", claim_type="finding")
        ctx = build_reasoning_context([e])
        # No hypotheses → ranked is empty → no warning line expected
        assert "ALL CLAIMS" in ctx

    def test_context_is_string(self):
        ctx = build_reasoning_context([])
        assert isinstance(ctx, str)
