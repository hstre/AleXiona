import os
import json
import structlog
import time
from typing import AsyncIterator
from pydantic import ValidationError
from datetime import datetime, timezone
from llm_config import sync_client as client, async_client, MODEL
from clinical_spl import run_spl_pipeline, run_dual_spl_pipeline
from models import (
    Claim, ClaimExtractionResult, ChatMessage,
    ReasoningResult, Alternative, MissingEvidence,
    CounterfactualResult, CounterfactualShift,
    HypothesisCounterfactualResult,
    Relation, ClaimType, SourceType, ClaimStatus, ClaimTrend,
    ExtractedObservation, ClaimCandidate,
)
from reasoning_engine import build_reasoning_context, evaluate_all_guidelines
from lab_parser import parse_lab_value

log = structlog.get_logger(__name__)

# Client and model resolved from llm_config (provider selected via LLM_PROVIDER env var).

# ── Claim Extraction ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a clinical knowledge extraction engine.
Analyze the input and extract structured claims from the text.

For each claim extract:
- text: the claim as a clear, concise statement
- entities: key medical concepts, objects, people, findings
- relations: directed relationships between entities
- evidence_support_score: 0.0–1.0 (how strongly the input text supports this claim — NOT a diagnostic probability)
- claim_type: one of symptom | finding | lab | imaging | hypothesis | diagnosis | therapy | risk_factor | guideline
- source_type: one of the following (choose the most specific):
    Clinical sources: clinician | llm | guideline | imaging_model | lab_system | imported_document
    Patient-generated sources (lower epistemic weight — these feed a separate normalization layer):
      patient_report   — patient verbal/written self-report or anamnesis
      wearable         — smartwatch, fitness tracker, CGM reading
      home_device      — home BP cuff, pulse oximeter, thermometer
      caregiver_report — information from family member or informal carer
- source_ref: document, device name, or test name if mentioned, else ""
- evidence_tier: one of patient_generated | clinician_observed | instrument_measured | lab_confirmed | guideline_structured
    Derive from source_type if not explicit:
      patient_report / wearable / home_device / caregiver_report → patient_generated
      clinician / llm / imported_document → clinician_observed
      imaging_model → instrument_measured
      lab_system → lab_confirmed
      guideline → guideline_structured
- status: one of observed | inferred | active | resolved | superseded
  Use "observed" for directly measured/witnessed findings (vitals, lab results, exam findings).
  Use "inferred" for conclusions drawn from other findings (suspected diagnosis, likely cause).
  Use "active" when the distinction is unclear.
  NOTE: patient-generated claims must NOT use status "confirmed" — use "observed" or "inferred".
- time_offset: string like "t+0h", "t+6h", "t+24h" if relative time mentioned, else null
- event_time: ISO 8601 datetime string if an absolute time is mentioned ("at 14:20", "yesterday at noon"), else null.
  Use today's date as reference if needed.
- trend: one of improving | worsening | stable | unknown
- uncertainty_flag: true if the text expresses uncertainty ("possibly", "suspected", "cannot exclude", "rule out"), else false
- assumptions: list of stated assumptions (e.g. ["patient fasted", "no recent anticoagulation"]) — empty list if none

Relation types: causes, is, belongs_to, enables, reduces, produces, contains,
requires, supports, indicates, contradicts, rules_out

Respond ONLY with valid JSON:
{
  "claims": [
    {
      "text": "string",
      "entities": ["string"],
      "relations": [{"from_entity": "string", "to_entity": "string", "type": "string"}],
      "evidence_support_score": 0.85,
      "claim_type": "finding",
      "source_type": "clinician",
      "source_ref": "",
      "evidence_tier": "clinician_observed",
      "status": "observed",
      "time_offset": null,
      "event_time": null,
      "trend": "unknown",
      "uncertainty_flag": false,
      "assumptions": []
    }
  ]
}

Extract 1–6 meaningful claims. Use the input language."""


# ── Clinical Reasoning Analysis ───────────────────────────────────────────────

REASONING_PROMPT = """You are a clinical reasoning assistant (NOT a diagnosing physician).
Given a set of extracted claims from a knowledge graph — enriched with rule-based hypothesis scores
as anchor points — produce a structured reasoning summary.

IMPORTANT:
- Do NOT make autonomous diagnostic decisions
- Use language like "leading hypothesis", "supporting evidence", "conflicting evidence"
- The rule_score values are ANCHORS — refine them using clinical context, do not blindly copy
- Express evidence_support_score (0.0–1.0) as evidence strength, NOT diagnostic probability
- Missing evidence must specify WHICH hypotheses it would differentiate between

