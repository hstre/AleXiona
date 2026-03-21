"""Unit tests for Pydantic models and enums in models.py."""
import pytest
from pydantic import ValidationError
from models import (
    Claim, ClaimType, SourceType, ClaimStatus, ClaimTrend,
    Relation, MissingEvidence, Alternative, CounterfactualShift,
    CounterfactualResult, ReasoningResult, Conflict, ConflictType, ConflictSeverity,
    GraphData, ChatMessage, ChatRequest, ChatResponse,
)


# ── Enum completeness ─────────────────────────────────────────────────────────

class TestEnums:
    def test_claim_type_has_nine_values(self):
        expected = {"symptom", "finding", "lab", "imaging", "hypothesis",
                    "diagnosis", "therapy", "risk_factor", "guideline"}
        assert {e.value for e in ClaimType} == expected

    def test_source_type_values(self):
        expected = {"clinician", "llm", "guideline", "imaging_model",
                    "lab_system", "imported_document"}
        assert {e.value for e in SourceType} == expected

    def test_claim_status_values(self):
        assert {e.value for e in ClaimStatus} == {
            "active", "confirmed", "refuted", "resolved", "superseded"
        }

    def test_claim_trend_values(self):
        assert {e.value for e in ClaimTrend} == {"improving", "worsening", "stable", "unknown"}

    def test_conflict_type_values(self):
        expected = {
            "competing_hypothesis", "negation", "evidence_mismatch", "timeline_gap",
            "therapy_without_indication", "stale_hypothesis", "contradictory_values",
            "temporal_inconsistency",
        }
        assert {e.value for e in ConflictType} == expected

    def test_conflict_severity_values(self):
        assert {e.value for e in ConflictSeverity} == {"error", "warning", "info"}


# ── Claim defaults ────────────────────────────────────────────────────────────

class TestClaimDefaults:
    def test_minimal_claim_uses_defaults(self):
        c = Claim(text="Fever 39°C")
        assert c.entities == []
        assert c.relations == []
        assert c.evidence_support_score == 0.8
        assert c.claim_type == ClaimType.finding
        assert c.source_type == SourceType.llm
        assert c.source_ref == ""
        assert c.derived_from == []
        assert c.status == ClaimStatus.active
        assert c.time_offset is None
        assert c.trend == ClaimTrend.unknown

    def test_claim_requires_text(self):
        with pytest.raises(ValidationError):
            Claim()  # type: ignore[call-arg]

    def test_claim_accepts_all_claim_types(self):
        for ct in ClaimType:
            c = Claim(text="test", claim_type=ct)
            assert c.claim_type == ct

    def test_claim_accepts_all_source_types(self):
        for st in SourceType:
            c = Claim(text="test", source_type=st)
            assert c.source_type == st

    def test_claim_accepts_all_statuses(self):
        for s in ClaimStatus:
            c = Claim(text="test", status=s)
            assert c.status == s

    def test_claim_rejects_invalid_claim_type(self):
        with pytest.raises(ValidationError):
            Claim(text="test", claim_type="unknown_type")

    def test_claim_rejects_invalid_source_type(self):
        with pytest.raises(ValidationError):
            Claim(text="test", source_type="robot")

    def test_claim_ess_float_coercion(self):
        c = Claim(text="test", evidence_support_score=1)  # int → float
        assert isinstance(c.evidence_support_score, float)
        assert c.evidence_support_score == 1.0

    def test_claim_time_offset_stored(self):
        c = Claim(text="test", time_offset="t+6h")
        assert c.time_offset == "t+6h"

    def test_claim_derived_from_list(self):
        c = Claim(text="test", derived_from=["id-abc", "id-def"])
        assert c.derived_from == ["id-abc", "id-def"]


# ── Relation ──────────────────────────────────────────────────────────────────

class TestRelation:
    def test_relation_requires_all_fields(self):
        r = Relation(from_entity="fever", to_entity="infection", type="indicates")
        assert r.from_entity == "fever"
        assert r.to_entity == "infection"
        assert r.type == "indicates"

    def test_relation_missing_field_raises(self):
        with pytest.raises(ValidationError):
            Relation(from_entity="fever", type="indicates")  # type: ignore[call-arg]

    def test_claim_with_relations(self):
        c = Claim(
            text="Fever indicates infection",
            relations=[Relation(from_entity="fever", to_entity="infection", type="indicates")],
        )
        assert len(c.relations) == 1


