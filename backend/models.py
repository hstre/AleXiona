from __future__ import annotations
import re
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator

_TIME_RE = re.compile(r'^(?:t\+)?(\d+(?:\.\d+)?)h?$', re.IGNORECASE)


def _clamp_ess(v: float | None) -> float | None:
    if v is None:
        return v
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.8  # safe default rather than a 500


def _normalize_time_offset(v: str | None) -> str | None:
    """Accepts '6h', '6', 't+6', 't+6h' → 't+6h'; passes through unrecognized forms."""
    if not v:
        return v
    m = _TIME_RE.match(v.strip())
    if m:
        hours = m.group(1)
        return f"t+{hours}h"
    return v.strip()


def _parse_offset_hours(v: str | None) -> float | None:
    """Return the numeric hours from a normalised offset string, or None if unparseable."""
    if not v:
        return None
    m = _TIME_RE.match(v.strip())
    if m:
        return float(m.group(1))
    return None


class ClaimType(str, Enum):
    symptom     = "symptom"
    finding     = "finding"
    lab         = "lab"
    imaging     = "imaging"
    hypothesis  = "hypothesis"
    diagnosis   = "diagnosis"
    therapy     = "therapy"
    risk_factor = "risk_factor"
    guideline   = "guideline"


class SourceType(str, Enum):
    # ── Clinical / institutional sources ─────────────────────────────────────
    clinician          = "clinician"
    llm                = "llm"
    guideline          = "guideline"
    imaging_model      = "imaging_model"
    lab_system         = "lab_system"
    imported_document  = "imported_document"
    # ── Patient-generated sources (own epistemic layer) ───────────────────────
    patient_report     = "patient_report"    # verbal/written self-report, anamnesis
    wearable           = "wearable"          # smartwatch, fitness tracker, CGM
    home_device        = "home_device"       # home BP cuff, pulse oximeter, thermometer
    caregiver_report   = "caregiver_report"  # family member or informal carer


class EvidenceTier(str, Enum):
    """Epistemic quality tier — derived from source_type but can be set explicitly.

    Drives differential weighting in scoring and prevents patient-generated data
    from being silently treated as clinical-grade evidence.
    """
    patient_generated   = "patient_generated"    # self-report, wearable, home device
    clinician_observed  = "clinician_observed"   # bedside examination, clinical note
    instrument_measured = "instrument_measured"  # validated medical device (in-hospital)
    lab_confirmed       = "lab_confirmed"        # laboratory / lab_system result
    guideline_structured = "guideline_structured"  # evidence-based guideline


def source_to_evidence_tier(source_type: str) -> EvidenceTier:
    """Derive the EvidenceTier from a SourceType value."""
    mapping = {
        "patient_report":   EvidenceTier.patient_generated,
        "wearable":         EvidenceTier.patient_generated,
        "home_device":      EvidenceTier.patient_generated,
        "caregiver_report": EvidenceTier.patient_generated,
        "clinician":        EvidenceTier.clinician_observed,
        "imported_document": EvidenceTier.clinician_observed,
        "llm":              EvidenceTier.clinician_observed,
        "imaging_model":    EvidenceTier.instrument_measured,
        "lab_system":       EvidenceTier.lab_confirmed,
        "guideline":        EvidenceTier.guideline_structured,
    }
    return mapping.get(source_type, EvidenceTier.clinician_observed)


class ClaimStatus(str, Enum):
    # ── Epistemic lifecycle (fine-grained) ───────────────────────────────────
    observed   = "observed"    # directly observed/measured — highest epistemic warrant
    inferred   = "inferred"    # derived or interpreted from other observations
    contested  = "contested"   # conflicting evidence exists; flagged for review
    # ── Clinician decisions ──────────────────────────────────────────────────
    confirmed  = "confirmed"   # clinician explicitly confirmed → score boost (×1.5)
    refuted    = "refuted"     # clinician explicitly contradicted → hard excluded from ranking
    withdrawn  = "withdrawn"   # clinician retracted (documentation error, etc.)
    # ── Temporal lifecycle ───────────────────────────────────────────────────
    resolved   = "resolved"    # clinical condition no longer active
    superseded = "superseded"  # replaced by a newer, more current claim
    # ── Backward compat ──────────────────────────────────────────────────────
    active     = "active"      # generic active — treated as "observed" in scoring