Respond ONLY with valid JSON:
{
  "leading_hypothesis": "string - most evidence-supported current hypothesis",
  "supporting_evidence": ["string - specific claim that supports"],
  "conflicting_evidence": ["string - specific claim that conflicts"],
  "evidence_support_score": 0.72,
  "alternatives": [
    {
      "label": "string",
      "evidence_support_score": 0.18,
      "supporting_claim_ids": []
    }
  ],
  "missing_evidence": [
    {
      "description": "string - what is missing and why it matters",
      "needed_for": "string - which hypothesis this would clarify",
      "test_or_type": "string - e.g. D-Dimer, CT-Angiographie, Troponin",
      "differentiates_between": ["string - hypothesis A", "string - hypothesis B"]
    }
  ],
  "focus_points": ["string - key area to investigate or act on"]
}

Max 2 alternatives, 3 missing evidence items, 2 focus points.
Respond in the same language as the input claims."""


QUERY_PROMPT = """You are AleXiona, a clinical reasoning assistant.
You have access to a structured knowledge graph built from clinical notes.
Answer questions by referencing specific claims from the context.
Use cautious, evidence-grounded language. Never claim certainty about diagnoses.
Respond in the same language the user is writing in."""


# ── Counterfactual ────────────────────────────────────────────────────────────

COUNTERFACTUAL_PROMPT = """You are a clinical reasoning assistant.
You are given:
1. The original reasoning with a full set of claims
2. A modified set of claims (with one piece of evidence excluded)

Analyze what changes in the clinical reasoning when that evidence is excluded.

Respond ONLY with valid JSON:
{
  "changed_evidence": ["string - what evidence changed and how"],
  "shifts": [
    {"hypothesis": "string", "score_before": 0.72, "score_after": 0.55}
  ],
  "reasoning_trace": "string - explanation of why the change occurred"
}
Respond in the same language as the input claims."""


# ── Retry helper ──────────────────────────────────────────────────────────────

def _llm_json(
    messages: list[dict],
    temperature: float = 0.1,
    max_retries: int = 2,
    validate_fn=None,
) -> dict:
    """Call OpenAI with JSON mode, retrying on parse OR schema validation errors.

    Args:
        validate_fn: Optional callable that receives the parsed dict and raises
                     ValidationError (or any Exception) if the schema is wrong.
    """
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=45.0,
            )
            data = json.loads(response.choices[0].message.content)
            if validate_fn is not None:
                validate_fn(data)   # raises ValidationError on schema mismatch
            return data
        except (json.JSONDecodeError, KeyError, ValidationError) as e:
            last_err = e
            if attempt < max_retries:
                log.warning(
                    "LLM JSON attempt %d/%d failed (%s: %s), retrying…",
                    attempt + 1, max_retries + 1, type(e).__name__, e,
                )
                time.sleep(0.5 * (attempt + 1))
        except Exception:
            # Non-parsing errors (network, rate limit, etc.) propagate immediately
            raise
    log.error("LLM JSON call failed after %d attempts: %s", max_retries + 1, last_err)
    return {}


# ── Functions ─────────────────────────────────────────────────────────────────

def _validate_extraction_schema(data: dict) -> None:
    """Raise ValidationError if data doesn't match ClaimExtractionResult schema."""
    ClaimExtractionResult.model_validate(data)


def _normalize_candidate(raw: dict) -> dict:
    """Stage 2 of the extraction pipeline: enrich a raw LLM claim dict.

    - Parses lab values quantitatively via lab_parser
    - Sets normalized_token from lab_parser canonical token
    - Stamps assertion_time = now (UTC) if not provided
    - Passes through uncertainty_flag and assumptions from LLM output

    Returns the enriched dict ready to be validated into a Claim.
    """
    enriched = dict(raw)

    # Stamp assertion_time at ingestion time (when the claim enters the graph)
    if not enriched.get("assertion_time"):
        enriched["assertion_time"] = datetime.now(timezone.utc).isoformat()

    # Quantitative lab enrichment (Stage 2 normalization)
    lab = parse_lab_value(enriched.get("text", ""))
    if lab:
        enriched["normalized_token"] = lab.token
        # Only set uncertainty_flag from lab if not already set by LLM
        if not enriched.get("uncertainty_flag"):
            enriched["uncertainty_flag"] = False

    return enriched


