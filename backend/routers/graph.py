from fastapi import APIRouter, HTTPException
from models import GraphData, NodeUpdate, CounterfactualResult, HypothesisCounterfactualResult, Claim, ClaimType, SourceType, ClaimStatus, ClaimTrend, _normalize_time_offset, _parse_offset_hours, AuditActor, MEDResult, ReasoningExplanation, HypothesisExplanation, ClaimContribution, GuidelineEvaluation, RiskScoreResponse, RiskScoreItem, ClinicalRoleView, RoleAlert, RoleViewSection, ClinicalReport, ReportSection, GenerateReportRequest, ReportTypeDef, ReportSectionDef, PriorityExplanation, PriorityFactor, OrchestratorState, OrchestratorScoreBreakdown, OrchestratorAlternative
from clinical_orchestrator import orchestrate
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from neo4j_client import get_db
from llm_client import run_counterfactual, run_hypothesis_counterfactual, analyze_reasoning, explain_conflict as _explain_conflict
from conflict_engine import detect_conflicts
from api_errors import internal_error, validation_error, not_found
from audit_log import log_created_batch, log_updated, log_deleted
from med_engine import compute_med
from reasoning_engine import explain_hypothesis_scores, build_priority_explanation
from composite_scores import compute_all_scores
from role_views import build_role_view
from report_engine import build_report_prompt, REPORT_TYPES
from llm_client import generate_report as _generate_report


class ManualClaimPayload(BaseModel):
    text:                   str = Field(..., min_length=1, max_length=5_000)
    claim_type:             ClaimType   = ClaimType.finding
    source_type:            SourceType  = SourceType.clinician
    source_ref:             str         = ""
    evidence_support_score: float       = 0.8
    time_offset:            Optional[str] = None
    trend:                  ClaimTrend  = ClaimTrend.unknown
    status:                 ClaimStatus = ClaimStatus.active
    derived_from:           list[str]   = []   # explicit claimIds chosen by the user

    @field_validator('evidence_support_score', mode='before')
    @classmethod
    def clamp_ess(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator('time_offset', mode='before')
    @classmethod
    def normalize_offset(cls, v: str | None) -> str | None:
        return _normalize_time_offset(v)


router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.post("/{session_id}/claims")
async def add_manual_claim(session_id: str, payload: ManualClaimPayload):
    db = get_db()
    try:
        if payload.derived_from:
            existing_claims = db.get_all_claims_for_session(session_id)
            existing_by_id  = {c["id"]: c for c in existing_claims}
            unknown = [i for i in payload.derived_from if i not in existing_by_id]
            if unknown:
                raise validation_error(
                    f"Unknown claim IDs in derived_from: {unknown}",
                    code="invalid_derived_from",
                )
            # Temporal consistency: new claim must not be earlier than any source
            child_h = _parse_offset_hours(payload.time_offset)
            if child_h is not None:
                for src_id in payload.derived_from:
                    src_h = _parse_offset_hours(existing_by_id[src_id].get("time_offset"))
                    if src_h is not None and child_h < src_h:
                        raise validation_error(
                            f"time_offset t+{child_h}h is earlier than source claim's "
                            f"t+{src_h}h — a derived claim cannot precede its source.",
                            code="temporal_inconsistency",
                        )
        claim = Claim(
            text=payload.text,
            entities=[], relations=[],
            evidence_support_score=payload.evidence_support_score,
            claim_type=payload.claim_type,
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            status=payload.status,
            time_offset=payload.time_offset,
            trend=payload.trend,
            derived_from=payload.derived_from,
            spl_emission_rule="MANUAL",   # Clinician direct entry — exempt from SPL emission
        )
        new_ids = db.store_claims([claim], session_id)
        if payload.derived_from and new_ids:
            db.link_explicit_derived_from(new_ids[0], payload.derived_from)
        log_created_batch(
            new_ids, [claim], session_id,
            actor=AuditActor.graph_manual,
            pipeline_stage="Manual claim creation via graph router",
        )
        return {"status": "created"}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}", response_model=GraphData)
async def get_graph(session_id: str):
    try:
        return get_db().get_graph(session_id)
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/conflicts")
async def get_conflicts(session_id: str):
    try:
        claims = get_db().get_all_claims_for_session(session_id)
        return detect_conflicts(claims)
    except Exception as e:
        raise internal_error(e)


class HypothesisCounterfactualPayload(BaseModel):
    hypothesis: str