class ClaimTrend(str, Enum):
    improving = "improving"
    worsening = "worsening"
    stable    = "stable"
    unknown   = "unknown"


class Relation(BaseModel):
    from_entity: str
    to_entity:   str
    type:        str


class Claim(BaseModel):
    """A structured, time-anchored, revisable clinical claim.

    Two orthogonal time axes (Alexandria principle):
        event_time     — WHEN the medical event/finding actually occurred
        assertion_time — WHEN the claim was entered into the knowledge graph

    These can diverge substantially:
        - "Fever since 3 days" → event_time ≈ now-72h, assertion_time ≈ now
        - Retrospective chart note → event_time = days ago, assertion_time = today

    valid_from / valid_until bound the claim's temporal scope of applicability.
    supersedes_claim_id makes the replacement chain explicit.
    """
    text:                   str
    entities:               list[str]            = []
    relations:              list[Relation]       = []
    evidence_support_score: float                = 0.8
    claim_type:             ClaimType            = ClaimType.finding
    source_type:            SourceType           = SourceType.llm
    source_ref:             str                  = ""
    derived_from:           list[str]            = []   # explicit epistemic derivation
    related_to:             list[str]            = []   # heuristic semantic proximity
    status:                 ClaimStatus          = ClaimStatus.active

    # ── Legacy relative time (retained for backward compat) ──────────────────
    time_offset:            Optional[str]        = None   # e.g. "t+6h"
    trend:                  ClaimTrend           = ClaimTrend.unknown

    # ── Absolute temporal anchoring (Alexandria principle) ───────────────────
    event_time:             Optional[datetime]   = None   # when the medical event occurred
    assertion_time:         Optional[datetime]   = None   # when this claim was entered
    valid_from:             Optional[datetime]   = None   # claim active from this moment
    valid_until:            Optional[datetime]   = None   # claim expires / no longer applicable

    # ── Epistemic provenance ─────────────────────────────────────────────────
    supersedes_claim_id:    Optional[str]        = None   # claim ID this replaces
    uncertainty_flag:       bool                 = False  # LLM/clinician flagged uncertainty
    assumptions:            list[str]            = []     # stated assumptions behind this claim
    normalized_token:       Optional[str]        = None   # canonical lab token (e.g. "crp")

    # ── Patient data layer ───────────────────────────────────────────────────
    evidence_tier:          Optional[str]        = None   # EvidenceTier value; None = derive from source_type
    patient_data_ref:       Optional[str]        = None   # ID of originating PatientObservation or PGM

    # ── Projection metadata (Alexandria: every claim carries its projection origin) ──
    projection_confidence:  Optional[float]      = None   # confidence at projection time (0.0–1.0)
    projection_method:      Optional[str]        = None   # "llm_extraction" | "rule_based_measurement" | "rule_based_observation" | "demo_seed"

    # ── SPL provenance (Semantic Projection Layer — WP2) ─────────────────────
    spl_unit_id:            Optional[str]        = None   # SemanticUnit.unit_id
    spl_projection_id:      Optional[str]        = None   # SemanticProjection.projection_id
    spl_emission_rule:      Optional[str]        = None   # "E1" | "E2" | "E3" | "E0"
    spl_h_norm:             Optional[float]      = None   # normalised Shannon entropy ∈ [0,1]


class ClaimExtractionResult(BaseModel):
    claims: list[Claim]


# ── 4-Stage Extraction Pipeline ───────────────────────────────────────────────
# raw note → ExtractedObservation → ClaimCandidate → Claim (validated)

class ExtractedObservation(BaseModel):
    """Stage 1 — raw LLM output before normalization.

    Captures what the LLM found in free text, with uncertainty/negation signals
    and time references still in raw form (not yet resolved to structured types).
    """
    raw_text:         str
    observation:      str                # extracted observation statement
    observation_type: str                # broad type: symptom | lab | finding | imaging | ...
    temporal_hint:    Optional[str] = None  # raw time reference: "3 days ago", "at 14:20"
    negation_hint:    bool          = False  # "no fever", "ruled out", "absent"
    uncertainty_hint: bool          = False  # "possibly", "suspected", "cannot exclude"
    source_ref:       str           = ""