def extract_claims(text: str) -> ClaimExtractionResult:
    """Extract structured claims from free text via the 5-stage pipeline.

    Stage 1: LLM extracts raw observations with temporal/negation/uncertainty hints.
    Stage 2: _normalize_candidate enriches with lab parsing, assertion_time stamp.
    Stage 3: Pydantic Claim validation (type checking, field constraints).
    Stage 4: SPL emission — E0 violations dropped, E3 ambiguous claims flagged.
    Stage 5: Persisted to Neo4j by the calling router (outside this function).
    """
    data = _llm_json(
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
        validate_fn=_validate_extraction_schema,
    )
    if not data:
        return ClaimExtractionResult(claims=[])

    claims = []
    for c in data.get("claims", []):
        try:
            enriched = _normalize_candidate(c)   # Stage 2
            relations = [
                Relation(from_entity=r["from_entity"], to_entity=r["to_entity"], type=r["type"])
                for r in enriched.get("relations", [])
            ]
            ess = float(enriched.get("evidence_support_score", 0.8))
            claims.append(Claim(               # Stage 3 — Pydantic validation
                text=enriched["text"],
                entities=enriched.get("entities", []),
                relations=relations,
                evidence_support_score=ess,
                claim_type=enriched.get("claim_type", "finding"),
                source_type=enriched.get("source_type", "llm"),
                source_ref=enriched.get("source_ref", ""),
                status=enriched.get("status", "active"),
                time_offset=enriched.get("time_offset"),
                event_time=enriched.get("event_time"),
                assertion_time=enriched.get("assertion_time"),
                trend=enriched.get("trend", "unknown"),
                uncertainty_flag=bool(enriched.get("uncertainty_flag", False)),
                assumptions=enriched.get("assumptions", []),
                normalized_token=enriched.get("normalized_token"),
                evidence_tier=enriched.get("evidence_tier"),
                projection_confidence=ess,
                projection_method="llm_extraction",
            ))
        except (ValidationError, KeyError, TypeError) as e:
            log.warning("Skipping malformed claim from LLM: %s — %s", c, e)

    claims = _apply_spl_to_claims(claims)   # Stage 4 — mandatory SPL emission
    return ClaimExtractionResult(claims=claims)


def _apply_spl_to_claims(claims: list[Claim]) -> list[Claim]:
    """
    Apply the SPL emission stage to a list of already-extracted claims.

    This is the mandatory epistemic filter for all LLM-extracted claims:
      - E0 (structural violation): claim is dropped entirely
      - E3 (ambiguous, ESS < 0.62): uncertainty_flag=True, status→tentative
      - E1/E2: spl_* provenance fields set; claim passes

    Manual (clinician) claims are exempt — they carry spl_emission_rule="MANUAL"
    and bypass this function entirely (handled in the graph router).
    """
    result: list[Claim] = []
    for c in claims:
        try:
            spl = run_spl_pipeline(c)
        except Exception as exc:
            # Pipeline error → treat as E3 rather than silently accepting or dropping
            log.warning("SPL pipeline error for '%s…': %s — E3 fallback", c.text[:60], exc)
            result.append(c.model_copy(update={
                "spl_emission_rule": "E3",
                "uncertainty_flag":  True,
            }))
            continue

        if spl.blocked:
            log.debug("SPL E0 blocked claim: %s", c.text[:60])
            continue   # structural violation — discard

        updates: dict = {
            "spl_emission_rule": spl.emission_rule,
            "spl_h_norm":        spl.h_norm,
            "spl_unit_id":       spl.unit_id,
            "spl_projection_id": spl.projection_id,
        }
        if spl.force_uncertain:
            updates["uncertainty_flag"] = True
            if c.status in ("active", "inferred"):
                updates["status"] = "tentative"
        result.append(c.model_copy(update=updates))
    return result


def analyze_reasoning(claims: list[dict]) -> ReasoningResult | None:
    if not claims:
        return None
    # Build enriched context with rule-based hypothesis scores as anchors
    context = build_reasoning_context(claims)
    try:
        data = _llm_json(
            messages=[
                {"role": "system", "content": REASONING_PROMPT},
                {"role": "user", "content": f"Clinical knowledge graph:\n{context}"},
            ],
            temperature=0.2,
        )
        if not data:
            return None
        return ReasoningResult(
            leading_hypothesis=data["leading_hypothesis"],
            supporting_evidence=data.get("supporting_evidence", []),
            conflicting_evidence=data.get("conflicting_evidence", []),
            evidence_support_score=float(data["evidence_support_score"]),
            alternatives=[
                Alternative(
                    label=a["label"],
                    evidence_support_score=float(a["evidence_support_score"]),
                    supporting_claim_ids=a.get("supporting_claim_ids", []),
                )
                for a in data.get("alternatives", [])
            ],
            missing_evidence=[
                MissingEvidence(
                    description=m["description"],
                    needed_for=m["needed_for"],
                    test_or_type=m["test_or_type"],
                    differentiates_between=m.get("differentiates_between", []),
                )
                for m in data.get("missing_evidence", [])
            ],
            focus_points=data.get("focus_points", []),
        )
    except Exception:
        return None