@router.post("/{session_id}/counterfactual/hypothesis", response_model=HypothesisCounterfactualResult)
async def hypothesis_counterfactual(session_id: str, payload: HypothesisCounterfactualPayload):
    """Ask: 'What would need to change for this hypothesis to be false?'"""
    db = get_db()
    try:
        all_claims = db.get_all_claims_for_session(session_id)
        result = run_hypothesis_counterfactual(payload.hypothesis, all_claims)
        if not result:
            raise validation_error("Could not compute hypothesis counterfactual",
                                   code="counterfactual_failed")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.post("/{session_id}/counterfactual/{claim_id}", response_model=CounterfactualResult)
async def counterfactual(session_id: str, claim_id: str):
    db = get_db()
    try:
        all_claims = db.get_all_claims_for_session(session_id)
        original_reasoning = analyze_reasoning(all_claims)
        if not original_reasoning:
            raise validation_error("Insufficient claims for counterfactual analysis",
                                   code="insufficient_claims")
        result = run_counterfactual(all_claims, original_reasoning, claim_id)
        if not result:
            raise not_found("Claim not found in session")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/entity-duplicates")
async def get_entity_duplicates(session_id: str):
    try:
        return get_db().get_entity_groups(session_id)
    except Exception as e:
        raise internal_error(e)


class MergeEntitiesPayload(BaseModel):
    canonical: str
    aliases:   list[str]


@router.post("/{session_id}/entities/merge")
async def merge_entities(session_id: str, payload: MergeEntitiesPayload):
    try:
        merged = get_db().merge_entities(payload.canonical, payload.aliases)
        return {"merged": merged}
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/export")
async def export_session(session_id: str):
    try:
        return get_db().export_session(session_id)
    except Exception as e:
        raise internal_error(e)


class ImportPayload(BaseModel):
    claims: list[dict]


@router.post("/{session_id}/import")
async def import_session(session_id: str, payload: ImportPayload):
    try:
        result = get_db().import_session(session_id, payload.claims)
        return result
    except Exception as e:
        raise internal_error(e)


class ConflictExplainPayload(BaseModel):
    type:                str
    severity:            str
    message:             str
    affected_claim_ids:  list[str] = []


@router.post("/{session_id}/conflicts/explain")
async def explain_conflict(session_id: str, payload: ConflictExplainPayload):
    try:
        claims = get_db().get_all_claims_for_session(session_id)
        explanation = _explain_conflict(payload.model_dump(), claims)
        if not explanation:
            raise validation_error("LLM explanation unavailable", code="llm_unavailable")
        return {"explanation": explanation}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/claims/{claim_id}/chain")