class ClaimCandidate(BaseModel):
    """Stage 2 — normalized but not yet validated claim.

    Lab values are parsed quantitatively; temporal hints are resolved to datetime
    where possible; tokens are normalized to canonical keys (via lab_parser).
    The candidate is validated into a full Claim by the ingestion pipeline.
    """
    observation:       ExtractedObservation
    candidate_text:    str
    candidate_type:    str                # normalized claim_type
    normalized_token:  Optional[str]   = None  # canonical lab token ("crp", "troponin", ...)
    parsed_value:      Optional[float] = None  # numeric lab value
    parsed_unit:       Optional[str]   = None  # unit string
    qualitative:       Optional[str]   = None  # "high" | "low" | "normal"
    event_time_iso:    Optional[str]   = None  # ISO 8601 datetime if resolved
    confidence:        float           = 0.5


# ── Patient Data Layer ────────────────────────────────────────────────────────
# Separate epistemic layer for patient-generated inputs.
# These objects NEVER directly become ClinicalClaims — they flow through
# normalization (patient_data.py) to produce ClaimCandidates first.

class PatientObservation(BaseModel):
    """Subjective observation from the patient or caregiver (Layer 1).

    Examples: "chest pain when climbing stairs", "dizzy since yesterday morning"
    """
    id:              str
    raw_text:        str
    source_type:     str                  = "patient_report"  # patient_report | caregiver_report
    event_time:      Optional[datetime]   = None
    assertion_time:  Optional[datetime]   = None
    body_location:   Optional[str]        = None   # "chest", "left arm", ...
    onset_hint:      Optional[str]        = None   # "since 3 days", "yesterday morning"
    severity_hint:   Optional[str]        = None   # "mild", "severe", "10/10"
    negation_hint:   bool                 = False   # "no pain", "no fever"
    uncertainty_hint: bool                = False   # "I think", "maybe"
    # Derived after normalization
    candidate_ids:   list[str]            = []      # ClaimCandidate IDs produced from this


class PatientGeneratedMeasurement(BaseModel):
    """A single device measurement from a home device or wearable (Layer 2).

    Examples: SpO2 91% from pulse oximeter, HR 130 from Apple Watch, BP 145/90
    """
    id:              str
    device_type:     str               # "wearable" | "home_device"
    device_name:     Optional[str]  = None   # "Apple Watch Series 9", "Omron BP cuff"
    token:           str               # canonical lab token: "spo2", "heart_rate", "systolic_bp"
    value:           float
    unit:            str
    qualitative:     Optional[str]  = None   # "high" | "low" | "normal" (derived from thresholds)
    event_time:      Optional[datetime]  = None
    assertion_time:  Optional[datetime]  = None
    # Quality metadata
    measurement_quality: Optional[str]  = None   # "good" | "medium" | "poor" | "unknown"
    session_duration_s:  Optional[int]  = None   # for wearables: how long was this measured
    # Derived
    candidate_id:    Optional[str]   = None   # ClaimCandidate ID produced from this


class TrendPoint(BaseModel):
    """A single data point in a time series for trend detection."""
    timestamp:  datetime
    value:      float


class TrendSignal(BaseModel):
    """An extracted trend from a series of PatientGeneratedMeasurements (Layer 2→3).

    Examples: "heart rate +18% over 72h", "SpO2 declining for 3 days"
    """
    id:            str
    token:         str               # canonical lab token
    direction:     str               # "rising" | "falling" | "stable" | "volatile"
    magnitude_pct: float             # percent change over the window
    window_hours:  float             # time window of the trend
    start_value:   float
    end_value:     float
    n_points:      int               # number of measurements in window
    clinical_flag: Optional[str]  = None  # "tachycardia_trend", "hypoxia_trend", ...
    # Derived
    candidate_id:  Optional[str]  = None


# ── Analysis / Reasoning ─────────────────────────────────────────────────────

class Alternative(BaseModel):
    label:                  str
    evidence_support_score: float
    supporting_claim_ids:   list[str] = []


class MissingEvidence(BaseModel):
    description:              str
    needed_for:               str
    test_or_type:             str
    differentiates_between:   list[str] = []


class CounterfactualShift(BaseModel):
    hypothesis:    str
    score_before:  float
    score_after:   float


class CounterfactualResult(BaseModel):
    excluded_claim_text: str
    changed_evidence:    list[str]
    shifts:              list[CounterfactualShift]
    reasoning_trace:     str
    guideline_shift:     Optional[dict] = None


class HypothesisCounterfactualResult(BaseModel):
    """Result of asking: 'What would need to change for this hypothesis to be false?'"""
    hypothesis:           str
    required_changes:     list[str]
    critical_evidence:    list[str]
    alternative_if_false: str
    reasoning_trace:      str