# ── Reasoning models ──────────────────────────────────────────────────────────

class TestReasoningModels:
    def test_missing_evidence_fields(self):
        me = MissingEvidence(
            description="D-Dimer not measured",
            needed_for="pulmonary embolism",
            test_or_type="D-Dimer",
        )
        assert me.test_or_type == "D-Dimer"

    def test_alternative_defaults(self):
        a = Alternative(label="PE", evidence_support_score=0.3)
        assert a.supporting_claim_ids == []

    def test_counterfactual_shift(self):
        s = CounterfactualShift(hypothesis="CAP", score_before=0.82, score_after=0.55)
        assert s.score_before > s.score_after

    def test_counterfactual_result(self):
        r = CounterfactualResult(
            excluded_claim_text="CRP 184 mg/L",
            changed_evidence=["CRP removed"],
            shifts=[CounterfactualShift(hypothesis="CAP", score_before=0.82, score_after=0.60)],
            reasoning_trace="Without CRP the bacterial evidence weakens.",
        )
        assert len(r.shifts) == 1
        assert r.reasoning_trace != ""

    def test_reasoning_result_full(self):
        rr = ReasoningResult(
            leading_hypothesis="Community-acquired pneumonia",
            supporting_evidence=["Fever", "CRP elevated"],
            conflicting_evidence=[],
            evidence_support_score=0.82,
            alternatives=[Alternative(label="PE", evidence_support_score=0.18)],
            missing_evidence=[
                MissingEvidence(
                    description="Blood culture",
                    needed_for="bacterial pneumonia",
                    test_or_type="Blood culture",
                )
            ],
            focus_points=["Antibiotic coverage"],
        )
        assert rr.evidence_support_score == 0.82
        assert len(rr.missing_evidence) == 1


# ── Conflict model ────────────────────────────────────────────────────────────

class TestConflictModel:
    def test_conflict_required_fields(self):
        c = Conflict(
            id="conflict-1",
            type=ConflictType.negation,
            severity=ConflictSeverity.error,
            message="Contradictory claims",
            affected_claim_ids=["a", "b"],
        )
        assert c.id == "conflict-1"
        assert c.type == ConflictType.negation


# ── API models ────────────────────────────────────────────────────────────────

class TestApiModels:
    def test_chat_request_defaults(self):
        req = ChatRequest(message="Hello", session_id="sess-1")
        assert req.history == []

    def test_chat_response_defaults(self):
        resp = ChatResponse(reply="Hi", claims=[], session_id="sess-1")
        assert resp.reasoning is None
        assert resp.conflicts == []

    def test_graph_data(self):
        gd = GraphData(nodes=[{"id": "n1"}], edges=[])
        assert len(gd.nodes) == 1
        assert gd.edges == []

    def test_chat_message(self):
        m = ChatMessage(role="user", content="Hello")
        assert m.role == "user"


# ── NodeUpdate notes field ─────────────────────────────────────────────────────

from models import NodeUpdate


class TestNodeUpdateNotes:
    def test_notes_defaults_to_none(self):
        u = NodeUpdate()
        assert u.notes is None

    def test_notes_accepts_string(self):
        u = NodeUpdate(notes="Follow-up echo scheduled")
        assert u.notes == "Follow-up echo scheduled"

    def test_notes_accepts_empty_string(self):
        u = NodeUpdate(notes="")
        assert u.notes == ""

    def test_notes_accepts_none_explicitly(self):
        u = NodeUpdate(notes=None)
        assert u.notes is None

    def test_notes_alongside_other_fields(self):
        u = NodeUpdate(text="Fever resolved", status="resolved", notes="Apyrexial for 24h")
        assert u.notes == "Apyrexial for 24h"
        assert u.text == "Fever resolved"

    def test_node_update_all_none_is_valid(self):
        """NodeUpdate with no fields set should be valid (partial patch)."""
        u = NodeUpdate()
        assert u.text is None
        assert u.notes is None