def run_counterfactual(
    all_claims: list[dict],
    original_reasoning: ReasoningResult,
    excluded_claim_id: str,
) -> CounterfactualResult | None:
    excluded = next((c for c in all_claims if c["id"] == excluded_claim_id), None)
    if not excluded:
        return None

    remaining = [c for c in all_claims if c["id"] != excluded_claim_id]
    remaining_text = "\n".join(
        f"- [{c.get('claim_type', 'finding').upper()}] {c['text']}"
        for c in remaining
    )

    # Compute guideline-layer shift before and after exclusion
    guideline_before = evaluate_all_guidelines(all_claims)
    guideline_after  = evaluate_all_guidelines(remaining)
    guideline_shift  = {
        hyp: {"before": guideline_before.get(hyp, {}), "after": guideline_after.get(hyp, {})}
        for hyp in set(guideline_before) | set(guideline_after)
    }

    try:
        data = _llm_json(
            messages=[
                {"role": "system", "content": COUNTERFACTUAL_PROMPT},
                {"role": "user", "content": (
                    f"Original leading hypothesis: {original_reasoning.leading_hypothesis} "
                    f"(score: {original_reasoning.evidence_support_score:.2f})\n\n"
                    f"Excluded claim: {excluded['text']}\n\n"
                    f"Remaining claims:\n{remaining_text}"
                )},
            ],
            temperature=0.2,
        )
        if not data:
            return None
        return CounterfactualResult(
            excluded_claim_text=excluded["text"],
            changed_evidence=data.get("changed_evidence", []),
            shifts=[CounterfactualShift(**s) for s in data.get("shifts", [])],
            reasoning_trace=data.get("reasoning_trace", ""),
            guideline_shift=guideline_shift,
        )
    except Exception:
        return None


HYPOTHESIS_COUNTERFACTUAL_PROMPT = """You are a clinical reasoning assistant (NOT a diagnosing physician).

You will be given:
1. A specific clinical hypothesis/diagnosis
2. All available claims from the clinical knowledge graph

Your task: Analyze what would need to change in the evidence for this hypothesis to be WRONG.

Think critically:
- Which current findings are the decisive pillars that make this hypothesis plausible?
- What specific changes (reversal, absence, or new contradicting findings) would be needed?
- If this hypothesis were false, which alternative would become most likely?

Respond ONLY with valid JSON:
{
  "required_changes": [
    "string - specific finding/value that would need to be different, e.g. 'D-Dimer would need to be < 0.5 µg/mL (currently 4.8)' or 'CT-PA would need to show no filling defect'"
  ],
  "critical_evidence": [
    "string - the most decisive supporting claim text (verbatim or paraphrased)"
  ],
  "alternative_if_false": "string - which diagnosis/hypothesis would become most likely if this were excluded",
  "reasoning_trace": "string - 2-3 sentence clinical explanation of the reasoning"
}

Max 4 required_changes, 3 critical_evidence items.
Be specific and quantitative where possible (include actual values).
Respond in the same language as the input claims."""


def run_hypothesis_counterfactual(
    hypothesis_label: str,
    all_claims: list[dict],
) -> HypothesisCounterfactualResult | None:
    """Ask: 'What would need to change for hypothesis H to be false?'"""
    if not all_claims:
        return None
    context = build_reasoning_context(all_claims)
    try:
        data = _llm_json(
            messages=[
                {"role": "system", "content": HYPOTHESIS_COUNTERFACTUAL_PROMPT},
                {"role": "user", "content": (
                    f"Hypothesis under analysis: \"{hypothesis_label}\"\n\n"
                    f"Clinical knowledge graph:\n{context}"
                )},
            ],
            temperature=0.2,
        )
        if not data:
            return None
        return HypothesisCounterfactualResult(
            hypothesis=hypothesis_label,
            required_changes=data.get("required_changes", []),
            critical_evidence=data.get("critical_evidence", []),
            alternative_if_false=data.get("alternative_if_false", ""),
            reasoning_trace=data.get("reasoning_trace", ""),
        )
    except Exception:
        return None


CONFLICT_EXPLAIN_PROMPT = """You are AleXiona, a clinical reasoning assistant (NOT a diagnosing physician).
A conflict detection rule has flagged a potential inconsistency in the clinical evidence graph.

Explain in plain clinical language (3-4 sentences):
1. Why this is clinically concerning
2. What the most likely cause of the conflict is
3. One concrete action the clinician should take to resolve it

Use cautious, evidence-grounded language. Do not make autonomous diagnostic decisions.
Respond in the same language as the affected claims."""