class ReasoningResult(BaseModel):
    leading_hypothesis:       str
    supporting_evidence:      list[str]
    conflicting_evidence:     list[str]
    evidence_support_score:   float
    alternatives:             list[Alternative]
    missing_evidence:         list[MissingEvidence]
    focus_points:             list[str]


# ── Conflicts ─────────────────────────────────────────────────────────────────

class ConflictSeverity(str, Enum):
    error   = "error"
    warning = "warning"
    info    = "info"


class ConflictType(str, Enum):
    # Original 8 rules
    competing_hypothesis       = "competing_hypothesis"
    negation                   = "negation"
    evidence_mismatch          = "evidence_mismatch"
    timeline_gap               = "timeline_gap"
    therapy_without_indication = "therapy_without_indication"
    stale_hypothesis           = "stale_hypothesis"
    contradictory_values       = "contradictory_values"
    temporal_inconsistency     = "temporal_inconsistency"
    # Epistemic-time rules (Rules 9–10)
    stale_lab_evidence         = "stale_lab_evidence"  # old lab result still driving hypothesis
    time_paradox               = "time_paradox"        # assertion_time before event_time


class Conflict(BaseModel):
    id:                  str
    type:                ConflictType
    severity:            ConflictSeverity
    message:             str
    affected_claim_ids:  list[str]


# ── API ───────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str
    content: str


class ChatRequest(BaseModel):
    message:    str
    session_id: str
    history:    list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply:      str
    claims:     list[Claim]
    session_id: str
    reasoning:  Optional[ReasoningResult] = None
    conflicts:  list[Conflict]            = []


class NodeUpdate(BaseModel):
    text:                   Optional[str]         = None
    evidence_support_score: Optional[float]       = None
    claim_type:             Optional[ClaimType]   = None
    status:                 Optional[ClaimStatus] = None
    trend:                  Optional[ClaimTrend]  = None
    time_offset:            Optional[str]         = None
    source_ref:             Optional[str]         = None
    notes:                  Optional[str]         = None
    # Epistemic fields patchable by clinician
    uncertainty_flag:       Optional[bool]        = None
    supersedes_claim_id:    Optional[str]         = None
    valid_until:            Optional[datetime]    = None
    evidence_tier:          Optional[str]         = None

    @field_validator('evidence_support_score', mode='before')
    @classmethod
    def clamp_ess(cls, v: float | None) -> float | None:
        return _clamp_ess(v)

    @field_validator('time_offset', mode='before')
    @classmethod
    def normalize_offset(cls, v: str | None) -> str | None:
        return _normalize_time_offset(v)


class GraphData(BaseModel):
    nodes: list[dict]
    edges: list[dict]


# ── Intake Layer ──────────────────────────────────────────────────────────────

class IntakeConversationRequest(BaseModel):
    """Patient or caregiver free-text conversation → Claims (patient_generated tier)."""
    text:        str
    session_id:  str
    source_type: str = "patient_report"   # patient_report | caregiver_report
    source_ref:  str = ""                  # e.g. "Erstgespräch 2024-03-21"


class IntakeConversationResponse(BaseModel):
    claims:     list[Claim]
    session_id: str


class IntakeMeasurementsRequest(BaseModel):
    """Wearable / home-device measurements + optional PatientObservations → Claims + Trends."""
    measurements: list[PatientGeneratedMeasurement]
    observations: list[PatientObservation]          = []
    session_id:   str


class IntakeMeasurementsResponse(BaseModel):
    claims:        list[Claim]
    trend_signals: list[TrendSignal]
    session_id:    str


class ClinicalInputType(str, Enum):
    lab        = "lab"        # → source_type=lab_system,   evidence_tier=lab_confirmed
    medication = "medication" # → source_type=clinician,    evidence_tier=clinician_observed
    document   = "document"   # → source_type=imported_document, tier=clinician_observed
    vitals     = "vitals"     # → source_type=clinician,    evidence_tier=clinician_observed


class ClinicalInput(BaseModel):
    text:        str
    input_type:  ClinicalInputType
    source_ref:  str               = ""       # e.g. "Synlab-Befund 2024-03-21"
    event_time:  Optional[datetime] = None


class IntakeClinicalRequest(BaseModel):
    """Structured clinical data (lab, medication, document, vitals) → Claims."""
    inputs:     list[ClinicalInput]
    session_id: str


