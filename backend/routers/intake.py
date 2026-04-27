"""Intake Layer — epistemically separated ingestion endpoints.

Three routes, one epistemic contract each:

POST /api/intake/conversation
    Patient or caregiver free text → Claims tagged patient_generated.
    All source_type / evidence_tier overrides are enforced at this boundary,
    not left to the LLM.

POST /api/intake/measurements
    PatientGeneratedMeasurements + optional PatientObservations →
    Claims + TrendSignals.  Pure rule-based path — no LLM involved.

POST /api/intake/clinical
    Structured clinical inputs (lab, medication, document, vitals) →
    Claims at lab_confirmed or clinician_observed tier.
    source_type is mapped from input_type at the boundary.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC

from fastapi import APIRouter, HTTPException

from api_errors import internal_error
from audit_log import log_created_batch
from llm_client import extract_claims_clinical, extract_claims_conversation
from models import (
    AuditActor,
    Claim,
    IntakeClinicalRequest,
    IntakeClinicalResponse,
    IntakeConversationRequest,
    IntakeConversationResponse,
    IntakeMeasurementsRequest,
    IntakeMeasurementsResponse,
    TrendSignal,
)
from neo4j_client import get_db
from patient_data import (
    candidate_to_claim,
    extract_trend_signal,
    ingest_measurement,
    ingest_patient_observation,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/intake", tags=["intake"])
_executor = ThreadPoolExecutor()

# source_type → evidence_tier for measurement ingestion
_MEASUREMENT_TIER: dict[str, str] = {
    "wearable":    "patient_generated",
    "home_device": "patient_generated",
}


# ── POST /api/intake/conversation ─────────────────────────────────────────────

@router.post("/conversation", response_model=IntakeConversationResponse)
async def intake_conversation(request: IntakeConversationRequest):
    """Patient / caregiver free text → Claims (patient_generated tier).

    The LLM extracts structure; source_type and evidence_tier are overridden
    at this boundary to patient_report / caregiver_report.
    Epistemic safeguards: no 'diagnosis' claim_type, no 'confirmed' status.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    db = get_db()
    try:
        extraction = await loop.run_in_executor(
            _executor,
            lambda: extract_claims_conversation(
                request.text,
                source_type=request.source_type,
                source_ref=request.source_ref,
            ),
        )
        if extraction.claims:
            claim_ids = db.store_claims(extraction.claims, request.session_id)
            log_created_batch(
                claim_ids, extraction.claims, request.session_id,
                actor=AuditActor.intake_conversation,
                pipeline_stage="Stage 1–3: LLM extraction + patient_generated override",
                meta={"source_type": request.source_type, "source_ref": request.source_ref},
            )

        return IntakeConversationResponse(
            claims=extraction.claims,
            session_id=request.session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


# ── POST /api/intake/measurements ─────────────────────────────────────────────

@router.post("/measurements", response_model=IntakeMeasurementsResponse)
async def intake_measurements(request: IntakeMeasurementsRequest):
    """Wearable / home-device measurements + PatientObservations → Claims + TrendSignals.

    Purely rule-based — no LLM call.  Each measurement produces a point-in-time
    Claim; series with ≥ 3 points additionally produce a TrendSignal Claim.
    """
    db = get_db()
    try:
        claims: list[Claim] = []
        trend_signals: list[TrendSignal] = []

        # 1. PatientObservations (free-text self-reports alongside device data)
        for obs in request.observations:
            candidate = ingest_patient_observation(obs)
            claim = candidate_to_claim(
                candidate,
                source_type=obs.source_type,
                evidence_tier="patient_generated",
                patient_data_ref=obs.id,
            )
            claims.append(claim)

        # 2. Measurements — point-in-time claims
        for pgm in request.measurements:
            candidate = ingest_measurement(pgm)
            claim = candidate_to_claim(
                candidate,
                source_type=pgm.device_type,   # "wearable" | "home_device"
                evidence_tier=_MEASUREMENT_TIER.get(pgm.device_type, "patient_generated"),
                patient_data_ref=pgm.id,
            )
            claims.append(claim)

        # 3. Trend detection per token
        by_token: dict[str, list] = defaultdict(list)
        for pgm in request.measurements:
            by_token[pgm.token].append(pgm)

        for token_pgms in by_token.values():
            trend = extract_trend_signal(token_pgms)
            if trend is None:
                continue
            trend_signals.append(trend)

            # Trend also becomes a Claim (finding, wearable, patient_generated)
            trend_text = (
                f"{trend.token} {trend.direction} "
                f"{abs(trend.magnitude_pct):.1f}% over {trend.window_hours:.1f}h"
                + (f" [{trend.clinical_flag}]" if trend.clinical_flag else "")
            )
            from datetime import datetime

            from models import ClaimStatus, ClaimTrend, ClaimType
            trend_claim = Claim(
                text=trend_text,
                entities=[trend.token],
                relations=[],
                evidence_support_score=0.65,
                claim_type=ClaimType.finding,
                source_type=token_pgms[0].device_type,
                source_ref=f"trend:{trend.id}",
                evidence_tier="patient_generated",
                status=ClaimStatus.observed,
                trend=(
                    ClaimTrend.worsening if trend.direction in ("rising", "falling")
                    else ClaimTrend.stable
                ),
                normalized_token=trend.token,
                uncertainty_flag=(trend.direction == "volatile"),
                assertion_time=datetime.now(UTC),
            )
            claims.append(trend_claim)

        if claims:
            claim_ids = db.store_claims(claims, request.session_id)
            log_created_batch(
                claim_ids, claims, request.session_id,
                actor=AuditActor.intake_measurements,
                pipeline_stage="Stage 2: Rule-based measurement normalization",
                meta={"n_measurements": len(request.measurements), "n_trends": len(trend_signals)},
            )

        return IntakeMeasurementsResponse(
            claims=claims,
            trend_signals=trend_signals,
            session_id=request.session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)


# ── POST /api/intake/clinical ─────────────────────────────────────────────────

@router.post("/clinical", response_model=IntakeClinicalResponse)
async def intake_clinical(request: IntakeClinicalRequest):
    """Structured clinical inputs (lab, medication, document, vitals) → Claims.

    Each ClinicalInput is processed separately so source_type and evidence_tier
    are mapped per input_type (not mixed in one LLM call).
    lab     → source_type=lab_system,        evidence_tier=lab_confirmed
    medication/vitals → source_type=clinician, evidence_tier=clinician_observed
    document → source_type=imported_document, evidence_tier=clinician_observed
    """
    import asyncio
    loop = asyncio.get_event_loop()
    db = get_db()
    try:
        all_claims: list[Claim] = []

        for clinical_input in request.inputs:
            event_hint = (
                clinical_input.event_time.isoformat()
                if clinical_input.event_time else None
            )
            extraction = await loop.run_in_executor(
                _executor,
                lambda ci=clinical_input, eh=event_hint: extract_claims_clinical(
                    ci.text,
                    input_type=ci.input_type.value,
                    source_ref=ci.source_ref,
                    event_time_hint=eh,
                ),
            )
            all_claims.extend(extraction.claims)

        if all_claims:
            claim_ids = db.store_claims(all_claims, request.session_id)
            input_types = list({ci.input_type.value for ci in request.inputs})
            log_created_batch(
                claim_ids, all_claims, request.session_id,
                actor=AuditActor.intake_clinical,
                pipeline_stage="Stage 1–3: LLM extraction + clinical tier override",
                meta={"input_types": input_types, "n_inputs": len(request.inputs)},
            )

        return IntakeClinicalResponse(
            claims=all_claims,
            session_id=request.session_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise internal_error(e)