def explain_conflict(conflict: dict, claims: list[dict]) -> str:
    """Return a plain-language clinical explanation of a detected conflict."""
    affected_ids = set(conflict.get("affected_claim_ids", []))
    affected_claims = [c for c in claims if c["id"] in affected_ids]
    claims_text = "\n".join(
        f"- [{c['claim_type'].upper()}] {c['text']} (status: {c['status']}, support: {int(c['evidence_support_score']*100)}%)"
        for c in affected_claims
    )
    prompt = (
        f"Conflict type: {conflict['type']}\n"
        f"Severity: {conflict['severity']}\n"
        f"Message: {conflict['message']}\n"
        f"\nAffected claims:\n{claims_text if claims_text else '(none found)'}"
    )
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": CONFLICT_EXPLAIN_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.3,
            max_tokens=280,
            timeout=30.0,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log.warning("explain_conflict failed: %s", e)
        return ""


# ── Source/tier maps for intake endpoints ────────────────────────────────────

_CLINICAL_TYPE_MAP: dict[str, tuple[str, str]] = {
    # input_type → (source_type, evidence_tier)
    "lab":        ("lab_system",        "lab_confirmed"),
    "medication":  ("clinician",         "clinician_observed"),
    "document":   ("imported_document", "clinician_observed"),
    "vitals":     ("clinician",         "clinician_observed"),
}

_PATIENT_SOURCE_TYPES = {"patient_report", "wearable", "home_device", "caregiver_report"}

# ── Intake: patient conversation extraction ───────────────────────────────────

# Beta builder: clinically conservative interpretation used for E4 JSD check.
# Deliberately maps the same surface form to a different claim_type than the
# alpha prompt to surface genuine semantic ambiguity.
_BETA_INTERPRETATION_PROMPT = """\
You are a conservative clinical evidence reviewer.
Given a short patient statement, return the most cautious clinical interpretation.

Rules:
- Prefer "finding" over "symptom" for statements with physical signs
- Prefer "history" over "finding" for past events
- Prefer "risk_factor" over "finding" for chronic conditions
- Use lower evidence_support_score (0.35–0.65) for subjective reports
- Use higher evidence_support_score (0.70–0.90) for directly observed values

Respond ONLY with JSON: {"claim_type": "...", "evidence_support_score": 0.0}
No other fields. No explanation.\
"""


def _extract_beta_interpretation(claim_text: str) -> tuple[str, float]:
    """
    Second-builder (beta) extraction for E4 JSD evaluation.
    Returns (claim_type, ess) using a clinically conservative prompt.
    Falls back to ("finding", 0.50) on any error.
    """
    try:
        data = _llm_json(
            messages=[
                {"role": "system", "content": _BETA_INTERPRETATION_PROMPT},
                {"role": "user",   "content": claim_text},
            ],
            temperature=0.2,
            validate_fn=None,
        )
        if data and "claim_type" in data and "evidence_support_score" in data:
            return (
                str(data["claim_type"]),
                float(max(0.0, min(1.0, data["evidence_support_score"]))),
            )
    except Exception:
        pass
    return ("finding", 0.50)


CONVERSATION_EXTRACTION_PROMPT = """\
You are a clinical knowledge extraction engine processing a patient or caregiver conversation.
All claims extracted here are PATIENT-REPORTED or CAREGIVER-REPORTED — NOT clinically confirmed.

Rules:
- source_type: use only patient_report or caregiver_report
- evidence_tier: always patient_generated
- status: use "observed" for directly stated facts, "inferred" for interpreted symptoms
- claim_type: use symptom (subjective complaints), finding (self-observed), risk_factor, or therapy
  NEVER use "diagnosis" — patients do not diagnose themselves
- uncertainty_flag: true whenever hedging language appears
  ("I think", "maybe", "vielleicht", "ich glaube", "possibly", "not sure")
- negation_hint is expressed by prefixing text with "[negated]"

For each claim extract:
- text, entities, relations, evidence_support_score (0.0–1.0),
  claim_type, source_type, source_ref, evidence_tier, status,
  time_offset (null or "t+Nh"), event_time (ISO 8601 or null),
  trend (improving|worsening|stable|unknown), uncertainty_flag, assumptions

Respond ONLY with valid JSON: { "claims": [ {...}, ... ] }
Extract 1–8 meaningful claims. Use the input language.\
"""


