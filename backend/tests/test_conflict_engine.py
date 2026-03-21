"""Unit tests for conflict_engine.detect_conflicts().

All tests use in-memory claim dicts — no Neo4j or LLM required.
"""
import pytest
from conflict_engine import detect_conflicts
from models import ConflictType, ConflictSeverity, _parse_offset_hours


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_claim(
    id: str,
    text: str,
    claim_type: str = "finding",
    status: str = "active",
    evidence_support_score: float = 0.8,
    derived_from: list[str] | None = None,
    time_offset: str | None = None,
) -> dict:
    return {
        "id": id,
        "text": text,
        "claim_type": claim_type,
        "status": status,
        "evidence_support_score": evidence_support_score,
        "derived_from": derived_from or [],
        "time_offset": time_offset,
    }


# ── Rule 1: Competing hypotheses ─────────────────────────────────────────────

class TestCompetingHypotheses:
    def test_two_diagnoses_triggers_conflict(self):
        claims = [
            make_claim("d1", "Community-acquired pneumonia", claim_type="diagnosis"),
            make_claim("d2", "Pulmonary embolism", claim_type="diagnosis"),
        ]
        conflicts = detect_conflicts(claims)
        types = [c.type for c in conflicts]
        assert ConflictType.competing_hypothesis in types

    def test_two_hypotheses_triggers_conflict(self):
        claims = [
            make_claim("h1", "Bacterial infection hypothesis", claim_type="hypothesis"),
            make_claim("h2", "Viral infection hypothesis", claim_type="hypothesis"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.competing_hypothesis for c in conflicts)

    def test_mixed_diagnosis_hypothesis_triggers_conflict(self):
        claims = [
            make_claim("d1", "Pneumonia diagnosis", claim_type="diagnosis"),
            make_claim("h1", "Sepsis hypothesis", claim_type="hypothesis"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.competing_hypothesis for c in conflicts)

    def test_single_hypothesis_no_conflict(self):
        claims = [make_claim("h1", "Pneumonia hypothesis", claim_type="hypothesis")]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.competing_hypothesis for c in conflicts)

    def test_competing_conflict_is_warning(self):
        claims = [
            make_claim("d1", "Diagnosis A", claim_type="diagnosis"),
            make_claim("d2", "Diagnosis B", claim_type="diagnosis"),
        ]
        comp = next(c for c in detect_conflicts(claims) if c.type == ConflictType.competing_hypothesis)
        assert comp.severity == ConflictSeverity.warning

    def test_superseded_hypothesis_excluded(self):
        """A superseded hypothesis should not count toward competing_hypothesis."""
        claims = [
            make_claim("d1", "Active diagnosis", claim_type="diagnosis"),
            make_claim("d2", "Old diagnosis", claim_type="diagnosis", status="superseded"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.competing_hypothesis for c in conflicts)

    def test_affected_ids_include_both_claims(self):
        claims = [
            make_claim("d1", "Diagnosis A", claim_type="diagnosis"),
            make_claim("d2", "Diagnosis B", claim_type="diagnosis"),
        ]
        comp = next(c for c in detect_conflicts(claims) if c.type == ConflictType.competing_hypothesis)
        assert "d1" in comp.affected_claim_ids
        assert "d2" in comp.affected_claim_ids


# ── Rule 2: Negation clash ────────────────────────────────────────────────────

class TestNegationClash:
    def test_english_negation_detected(self):
        claims = [
            make_claim("c1", "Patient has fever"),
            make_claim("c2", "Patient has no fever"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.negation for c in conflicts)

    def test_german_negation_detected(self):
        claims = [
            make_claim("c1", "Fieber vorhanden beim Patienten"),
            make_claim("c2", "Kein Fieber beim Patienten"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.negation for c in conflicts)

    def test_negation_is_error_severity(self):
        claims = [
            make_claim("c1", "Infiltrate found in lung"),
            make_claim("c2", "No infiltrate found in lung"),
        ]
        neg = next(c for c in detect_conflicts(claims) if c.type == ConflictType.negation)
        assert neg.severity == ConflictSeverity.error

    def test_both_negated_no_conflict(self):
        """Two negated claims don't clash."""
        claims = [
            make_claim("c1", "No fever present in patient"),
            make_claim("c2", "No fever detected in patient"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.negation for c in conflicts)

    def test_insufficient_keyword_overlap_no_conflict(self):
        """Less than 2 shared key terms → no negation conflict."""
        claims = [
            make_claim("c1", "Patient has fever"),
            make_claim("c2", "No pneumonia detected"),  # only 1 shared token at most
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.negation for c in conflicts)

    def test_ruled_out_negation(self):
        claims = [
            make_claim("c1", "Pulmonary embolism suspected"),
            make_claim("c2", "Pulmonary embolism ruled out"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.negation for c in conflicts)

    def test_negation_only_on_active_claims(self):
        claims = [
            make_claim("c1", "Patient has fever", status="active"),
            make_claim("c2", "Patient has no fever", status="superseded"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.negation for c in conflicts)


# ── Rule 3: Evidence mismatch ─────────────────────────────────────────────────

class TestEvidenceMismatch:
    def test_strong_evidence_weak_hypothesis_triggers(self):
        claims = [
            make_claim("e1", "CRP elevated 184 mg/L", claim_type="lab", evidence_support_score=0.90),
            make_claim("h1", "Bacterial infection", claim_type="hypothesis", evidence_support_score=0.35),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.evidence_mismatch for c in conflicts)

    def test_mismatch_is_info_severity(self):
        claims = [
            make_claim("e1", "Leukocytes elevated", claim_type="lab", evidence_support_score=0.92),
            make_claim("h1", "Infection hypothesis", claim_type="hypothesis", evidence_support_score=0.30),
        ]
        mismatch = next(c for c in detect_conflicts(claims) if c.type == ConflictType.evidence_mismatch)
        assert mismatch.severity == ConflictSeverity.info

    def test_weak_evidence_no_mismatch(self):
        claims = [
            make_claim("e1", "Mild fever finding", claim_type="finding", evidence_support_score=0.60),
            make_claim("h1", "Hypothesis", claim_type="hypothesis", evidence_support_score=0.30),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.evidence_mismatch for c in conflicts)

    def test_strong_hypothesis_no_mismatch(self):
        claims = [
            make_claim("e1", "Consolidation on CT", claim_type="imaging", evidence_support_score=0.95),
            make_claim("h1", "Strong hypothesis", claim_type="hypothesis", evidence_support_score=0.80),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.evidence_mismatch for c in conflicts)

    def test_ess_boundary_at_085(self):
        """Evidence at exactly 0.85 should count as strong."""
        claims = [
            make_claim("e1", "Lab finding", claim_type="lab", evidence_support_score=0.85),
            make_claim("h1", "Hypothesis", claim_type="hypothesis", evidence_support_score=0.39),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.evidence_mismatch for c in conflicts)

    def test_ess_just_below_boundary(self):
        """Evidence at 0.84 should NOT count as strong."""
        claims = [
            make_claim("e1", "Lab finding", claim_type="lab", evidence_support_score=0.84),
            make_claim("h1", "Hypothesis", claim_type="hypothesis", evidence_support_score=0.30),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.evidence_mismatch for c in conflicts)


# ── Rule 4: Timeline / stale derivation ───────────────────────────────────────

class TestTimelineGap:
    def test_derived_from_superseded_triggers(self):
        claims = [
            make_claim("sup1", "Viral pneumonia hypothesis", claim_type="hypothesis", status="superseded"),
            make_claim("act1", "Follow-up therapy", claim_type="therapy", derived_from=["sup1"]),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.timeline_gap for c in conflicts)

    def test_timeline_gap_is_warning(self):
        claims = [
            make_claim("sup1", "Old finding", status="superseded"),
            make_claim("act1", "Current finding", derived_from=["sup1"]),
        ]
        gap = next(c for c in detect_conflicts(claims) if c.type == ConflictType.timeline_gap)
        assert gap.severity == ConflictSeverity.warning

    def test_derived_from_active_no_gap(self):
        claims = [
            make_claim("src1", "Source claim", status="active"),
            make_claim("act1", "Derived claim", derived_from=["src1"]),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.timeline_gap for c in conflicts)

    def test_derived_from_resolved_no_gap(self):
        """Only superseded triggers the gap rule, not resolved."""
        claims = [
            make_claim("res1", "Resolved finding", status="resolved"),
            make_claim("act1", "Active claim", derived_from=["res1"]),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.timeline_gap for c in conflicts)

    def test_no_derivation_no_gap(self):
        claims = [
            make_claim("sup1", "Superseded claim", status="superseded"),
            make_claim("act1", "Active independent claim"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.timeline_gap for c in conflicts)

    def test_affected_ids_include_both(self):
        claims = [
            make_claim("sup1", "Old hypothesis", status="superseded"),
            make_claim("act1", "New therapy", derived_from=["sup1"]),
        ]
        gap = next(c for c in detect_conflicts(claims) if c.type == ConflictType.timeline_gap)
        assert "act1" in gap.affected_claim_ids
        assert "sup1" in gap.affected_claim_ids


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_claims_no_conflict(self):
        assert detect_conflicts([]) == []

    def test_single_claim_no_conflict(self):
        claims = [make_claim("c1", "Patient has fever")]
        assert detect_conflicts(claims) == []

    def test_all_resolved_no_active_conflicts(self):
        claims = [
            make_claim("d1", "Diagnosis A", claim_type="diagnosis", status="resolved"),
            make_claim("d2", "Diagnosis B", claim_type="diagnosis", status="resolved"),
        ]
        conflicts = detect_conflicts(claims)
        # No active leads → no competing_hypothesis
        assert not any(c.type == ConflictType.competing_hypothesis for c in conflicts)

    def test_multiple_rules_can_fire_simultaneously(self):
        """A set of claims can trigger more than one rule."""
        claims = [
            make_claim("d1", "Pneumonia diagnosis", claim_type="diagnosis"),
            make_claim("d2", "Sepsis diagnosis", claim_type="diagnosis"),
            make_claim("lab1", "CRP elevated lab result", claim_type="lab", evidence_support_score=0.95),
            make_claim("h1", "Weak hypothesis candidate", claim_type="hypothesis", evidence_support_score=0.30),
        ]
        types = {c.type for c in detect_conflicts(claims)}
        assert ConflictType.competing_hypothesis in types
        assert ConflictType.evidence_mismatch in types

    def test_returns_list_type(self):
        result = detect_conflicts([make_claim("c1", "Some claim")])
        assert isinstance(result, list)


# ── Rule 5: Therapy without active indication ─────────────────────────────────

class TestTherapyWithoutIndication:
    def test_therapy_targets_superseded_diagnosis(self):
        claims = [
            make_claim("d1", "Pulmonary embolism diagnosis", claim_type="diagnosis", status="superseded"),
            make_claim("t1", "Anticoagulation therapy for pulmonary embolism", claim_type="therapy"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.therapy_without_indication for c in conflicts)

    def test_therapy_targets_resolved_diagnosis(self):
        claims = [
            make_claim("d1", "Pneumonia diagnosis confirmed", claim_type="diagnosis", status="resolved"),
            make_claim("t1", "Antibiotic therapy for pneumonia diagnosis", claim_type="therapy"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.therapy_without_indication for c in conflicts)

    def test_therapy_with_active_diagnosis_no_conflict(self):
        """Active diagnosis supports the therapy — no conflict."""
        claims = [
            make_claim("d1", "Pulmonary embolism active diagnosis", claim_type="diagnosis"),
            make_claim("t1", "Anticoagulation therapy for pulmonary embolism", claim_type="therapy"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.therapy_without_indication for c in conflicts)

    def test_therapy_no_overlap_no_conflict(self):
        """Therapy and superseded diagnosis share <2 terms — not linked."""
        claims = [
            make_claim("d1", "Cardiac failure diagnosis", claim_type="diagnosis", status="superseded"),
            make_claim("t1", "Antibiotic treatment for infection", claim_type="therapy"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.therapy_without_indication for c in conflicts)

    def test_therapy_without_indication_is_warning(self):
        claims = [
            make_claim("d1", "Pneumonia diagnosis treatment plan", claim_type="diagnosis", status="superseded"),
            make_claim("t1", "Antibiotic therapy for pneumonia treatment", claim_type="therapy"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.therapy_without_indication)
        assert c.severity == ConflictSeverity.warning

    def test_affected_ids_include_therapy_and_diagnosis(self):
        claims = [
            make_claim("d1", "Pulmonary embolism diagnosis confirmed", claim_type="diagnosis", status="superseded"),
            make_claim("t1", "Anticoagulation pulmonary embolism therapy", claim_type="therapy"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.therapy_without_indication)
        assert "t1" in c.affected_claim_ids
        assert "d1" in c.affected_claim_ids


# ── Rule 6: Stale hypothesis ──────────────────────────────────────────────────

class TestStaleHypothesis:
    def test_hypothesis_only_superseded_evidence_triggers(self):
        claims = [
            make_claim("e1", "CRP elevated troponin result", claim_type="lab", status="superseded"),
            make_claim("h1", "Cardiac hypothesis elevated troponin", claim_type="hypothesis"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.stale_hypothesis for c in conflicts)

    def test_hypothesis_with_active_evidence_no_conflict(self):
        claims = [
            make_claim("e1", "CRP elevated troponin result", claim_type="lab", status="superseded"),
            make_claim("e2", "CRP elevated troponin current", claim_type="lab", status="active"),
            make_claim("h1", "Cardiac hypothesis elevated troponin", claim_type="hypothesis"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.stale_hypothesis for c in conflicts)

    def test_hypothesis_no_evidence_overlap_no_conflict(self):
        """Hypothesis doesn't share terms with any evidence — rule doesn't fire."""
        claims = [
            make_claim("e1", "Kidney creatinine level result", claim_type="lab", status="superseded"),
            make_claim("h1", "Cardiac arrest hypothesis possible", claim_type="hypothesis"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.stale_hypothesis for c in conflicts)

    def test_stale_hypothesis_is_warning(self):
        claims = [
            make_claim("e1", "Troponin elevated cardiac injury result", claim_type="lab", status="superseded"),
            make_claim("h1", "Troponin elevated cardiac hypothesis injury", claim_type="hypothesis"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.stale_hypothesis)
        assert c.severity == ConflictSeverity.warning

    def test_stale_diagnosis_also_triggers(self):
        """Rule applies to diagnosis-type claims, not only hypothesis."""
        claims = [
            make_claim("e1", "Infiltrate imaging chest finding", claim_type="imaging", status="superseded"),
            make_claim("d1", "Infiltrate chest imaging diagnosis", claim_type="diagnosis"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.stale_hypothesis for c in conflicts)

    def test_stale_hypothesis_affected_ids(self):
        claims = [
            make_claim("e1", "CRP elevated troponin result", claim_type="lab", status="superseded"),
            make_claim("h1", "Cardiac hypothesis elevated troponin", claim_type="hypothesis"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.stale_hypothesis)
        assert "h1" in c.affected_claim_ids
        assert "e1" in c.affected_claim_ids


# ── Rule 7: Contradictory quantitative values ────────────────────────────────

class TestContradictoryValues:
    def test_elevated_vs_normal_triggers(self):
        claims = [
            make_claim("e1", "CRP elevated above reference range", claim_type="lab"),
            make_claim("e2", "CRP within normal limits reference range", claim_type="lab"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.contradictory_values for c in conflicts)

    def test_increased_vs_decreased_triggers(self):
        claims = [
            make_claim("e1", "Leukocytes significantly increased blood count", claim_type="lab"),
            make_claim("e2", "Leukocytes decreased blood count result", claim_type="lab"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.contradictory_values for c in conflicts)

    def test_german_erhöht_vs_normwertig(self):
        claims = [
            make_claim("e1", "Troponin erhöht beim Patienten festgestellt", claim_type="finding"),
            make_claim("e2", "Troponin normwertig beim Patienten gemessen", claim_type="finding"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.contradictory_values for c in conflicts)

    def test_both_elevated_no_conflict(self):
        claims = [
            make_claim("e1", "CRP elevated above reference", claim_type="lab"),
            make_claim("e2", "CRP elevated significantly high", claim_type="lab"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.contradictory_values for c in conflicts)

    def test_no_shared_terms_no_conflict(self):
        claims = [
            make_claim("e1", "CRP elevated above threshold", claim_type="lab"),
            make_claim("e2", "Troponin within normal limits", claim_type="lab"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.contradictory_values for c in conflicts)

    def test_negation_pair_not_double_counted(self):
        """A pair caught by the negation rule should not also fire contradictory_values."""
        claims = [
            make_claim("e1", "Infiltrate elevated found in lung tissue"),
            make_claim("e2", "No infiltrate elevated found in lung tissue"),
        ]
        conflicts = detect_conflicts(claims)
        types = [c.type for c in conflicts]
        # negation fires; contradictory_values must not (negation excluded from rule 7)
        assert ConflictType.negation in types
        assert ConflictType.contradictory_values not in types

    def test_contradictory_values_is_error_severity(self):
        claims = [
            make_claim("e1", "CRP elevated above reference range", claim_type="lab"),
            make_claim("e2", "CRP within normal limits reference range", claim_type="lab"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.contradictory_values)
        assert c.severity == ConflictSeverity.error

    def test_only_evidence_types_checked(self):
        """contradictory_values only fires on evidence-type claims, not therapy/diagnosis."""
        claims = [
            make_claim("t1", "Anticoagulation elevated dose therapy", claim_type="therapy"),
            make_claim("d1", "Anticoagulation normal dose diagnosis", claim_type="diagnosis"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.contradictory_values for c in conflicts)


# ── Rule 8: Temporal inconsistency ───────────────────────────────────────────

class TestTemporalInconsistency:
    def test_child_earlier_than_source_triggers(self):
        claims = [
            make_claim("src", "Source finding", time_offset="t+12h"),
            make_claim("child", "Derived finding", derived_from=["src"], time_offset="t+6h"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.temporal_inconsistency for c in conflicts)

    def test_child_later_than_source_no_conflict(self):
        claims = [
            make_claim("src", "Source finding", time_offset="t+6h"),
            make_claim("child", "Derived finding", derived_from=["src"], time_offset="t+12h"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.temporal_inconsistency for c in conflicts)

    def test_child_same_time_as_source_no_conflict(self):
        claims = [
            make_claim("src", "Source finding", time_offset="t+6h"),
            make_claim("child", "Derived finding", derived_from=["src"], time_offset="t+6h"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.temporal_inconsistency for c in conflicts)

    def test_no_time_offset_on_child_no_conflict(self):
        """Cannot determine ordering without a child time_offset."""
        claims = [
            make_claim("src", "Source finding", time_offset="t+12h"),
            make_claim("child", "Derived finding", derived_from=["src"]),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.temporal_inconsistency for c in conflicts)

    def test_no_time_offset_on_source_no_conflict(self):
        """Cannot determine ordering without a source time_offset."""
        claims = [
            make_claim("src", "Source finding"),
            make_claim("child", "Derived finding", derived_from=["src"], time_offset="t+6h"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.temporal_inconsistency for c in conflicts)

    def test_temporal_inconsistency_is_error(self):
        claims = [
            make_claim("src", "Source finding", time_offset="t+24h"),
            make_claim("child", "Derived finding", derived_from=["src"], time_offset="t+1h"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.temporal_inconsistency)
        assert c.severity == ConflictSeverity.error

    def test_affected_ids_include_both(self):
        claims = [
            make_claim("src", "Source finding", time_offset="t+24h"),
            make_claim("child", "Derived finding", derived_from=["src"], time_offset="t+1h"),
        ]
        c = next(x for x in detect_conflicts(claims) if x.type == ConflictType.temporal_inconsistency)
        assert "src" in c.affected_claim_ids
        assert "child" in c.affected_claim_ids

    def test_no_derived_from_no_conflict(self):
        """Without explicit derivation, time comparison is not performed."""
        claims = [
            make_claim("src", "Early finding", time_offset="t+24h"),
            make_claim("later", "Later finding", time_offset="t+1h"),
        ]
        conflicts = detect_conflicts(claims)
        assert not any(c.type == ConflictType.temporal_inconsistency for c in conflicts)

    def test_superseded_child_still_checked(self):
        """Even superseded claims can expose temporal inconsistencies."""
        claims = [
            make_claim("src", "Source finding", time_offset="t+12h"),
            make_claim("child", "Old derived finding", derived_from=["src"],
                       time_offset="t+4h", status="superseded"),
        ]
        conflicts = detect_conflicts(claims)
        assert any(c.type == ConflictType.temporal_inconsistency for c in conflicts)


# ── _parse_offset_hours unit tests ───────────────────────────────────────────

class TestParseOffsetHours:
    def test_standard_form(self):
        assert _parse_offset_hours("t+6h") == 6.0

    def test_decimal(self):
        assert _parse_offset_hours("t+1.5h") == 1.5

    def test_no_prefix(self):
        assert _parse_offset_hours("6h") == 6.0

    def test_no_h_suffix(self):
        assert _parse_offset_hours("t+6") == 6.0

    def test_bare_number(self):
        assert _parse_offset_hours("6") == 6.0

    def test_none_returns_none(self):
        assert _parse_offset_hours(None) is None

    def test_empty_string_returns_none(self):
        assert _parse_offset_hours("") is None

    def test_unrecognized_format_returns_none(self):
        assert _parse_offset_hours("day2") is None


# ── Rule 9: Stale lab evidence ────────────────────────────────────────────────

class TestStaleLabEvidence:
    def _old_lab(self, id: str, text: str, hyp_text: str = "") -> tuple:
        from datetime import datetime, timezone, timedelta
        old_time = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        lab = {
            "id": id, "text": text, "claim_type": "lab",
            "status": "active", "evidence_support_score": 0.9,
            "derived_from": [], "time_offset": None,
            "event_time": old_time,
        }
        hyp = {
            "id": "h1", "text": hyp_text or text + " hypothesis",
            "claim_type": "hypothesis", "status": "active",
            "evidence_support_score": 0.7, "derived_from": [], "time_offset": None,
        }
        return lab, hyp

    def test_stale_lab_triggers_conflict(self):
        lab, hyp = self._old_lab("l1", "CRP elevated sepsis infection")
        conflicts = detect_conflicts([lab, hyp])
        assert any(c.type == ConflictType.stale_lab_evidence for c in conflicts)

    def test_recent_lab_no_stale_conflict(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        lab = {
            "id": "l1", "text": "CRP elevated sepsis",
            "claim_type": "lab", "status": "active",
            "evidence_support_score": 0.9, "derived_from": [], "time_offset": None,
            "event_time": recent,
        }
        hyp = {
            "id": "h1", "text": "Sepsis hypothesis", "claim_type": "hypothesis",
            "status": "active", "evidence_support_score": 0.7,
            "derived_from": [], "time_offset": None,
        }
        conflicts = detect_conflicts([lab, hyp])
        assert not any(c.type == ConflictType.stale_lab_evidence for c in conflicts)

    def test_lab_without_event_time_not_flagged(self):
        lab = {
            "id": "l1", "text": "CRP elevated sepsis",
            "claim_type": "lab", "status": "active",
            "evidence_support_score": 0.9, "derived_from": [], "time_offset": None,
            # no event_time
        }
        hyp = {
            "id": "h1", "text": "Sepsis hypothesis", "claim_type": "hypothesis",
            "status": "active", "evidence_support_score": 0.7,
            "derived_from": [], "time_offset": None,
        }
        conflicts = detect_conflicts([lab, hyp])
        assert not any(c.type == ConflictType.stale_lab_evidence for c in conflicts)

    def test_stale_conflict_is_warning(self):
        lab, hyp = self._old_lab("l1", "Troponin elevated cardiac sepsis")
        conflicts = detect_conflicts([lab, hyp])
        stale = [c for c in conflicts if c.type == ConflictType.stale_lab_evidence]
        if stale:
            assert stale[0].severity == ConflictSeverity.warning


# ── Rule 10: Time paradox ─────────────────────────────────────────────────────

class TestTimeparadox:
    def test_assertion_before_event_triggers_paradox(self):
        from datetime import datetime, timezone, timedelta
        event     = datetime.now(timezone.utc)
        assertion = (event - timedelta(hours=2)).isoformat()  # asserted BEFORE event
        claim = {
            "id": "c1", "text": "Fever measured",
            "claim_type": "finding", "status": "active",
            "evidence_support_score": 0.8, "derived_from": [], "time_offset": None,
            "event_time": event.isoformat(),
            "assertion_time": assertion,
        }
        conflicts = detect_conflicts([claim])
        assert any(c.type == ConflictType.time_paradox for c in conflicts)

    def test_normal_order_no_paradox(self):
        from datetime import datetime, timezone, timedelta
        event     = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        assertion = datetime.now(timezone.utc).isoformat()  # asserted AFTER event
        claim = {
            "id": "c1", "text": "Fever measured",
            "claim_type": "finding", "status": "active",
            "evidence_support_score": 0.8, "derived_from": [], "time_offset": None,
            "event_time": event,
            "assertion_time": assertion,
        }
        conflicts = detect_conflicts([claim])
        assert not any(c.type == ConflictType.time_paradox for c in conflicts)

    def test_missing_assertion_time_no_paradox(self):
        from datetime import datetime, timezone
        claim = {
            "id": "c1", "text": "Finding noted",
            "claim_type": "finding", "status": "active",
            "evidence_support_score": 0.8, "derived_from": [], "time_offset": None,
            "event_time": datetime.now(timezone.utc).isoformat(),
            # no assertion_time
        }
        conflicts = detect_conflicts([claim])
        assert not any(c.type == ConflictType.time_paradox for c in conflicts)

    def test_paradox_is_error_severity(self):
        from datetime import datetime, timezone, timedelta
        event     = datetime.now(timezone.utc)
        assertion = (event - timedelta(hours=1)).isoformat()
        claim = {
            "id": "c1", "text": "Some finding",
            "claim_type": "finding", "status": "active",
            "evidence_support_score": 0.8, "derived_from": [], "time_offset": None,
            "event_time": event.isoformat(),
            "assertion_time": assertion,
        }
        paradoxes = [c for c in detect_conflicts([claim]) if c.type == ConflictType.time_paradox]
        assert paradoxes[0].severity == ConflictSeverity.error
