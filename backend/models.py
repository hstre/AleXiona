from __future__ import annotations
import re
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator

_TIME_RE = re.compile(r'^(?:t\+)?(\d+(?:\.\d+)?)h?$', re.IGNORECASE)


def _clamp_ess(v: float | None) -> float | None:
    if v is None:
        return v
    return max(0.0, min(1.0, v))


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
    clinician          = "clinician"
    llm                = "llm"
    guideline          = "guideline"
    imaging_model      = "imaging_model"
    lab_system         = "lab_system"
    imported_document  = "imported_document"


class ClaimStatus(str, Enum):
    active     = "active"
    resolved   = "resolved"
    superseded = "superseded"


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
    text:                  str
    entities:              list[str]            = []
    relations:             list[Relation]       = []
    evidence_support_score: float              = 0.8
    claim_type:            ClaimType           = ClaimType.finding
    source_type:           SourceType          = SourceType.llm
    source_ref:            str                 = ""
    derived_from:          list[str]           = []   # claim IDs
    status:                ClaimStatus         = ClaimStatus.active
    time_offset:           Optional[str]       = None  # e.g. "t+6h"
    trend:                 ClaimTrend          = ClaimTrend.unknown


class ClaimExtractionResult(BaseModel):
    claims: list[Claim]


# ── Analysis / Reasoning ────────────────────────────────────────────────────

class Alternative(BaseModel):
    label:                  str
    evidence_support_score: float
    supporting_claim_ids:   list[str] = []


class MissingEvidence(BaseModel):
    description:  str
    needed_for:   str        # which hypothesis it would clarify
    test_or_type: str        # e.g. "D-Dimer", "CT-Angiographie"


class CounterfactualShift(BaseModel):
    hypothesis:    str
    score_before:  float
    score_after:   float


class CounterfactualResult(BaseModel):
    excluded_claim_text: str
    changed_evidence:    list[str]
    shifts:              list[CounterfactualShift]
    reasoning_trace:     str


class ReasoningResult(BaseModel):
    leading_hypothesis:       str
    supporting_evidence:      list[str]
    conflicting_evidence:     list[str]
    evidence_support_score:   float
    alternatives:             list[Alternative]
    missing_evidence:         list[MissingEvidence]
    focus_points:             list[str]


# ── Conflicts ────────────────────────────────────────────────────────────────

class ConflictSeverity(str, Enum):
    error   = "error"
    warning = "warning"
    info    = "info"


class ConflictType(str, Enum):
    competing_hypothesis      = "competing_hypothesis"
    negation                  = "negation"
    evidence_mismatch         = "evidence_mismatch"
    timeline_gap              = "timeline_gap"
    therapy_without_indication = "therapy_without_indication"
    stale_hypothesis          = "stale_hypothesis"
    contradictory_values      = "contradictory_values"
    temporal_inconsistency    = "temporal_inconsistency"


class Conflict(BaseModel):
    id:                  str
    type:                ConflictType
    severity:            ConflictSeverity
    message:             str
    affected_claim_ids:  list[str]


# ── API ─────────────────────────────────────────────────────────────────────

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