def extract_claims_conversation(
    text: str,
    source_type: str = "patient_report",
    source_ref: str = "",
) -> ClaimExtractionResult:
    """Extract claims from a patient/caregiver conversation.

    Forces evidence_tier=patient_generated on every claim regardless of LLM output.
    Also enforces epistemic safeguards: no 'diagnosis' claim_type, no 'confirmed' status.
    """
    data = _llm_json(
        messages=[
            {"role": "system", "content": CONVERSATION_EXTRACTION_PROMPT},
            {"role": "user",   "content": text},
        ],
        temperature=0.1,
        validate_fn=_validate_extraction_schema,
    )
    if not data:
        return ClaimExtractionResult(claims=[])

    claims: list[Claim] = []
    for c in data.get("claims", []):
        try:
            enriched = _normalize_candidate(c)

            # Override source/tier from API boundary — never trust LLM here
            enriched["source_type"]   = source_type
            enriched["evidence_tier"] = "patient_generated"
            if source_ref:
                enriched["source_ref"] = source_ref

            # Epistemic safeguards: patients cannot diagnose or confirm
            if enriched.get("claim_type") == "diagnosis":
                enriched["claim_type"] = "finding"
            if enriched.get("status") == "confirmed":
                enriched["status"] = "observed"

            relations = [
                Relation(from_entity=r["from_entity"], to_entity=r["to_entity"], type=r["type"])
                for r in enriched.get("relations", [])
            ]
            ess         = float(enriched.get("evidence_support_score", 0.5))
            claim_type  = enriched.get("claim_type", "symptom")
            entities    = enriched.get("entities", [])

            # ── SPL gate: alpha projection ─────────────────────────────────────
            alpha_spl = run_spl_pipeline(
                claim_text=enriched["text"],
                claim_type=claim_type,
                ess=ess,
                source_ref=enriched.get("source_ref", ""),
                subject=entities[0] if entities else "",
                object_=entities[1] if len(entities) > 1 else "",
            )

            # E0 (structural violation) → discard silently
            if alpha_spl.blocked:
                log.info("SPL E0 blocked conversation claim: %r", enriched["text"][:60])
                continue

            # ── E4 dual-builder: triggered when alpha is uncertain ─────────────
            # Run a second conservative LLM interpretation and compare P_r via JSD.
            # E4 fires when both builders are moderately confident but assign
            # different clinical relation types (JSD > tau_4=0.40).
            run_dual = alpha_spl.force_uncertain or bool(enriched.get("uncertainty_flag", False))

            if run_dual:
                beta_claim_type, beta_ess = _extract_beta_interpretation(enriched["text"])
                dual = run_dual_spl_pipeline(
                    claim_text=enriched["text"],
                    alpha_claim_type=claim_type, alpha_ess=ess,
                    beta_claim_type=beta_claim_type, beta_ess=beta_ess,
                    source_ref=enriched.get("source_ref", ""),
                    subject=entities[0] if entities else "",
                    object_=entities[1] if len(entities) > 1 else "",
                )
                if dual.branched:
                    # Both interpretations equally valid — write two tentative claims
                    log.info(
                        "SPL E4 branch: JSD=%.3f  alpha=%s/%.2f  beta=%s/%.2f  text=%r",
                        dual.jsd, claim_type, ess, beta_claim_type, beta_ess,
                        enriched["text"][:60],
                    )
                    _base = dict(
                        text=enriched["text"],
                        entities=entities,
                        relations=relations,
                        source_type=enriched["source_type"],
                        source_ref=enriched.get("source_ref", ""),
                        evidence_tier=enriched["evidence_tier"],
                        status="tentative",
                        time_offset=enriched.get("time_offset"),
                        event_time=enriched.get("event_time"),
                        assertion_time=enriched.get("assertion_time"),
                        trend=enriched.get("trend", "unknown"),
                        uncertainty_flag=True,
                        normalized_token=enriched.get("normalized_token"),
                        projection_method="llm_extraction",
                        spl_unit_id=dual.alpha.unit_id,   # shared — marks them as pair
                        spl_emission_rule="E4",
                    )
                    claims.append(Claim(
                        **_base,
                        claim_type=claim_type,
                        evidence_support_score=ess,
                        projection_confidence=ess,
                        assumptions=list(enriched.get("assumptions", [])) + [
                            f"SPL E4 alpha: type={claim_type} ess={ess:.2f} "
                            f"jsd={dual.jsd:.3f} h_norm={dual.alpha.h_norm:.3f}"
                        ],
                        spl_projection_id=dual.alpha.projection_id,
                        spl_h_norm=round(dual.alpha.h_norm, 4),
                    ))
                    claims.append(Claim(
                        **_base,
                        claim_type=beta_claim_type if beta_claim_type != "diagnosis" else "finding",
                        evidence_support_score=beta_ess,
                        projection_confidence=beta_ess,
                        assumptions=list(enriched.get("assumptions", [])) + [
                            f"SPL E4 beta: type={beta_claim_type} ess={beta_ess:.2f} "
                            f"jsd={dual.jsd:.3f} h_norm={dual.beta.h_norm:.3f}"
                        ],
                        spl_projection_id=dual.beta.projection_id,
                        spl_h_norm=round(dual.beta.h_norm, 4),
                    ))
                    continue  # skip the single-claim path below

                # Not branched → use the dual result's alpha (now re-evaluated)
                alpha_spl = dual.alpha

            # ── Single-claim path (E1, E2, or unresolved E3) ───────────────────
            uncertainty_flag = bool(enriched.get("uncertainty_flag", False)) or alpha_spl.force_uncertain
            status_override  = "tentative" if alpha_spl.force_uncertain else enriched.get("status", "observed")

            assumptions = list(enriched.get("assumptions", []))
            assumptions.append(
                f"SPL: emission_rule={alpha_spl.emission_rule} "
                f"h_norm={alpha_spl.h_norm:.3f} "
                f"relation_score={alpha_spl.relation_score:.3f}"
            )

            claims.append(Claim(
                text=enriched["text"],
                entities=entities,
                relations=relations,
                evidence_support_score=ess,
                claim_type=claim_type,
                source_type=enriched["source_type"],
                source_ref=enriched.get("source_ref", ""),
                evidence_tier=enriched["evidence_tier"],
                status=status_override,
                time_offset=enriched.get("time_offset"),
                event_time=enriched.get("event_time"),
                assertion_time=enriched.get("assertion_time"),
                trend=enriched.get("trend", "unknown"),
                uncertainty_flag=uncertainty_flag,
                assumptions=assumptions,
                normalized_token=enriched.get("normalized_token"),
                projection_confidence=ess,
                projection_method="llm_extraction",
                spl_unit_id=alpha_spl.unit_id,
                spl_projection_id=alpha_spl.projection_id,
                spl_emission_rule=alpha_spl.emission_rule,
                spl_h_norm=round(alpha_spl.h_norm, 4),
            ))
        except (ValidationError, KeyError, TypeError) as e:
            log.warning("Skipping malformed conversation claim: %s — %s", c, e)

    return ClaimExtractionResult(claims=claims)