class IntakeClinicalResponse(BaseModel):
    claims:     list[Claim]
    session_id: str


# ── Audit Layer ───────────────────────────────────────────────────────────────

class AuditEventType(str, Enum):
    claim_created    = "claim_created"
    claim_updated    = "claim_updated"
    claim_deleted    = "claim_deleted"
    claim_superseded = "claim_superseded"


class AuditActor(str, Enum):
    """Which layer / endpoint triggered the mutation."""
    chat                = "chat"
    intake_conversation = "intake_conversation"
    intake_measurements = "intake_measurements"
    intake_clinical     = "intake_clinical"
    graph_manual        = "graph_manual"   # clinician edits via graph router
    system              = "system"


class AuditEvent(BaseModel):
    id:             str
    event_type:     AuditEventType
    claim_id:       str
    session_id:     str
    actor:          str          # AuditActor value
    pipeline_stage: str          # human-readable: "Stage 1: LLM extraction", "Manual edit", …
    timestamp:      datetime
    before:         Optional[dict] = None   # claim state before mutation (None for create)
    after:          Optional[dict] = None   # claim state after mutation  (None for delete)
    meta:           dict          = {}      # extra context, e.g. {input_type: "lab"}


class AuditTrailResponse(BaseModel):
    claim_id:  Optional[str] = None
    session_id: Optional[str] = None
    events:    list[AuditEvent]


# ── Clinical Orchestrator ─────────────────────────────────────────────────────

class OrchestratorScoreBreakdown(BaseModel):
    """Per-factor contribution to the orchestrated_score (all values in [0,1])."""
    evidence:  float   # base evidence weight × WEIGHT_EVIDENCE
    guideline: float   # guideline compliance × WEIGHT_GUIDELINE
    composite: float   # composite score normalised × WEIGHT_COMPOSITE
    temporal:  float   # freshness × WEIGHT_TEMPORAL
    conflict:  float   # penalty (negative) from conflict load


class OrchestratorAlternative(BaseModel):
    text:                        str
    score:                       float
    composite_score_contribution: float


class OrchestratorState(BaseModel):
    """
    Single authoritative clinical state produced by the orchestrator.
    Merges evidence, guideline, composite scores, temporal decay, and conflicts
    into one transparent output with a German verdict and concrete next action.
    """
    session_id:         str
    leading_hypothesis: Optional[str]
    orchestrated_score: float                    # weighted combined score [0,1]
    status:             str                      # "confident" | "undecided" | "contested" | "insufficient"
    why:                str                      # German 2-4 sentence verdict
    key_conflicts:      list[str]                # top 3 conflict messages
    missing_critical:   list[str]                # top 3 missing tests/criteria
    next_action:        str                      # single most important next step
    score_breakdown:    OrchestratorScoreBreakdown
    alternatives:       list[OrchestratorAlternative]
    state_transition:   Optional[str] = None  # e.g. "undecided → contested"; None when unchanged
    generated_at:       str


# ── Priority Explanation ──────────────────────────────────────────────────────

class PriorityFactor(BaseModel):
    """One contributing factor to the leading hypothesis score."""
    name:         str    # e.g. "evidence", "guideline", "composite_scores", "conflicts", "evidence_gap"
    label:        str    # German human-readable label
    contribution: float  # positive = supporting, negative = detractor
    direction:    str    # "supporting" | "detractor" | "neutral"
    explanation:  str    # 1-sentence German explanation


class PriorityExplanation(BaseModel):
    """
    Structured explanation of WHY the current leading hypothesis is ranked first.
    Merges evidence score, guideline compliance, composite score boost,
    conflict load, and evidence gaps into a single traceable breakdown.
    """
    session_id:        str
    hypothesis_text:   Optional[str]
    final_score:       float
    factors:           list[PriorityFactor]
    confidence_status: str   # "confident" | "insufficient"
    verdict:           str   # concise German summary sentence
    generated_at:      str


# ── Clinical Reports (Arztbrief, Entlassbrief, Konsilbrief, Befundbericht) ────

class ReportSectionDef(BaseModel):
    key:      str
    title:    str
    required: bool


class ReportTypeDef(BaseModel):
    key:         str
    title:       str
    description: str
    sections:    list[ReportSectionDef]


class ReportSection(BaseModel):
    key:   str
    title: str
    text:  str   # LLM-generated narrative prose