async def get_claim_chain(session_id: str, claim_id: str):
    """Return all claim IDs reachable via DERIVES_FROM edges (ancestors + descendants)."""
    try:
        db = get_db()
        claims = db.get_all_claims_for_session(session_id)
        claim_ids = {c["id"] for c in claims}
        if claim_id not in claim_ids:
            raise not_found("Claim not found in session")
        # Build adjacency from derived_from lists (stored on each claim)
        parents:  dict[str, list[str]] = {}   # claim -> list of sources it derives from
        children: dict[str, list[str]] = {}   # claim -> list of claims that derive from it
        for c in claims:
            cid = c["id"]
            parents.setdefault(cid, [])
            children.setdefault(cid, [])
            for src in c.get("derived_from") or []:
                if src in claim_ids:
                    parents[cid].append(src)
                    children.setdefault(src, []).append(cid)

        visited: set[str] = set()
        queue = [claim_id]
        while queue:
            cur = queue.pop()
            if cur in visited:
                continue
            visited.add(cur)
            queue.extend(parents.get(cur, []))
            queue.extend(children.get(cur, []))

        chain = list(visited - {claim_id})
        return {"claim_id": claim_id, "chain": chain}
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.patch("/claim/{claim_id}")
async def update_claim(claim_id: str, update: NodeUpdate):
    db = get_db()
    try:
        before = db.get_claim_by_id(claim_id)
        session_id = (before or {}).get("session_id", "")
        changes = update.model_dump(exclude_none=True)
        db.update_claim(claim_id, changes, session_id=session_id)
        after = db.get_claim_by_id(claim_id)
        log_updated(
            claim_id, session_id,
            actor=AuditActor.graph_manual,
            before=before,
            after=after,
            meta={"changed_fields": list(changes.keys())},
        )
        return {"status": "updated"}
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/reasoning/explain", response_model=ReasoningExplanation)
async def get_reasoning_explanation(session_id: str):
    """
    Per-claim contribution breakdown for every active hypothesis.

    For each hypothesis returns:
    - contributions: ordered list of claims with direction, magnitude,
      source_weight, temporal_weight, spl_emission_rule, trend_boosted
    - total_support / total_conflict: raw sums before score clamping
    - guideline: required/supporting/missing evidence per guideline rule
    """
    from datetime import datetime, timezone
    db = get_db()
    try:
        claims = db.get_all_claims_for_session(session_id)
        explanations_raw = explain_hypothesis_scores(claims)

        hypotheses = []
        for e in explanations_raw:
            g = e["guideline"]
            hypotheses.append(HypothesisExplanation(
                hypothesis_id=e["id"],
                hypothesis_text=e["text"],
                claim_type=e["claim_type"],
                rule_based_score=e["rule_based_score"],
                total_support=e["total_support"],
                total_conflict=e["total_conflict"],
                contributions=[
                    ClaimContribution(**c) for c in e["contributions"]
                ],
                guideline=GuidelineEvaluation(
                    label=g.get("label", ""),
                    rule_found=g.get("rule_found", False),
                    eligible=g.get("eligible", False),
                    required_present=g.get("required_present", []),
                    required_missing=g.get("required_missing", []),
                    supporting_present=g.get("supporting_present", []),
                    conflicting_present=g.get("conflicting_present", []),
                    missing_priority=g.get("missing_priority", []),
                ),
            ))

        return ReasoningExplanation(
            session_id=session_id,
            hypotheses=hypotheses,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/orchestrate", response_model=OrchestratorState)
async def get_orchestrator_state(session_id: str):
    """
    Return the single authoritative clinical state for this session.

    The Clinical Orchestrator is the central reasoning layer that merges all
    sub-engine signals into ONE output:
      • leading_hypothesis  — who is winning, and why
      • orchestrated_score  — weighted combined score (evidence 40%, guideline 25%,
                              composite scores 15%, temporal freshness 10%, conflicts -10%)
      • status              — confident | undecided | contested | insufficient
      • why                 — German 2-4 sentence verdict
      • key_conflicts       — top 3 conflicts (error-first)
      • missing_critical    — top 3 missing tests or guideline criteria
      • next_action         — single most important concrete next step
      • score_breakdown     — transparent per-factor contributions
      • alternatives        — runner-up hypotheses with their scores

    No LLM call is made — all computation is deterministic and synchronous.
    For the full per-claim breakdown use /reasoning/explain.
    For the priority decomposition use /priority.
    """
    db = get_db()
    try:
        claims = db.get_all_claims_for_session(session_id)
        state  = orchestrate(session_id, claims)
        return OrchestratorState(
            session_id=state["session_id"],
            leading_hypothesis=state["leading_hypothesis"],
            orchestrated_score=state["orchestrated_score"],
            status=state["status"],
            why=state["why"],
            key_conflicts=state["key_conflicts"],
            missing_critical=state["missing_critical"],
            next_action=state["next_action"],
            score_breakdown=OrchestratorScoreBreakdown(**state["score_breakdown"]),
            alternatives=[OrchestratorAlternative(**a) for a in state["alternatives"]],
            state_transition=state.get("state_transition"),
            generated_at=state["generated_at"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/priority", response_model=PriorityExplanation)
async def get_priority_explanation(session_id: str):
    """
    Return the central priority explanation for the current leading hypothesis.

    This is the single authoritative breakdown of WHY a hypothesis is ranked first,
    merging five factors into a transparent score chain:

      1. Evidenzstärke        — rule_based_score from supporting/conflicting claims
      2. Klinische Scores     — bounded composite score boost (max 8 pp)
      3. Leitlinienkonformität — % required guideline criteria fulfilled
      4. Konfliktlast         — penalty from number of conflicting claims
      5. Evidenzlücken        — penalty from missing required guideline criteria

    A German verdict sentence summarizes the result.
    Use GET /api/graph/{session_id}/reasoning/explain for the full per-claim
    contribution breakdown.
    """
    db = get_db()
    try:
        claims = db.get_all_claims_for_session(session_id)
        result = build_priority_explanation(session_id, claims)
        return PriorityExplanation(
            session_id=result["session_id"],
            hypothesis_text=result["hypothesis_text"],
            final_score=result["final_score"],
            factors=[PriorityFactor(**f) for f in result["factors"]],
            confidence_status=result["confidence_status"],
            verdict=result["verdict"],
            generated_at=result["generated_at"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/report-types", response_model=list[ReportTypeDef])
async def list_report_types():
    """Return all supported clinical report types with their section definitions."""
    return [
        ReportTypeDef(
            key=k,
            title=v["title"],
            description=v["description"],
            sections=[ReportSectionDef(**s) for s in v["sections"]],
        )
        for k, v in REPORT_TYPES.items()
    ]


@router.post("/{session_id}/report", response_model=ClinicalReport)
async def create_report(session_id: str, body: GenerateReportRequest):
    """
    Generate a clinical report from the current claim graph.

    Supported report types:
      arztbrief    — Vollständiger Arztbrief (Anamnese, Befund, Diagnostik,
                     Diagnosen, Verlauf, Therapie, Procedere)
      entlassbrief — Kurzarztbrief / Entlassbrief
      konsilbrief  — Konsiliarbrief (Fragestellung, Befund, Diagnosen,
                     Beurteilung, Empfehlung)
      befundbericht — Befundbericht (Material, Befund, Beurteilung)

    The LLM generates structured prose for each section anchored to
    the rule-based hypothesis scores, parsed lab values, and all active claims.
    Optional patient_context (name, DOB, ward, etc.) is woven into the letter.
    """
    from datetime import datetime, timezone
    rt = REPORT_TYPES.get(body.report_type)
    if not rt:
        raise validation_error(
            f"Unknown report type '{body.report_type}'. "
            f"Valid: {', '.join(REPORT_TYPES)}"
        )
    db = get_db()
    try:
        claims  = db.get_all_claims_for_session(session_id)
        prompt  = build_report_prompt(body.report_type, claims, body.patient_context)
        raw     = await _generate_report(prompt)

        sections = []
        for s in rt["sections"]:
            text = raw.get(s["key"], "")
            if not text and s["required"]:
                text = "[nicht dokumentiert]"
            sections.append(ReportSection(key=s["key"], title=s["title"], text=text))

        return ClinicalReport(
            session_id=session_id,
            report_type=body.report_type,
            title=rt["title"],
            sections=sections,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as e:
        raise validation_error(str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/view/{role}", response_model=ClinicalRoleView)
async def get_role_view(
    session_id: str,
    role: str,
    specialty: Optional[str] = None,
):
    """
    Role-filtered clinical view — each role sees exactly what they need.

    Roles (German or English):
      pfleger / nurse          — vitals, trend alerts, monitoring tasks
      assistenzarzt / resident — full differential, risk scores, missing evidence
      facharzt / specialist    — specialty-filtered hypotheses + claim breakdown
      labor / lab              — lab results, abnormal flags, pending tests
      chefarzt / chief         — executive summary, risk flags, decisions pending

    Optional ?specialty= for the specialist role:
      cardiology | pulmonology | infectiology | neurology | nephrology | gastroenterology
    """
    from datetime import datetime, timezone
    db = get_db()
    try:
        claims  = db.get_all_claims_for_session(session_id)
        raw     = build_role_view(role, claims, specialty)
        level_order = {"critical": 0, "warning": 1, "info": 2}
        alerts = sorted(
            [RoleAlert(**a) for a in raw["alerts"]],
            key=lambda a: level_order.get(a.level, 3),
        )
        return ClinicalRoleView(
            session_id=session_id,
            role=raw["role"],
            specialty=specialty,
            alerts=alerts,
            sections=[RoleViewSection(**s) for s in raw["sections"]],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as e:
        raise validation_error(str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/risk-scores", response_model=RiskScoreResponse)
async def get_risk_scores(session_id: str):
    """
    Compute all six validated bedside risk scores from the current claim graph.

    Scores computed: qSOFA, Wells-PE, GRACE-ACS, HEART, PERC, CURB-65.
    Each score includes criteria_met, criteria_missing, interpretation,
    and an evidence-based recommendation. The `relevant` flag indicates
    whether the score applies to the active differential diagnoses.
    Results are sorted: relevant + highest-risk first.
    """
    from datetime import datetime, timezone
    db = get_db()
    try:
        claims = db.get_all_claims_for_session(session_id)
        raw    = compute_all_scores(claims)
        return RiskScoreResponse(
            session_id=session_id,
            scores=[RiskScoreItem(**r) for r in raw],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.get("/{session_id}/med", response_model=MEDResult)
async def get_med(session_id: str):
    """Compute the Minimal Evidence to Decision set for the current session."""
    db = get_db()
    try:
        claims = db.get_all_claims_for_session(session_id)
        result = compute_med(claims, session_id=session_id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


@router.delete("/claim/{claim_id}")
async def delete_claim(claim_id: str):
    db = get_db()
    try:
        before = db.get_claim_by_id(claim_id)
        session_id = (before or {}).get("session_id", "")
        db.delete_claim(claim_id, session_id=session_id)
        log_deleted(
            claim_id, session_id,
            actor=AuditActor.graph_manual,
            before=before,
        )
        return {"status": "deleted"}
    except Exception as e:
        raise internal_error(e)