# ── Intake: clinical data extraction ─────────────────────────────────────────

CLINICAL_EXTRACTION_PROMPT = """\
You are a clinical knowledge extraction engine processing structured clinical data.
The input is a {input_type} record. Extract claims at the appropriate clinical epistemic level.

Source type for all claims: {source_type}
Evidence tier for all claims: {evidence_tier}
Source reference: {source_ref}

Rules:
- status: "observed" for directly documented values; "inferred" for interpretations
- claim_type: lab (numeric results), finding (clinical observations),
  therapy (medication/treatment), diagnosis (confirmed diagnoses from documents),
  risk_factor (comorbidities)
- uncertainty_flag: true if marked as preliminary, suspected, or uncertain in the source
- For lab values: include numeric value and unit in the claim text where present

For each claim extract:
- text, entities, relations, evidence_support_score (0.0–1.0),
  claim_type, source_type, source_ref, evidence_tier, status,
  time_offset (null or "t+Nh"), event_time (ISO 8601 or null),
  trend (improving|worsening|stable|unknown), uncertainty_flag, assumptions

Respond ONLY with valid JSON: {{ "claims": [ {{...}}, ... ] }}
Extract 1–10 meaningful claims. Use the input language.\
"""


def extract_claims_clinical(
    text: str,
    input_type: str,
    source_ref: str = "",
    event_time_hint: str | None = None,
) -> ClaimExtractionResult:
    """Extract claims from a clinical input (lab, medication, document, vitals).

    Forces source_type and evidence_tier from the input_type mapping —
    never derived from LLM output for clinical data.
    """
    source_type, evidence_tier = _CLINICAL_TYPE_MAP.get(
        input_type, ("clinician", "clinician_observed")
    )

    system_prompt = CLINICAL_EXTRACTION_PROMPT.format(
        input_type=input_type,
        source_type=source_type,
        evidence_tier=evidence_tier,
        source_ref=source_ref or input_type,
    )
    user_content = text
    if event_time_hint:
        user_content = f"[Recorded at: {event_time_hint}]\n\n{text}"

    data = _llm_json(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.1,
        validate_fn=_validate_extraction_schema,
    )
    if not data:
        return ClaimExtractionResult(claims=[])

    claims: list[Claim] = []
    for c in data.get("claims", []):
        try:
            enriched = _normalize_candidate(c)

            # Override from API boundary
            enriched["source_type"]   = source_type
            enriched["evidence_tier"] = evidence_tier
            if source_ref:
                enriched["source_ref"] = source_ref

            relations = [
                Relation(from_entity=r["from_entity"], to_entity=r["to_entity"], type=r["type"])
                for r in enriched.get("relations", [])
            ]
            ess        = float(enriched.get("evidence_support_score", 0.8))
            claim_type = enriched.get("claim_type", "finding")
            entities   = enriched.get("entities", [])

            # ── SPL gate (single-builder; no E4 for structured clinical data) ──
            spl = run_spl_pipeline(
                claim_text=enriched["text"],
                claim_type=claim_type,
                ess=ess,
                source_ref=enriched.get("source_ref", ""),
                subject=entities[0] if entities else "",
                object_=entities[1] if len(entities) > 1 else "",
            )

            if spl.blocked:
                log.info("SPL E0 blocked clinical claim: %r", enriched["text"][:60])
                continue

            uncertainty_flag = bool(enriched.get("uncertainty_flag", False)) or spl.force_uncertain
            assumptions = list(enriched.get("assumptions", []))
            assumptions.append(
                f"SPL: emission_rule={spl.emission_rule} "
                f"h_norm={spl.h_norm:.3f} "
                f"relation_score={spl.relation_score:.3f}"
            )

            claims.append(Claim(
                text=enriched["text"],
                entities=entities,
                relations=relations,
                evidence_support_score=ess,
                claim_type=claim_type,
                source_type=enriched["source_type"],
                source_ref=enriched.get("source_ref", ""),
                evidence_tier=enriched["evidence_tier"],
                status=enriched.get("status", "observed"),
                time_offset=enriched.get("time_offset"),
                event_time=enriched.get("event_time"),
                assertion_time=enriched.get("assertion_time"),
                trend=enriched.get("trend", "unknown"),
                uncertainty_flag=uncertainty_flag,
                assumptions=assumptions,
                normalized_token=enriched.get("normalized_token"),
                projection_confidence=ess,
                projection_method="llm_extraction",
                spl_unit_id=spl.unit_id,
                spl_projection_id=spl.projection_id,
                spl_emission_rule=spl.emission_rule,
                spl_h_norm=round(spl.h_norm, 4),
            ))
        except (ValidationError, KeyError, TypeError) as e:
            log.warning("Skipping malformed clinical claim: %s — %s", c, e)

    return ClaimExtractionResult(claims=claims)