class GenerateReportRequest(BaseModel):
    report_type:     str                    # "arztbrief" | "entlassbrief" | "konsilbrief" | "befundbericht"
    patient_context: Optional[dict] = None  # e.g. {"name": "Max M.", "geburtsdatum": "1958-04-12"}


class ClinicalReport(BaseModel):
    session_id:   str
    report_type:  str
    title:        str
    sections:     list[ReportSection]
    generated_at: str


# ── Role-Based Clinical Views ──────────────────────────────────────────────────

class RoleAlert(BaseModel):
    level:   str   # "critical" | "warning" | "info"
    message: str
    context: str = ""


class RoleViewSection(BaseModel):
    section: str
    items:   list[dict]


class ClinicalRoleView(BaseModel):
    session_id:   str
    role:         str                    # nurse | resident | specialist | lab | chief
    specialty:    Optional[str] = None
    alerts:       list[RoleAlert]        # critical first
    sections:     list[RoleViewSection]
    generated_at: str


# ── Risk Score Response ────────────────────────────────────────────────────────

class RiskScoreItem(BaseModel):
    name:             str
    score:            float
    interpretation:   str              # "low" | "intermediate" | "high"
    criteria_met:     list[str]        # criteria that fired (with point values)
    criteria_missing: list[str]        # criteria that couldn't be determined
    relevant:         bool             # applies to current active hypotheses
    recommendation:   str = ""         # clinical action guidance


class RiskScoreResponse(BaseModel):
    session_id:   str
    scores:       list[RiskScoreItem]  # sorted: relevant+high-risk first
    generated_at: str


# ── Claim Contribution Analysis ───────────────────────────────────────────────

class ClaimContribution(BaseModel):
    """Per-claim contribution to a hypothesis score."""
    claim_id:          str
    claim_text:        str
    claim_type:        str
    source_type:       str
    evidence_tier:     Optional[str]   = None
    spl_emission_rule: Optional[str]   = None   # "E1"|"E2"|"E3"|"E4" — epistemic quality
    direction:         str             # "supporting" | "conflicting"
    contribution:      float           # magnitude (always ≥ 0); direction carries sign
    ess:               float           # evidence_support_score of this claim
    overlap_weight:    float           # term-overlap weight (0.0 for conflicting)
    source_weight:     float           # epistemic authority multiplier
    temporal_weight:   float           # [0.25, 1.0] decay factor
    trend_boosted:     bool = False    # True if this is a trend signal with keyword boost


class GuidelineEvaluation(BaseModel):
    label:               str
    rule_found:          bool
    eligible:            bool
    required_present:    list[str]
    required_missing:    list[str]
    supporting_present:  list[str]
    conflicting_present: list[str]
    missing_priority:    list[str]


class HypothesisExplanation(BaseModel):
    hypothesis_id:    str
    hypothesis_text:  str
    claim_type:       str
    rule_based_score: float
    total_support:    float
    total_conflict:   float
    contributions:    list[ClaimContribution]   # sorted: supporting desc, conflicting desc
    guideline:        GuidelineEvaluation


class ReasoningExplanation(BaseModel):
    session_id:   str
    hypotheses:   list[HypothesisExplanation]   # sorted by rule_based_score desc
    generated_at: str


# ── MED Engine (Minimal Evidence to Decision) ─────────────────────────────────

class MEDOutcome(BaseModel):
    """One simulated outcome for a candidate test."""
    label:              str           # e.g. "elevated (>0.5 µg/mL)"
    synthetic_text:     str           # text of the simulated claim
    score_delta:        float         # change in leading hypothesis score (signed)
    leading_after:      str           # leading hypothesis after this outcome
    leading_score_after: float
    hypothesis_flipped: bool          # True if leading hypothesis changes


class MEDTestResult(BaseModel):
    """Simulated impact of one candidate test on the current differential."""
    test:                  str
    category:              str        # "lab" | "imaging" | "ecg" | "clinical"
    impact_score:          float      # 0.0–1.0 information gain
    rationale:             str        # clinical explanation
    differentiates_between: list[str] # which hypotheses this separates
    outcomes:              list[MEDOutcome]
    already_evidenced:     bool       # True if this test is already in the graph


class MEDResult(BaseModel):
    """Full MED analysis for a session."""
    session_id:          str
    current_leading:     str
    current_score:       float
    minimal_decision_set: list[MEDTestResult]   # sorted by impact_score desc
