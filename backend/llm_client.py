import os
import json
import logging
import time
from typing import AsyncIterator
from openai import OpenAI, AsyncOpenAI
from pydantic import ValidationError
from models import (
    Claim, ClaimExtractionResult, ChatMessage,
    ReasoningResult, Alternative, MissingEvidence,
    CounterfactualResult, CounterfactualShift,
    HypothesisCounterfactualResult,
    Relation, ClaimType, SourceType, ClaimStatus, ClaimTrend,
)
from reasoning_engine import build_reasoning_context, evaluate_all_guidelines

log = logging.getLogger(__name__)

client       = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o"

# ── Claim Extraction ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a clinical knowledge extraction engine.
Analyze the input and extract structured claims from the text.

For each claim extract:
- text: the claim as a clear, concise statement
- entities: key medical concepts, objects, people, findings
- relations: directed relationships between entities
- evidence_support_score: 0.0–1.0 (how strongly the input text supports this claim — this is NOT a diagnostic probability)
- claim_type: one of symptom | finding | lab | imaging | hypothesis | diagnosis | therapy | risk_factor | guideline
- source_type: one of clinician | llm | guideline | imaging_model | lab_system | imported_document
- source_ref: document or test name if mentioned, else ""
- status: one of active | resolved | superseded
- time_offset: string like "t+0h", "t+6h", "t+24h" if time is mentioned, else null
- trend: one of improving | worsening | stable | unknown

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
      "status": "active",
      "time_offset": null,
      "trend": "unknown"
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


def extract_claims(text: str) -> ClaimExtractionResult:
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
            relations = [
                Relation(from_entity=r["from_entity"], to_entity=r["to_entity"], type=r["type"])
                for r in c.get("relations", [])
            ]
            claims.append(Claim(
                text=c["text"],
                entities=c.get("entities", []),
                relations=relations,
                evidence_support_score=float(c.get("evidence_support_score", 0.8)),
                claim_type=c.get("claim_type", "finding"),
                source_type=c.get("source_type", "llm"),
                source_ref=c.get("source_ref", ""),
                status=c.get("status", "active"),
                time_offset=c.get("time_offset"),
                trend=c.get("trend", "unknown"),
            ))
        except (ValidationError, KeyError, TypeError) as e:
            log.warning("Skipping malformed claim from LLM: %s — %s", c, e)

    return ClaimExtractionResult(claims=claims)


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
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        log.warning("explain_conflict failed: %s", e)
        return ""


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
        model=MODEL, messages=messages, temperature=0.3,
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
        model=MODEL, messages=messages, temperature=0.3, stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            yield delta