def answer_with_context(
    user_message: str,
    history: list[ChatMessage],
    graph_context: str,
) -> str:
    messages = [{"role": "system", "content": QUERY_PROMPT}]
    if graph_context:
        messages.append({
            "role": "system",
            "content": f"Knowledge graph context:\n{graph_context}"
        })
    for msg in history[-6:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model=MODEL, messages=messages, temperature=0.3, timeout=45.0,
    )
    return response.choices[0].message.content


def _build_query_messages(
    user_message: str,
    history: list[ChatMessage],
    graph_context: str,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": QUERY_PROMPT}]
    if graph_context:
        messages.append({
            "role": "system",
            "content": f"Knowledge graph context:\n{graph_context}",
        })
    for msg in history[-6:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})
    return messages


async def stream_answer_with_context(
    user_message: str,
    history: list[ChatMessage],
    graph_context: str,
) -> AsyncIterator[str]:
    """Yield LLM reply tokens one by one via OpenAI streaming."""
    messages = _build_query_messages(user_message, history, graph_context)
    stream = await async_client.chat.completions.create(
        model=MODEL, messages=messages, temperature=0.3, stream=True, timeout=90.0,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield delta


# ── Clinical Report Generation ─────────────────────────────────────────────────

async def generate_report(prompt: str) -> dict[str, str]:
    """
    Call the LLM with a report-generation prompt and return parsed sections.

    Args:
        prompt: Full prompt from report_engine.build_report_prompt().

    Returns:
        Dict mapping section keys to generated prose strings.

    Raises:
        ValueError: LLM returned non-JSON or empty sections.
    """
    resp = await async_client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,        # slightly higher than reasoning — narrative prose
        response_format={"type": "json_object"},
        timeout=60.0,
    )
    raw = resp.choices[0].message.content or "{}"
    try:
        sections: dict = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Report LLM returned invalid JSON: {e}")
    if not isinstance(sections, dict) or not sections:
        raise ValueError("Report LLM returned empty response")
    return {k: str(v) for k, v in sections.items()}
