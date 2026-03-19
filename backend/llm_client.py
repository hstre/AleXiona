import os
import json
from openai import OpenAI
from models import (
    Claim, ClaimExtractionResult, ChatMessage,
    ReasoningResult, Alternative, MissingEvidence,
    CounterfactualResult, CounterfactualShift,
    Relation, ClaimType, SourceType, ClaimStatus, ClaimTrend,
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
MODEL = "gpt-4o"

# ── Claim Extraction ─────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """You are a clinical knowledge extraction engine.
Analyze the input and extract structured claims from the text.

For each claim extract:
- text: the claim as a clear, concise statement
- entities: key medical concepts, objects, people, findings
- relations: directed relationships between entities
- evidence_support_score: 0.0–1.0 (how strongly the input supports this claim)
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
Given a set of extracted claims from a knowledge graph, produce a structured reasoning summary.

IMPORTANT:
- Do NOT make autonomous diagnostic decisions
- Use language like "leading hypothesis", "supporting evidence", "conflicting evidence"
- Express support as evidence_support_score (0.0–1.0), NOT as diagnostic probability
- Missing evidence must be tied to specific competing hypotheses

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
      "description": "string - what is missing",
      "needed_for": "string - which hypothesis this would clarify",
      "test_or_type": "string - e.g. D-Dimer, CT-Angiographie"
    }
  ],
  "focus_points": ["string - key area to investigate"]
}

Max 2 alternatives, 3 missing evidence items, 2 focus points."""


QUERY_PROMPT = """You are AleXiona, a clinical reasoning assistant.
You have access to a structured knowledge graph built from clinical notes.
Answer questions by referencing specific claims from the context.
Use cautious, evidence-grounded language. Never claim certainty about diagnoses."""


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
}"""


# ── Functions ─────────────────────────────────────────────────────────────────

def extract_claims(text: str) -> ClaimExtractionResult:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    data = json.loads(response.choices[0].message.content)
    claims = []
    for c in data.get("claims", []):
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
    return ClaimExtractionResult(claims=claims)


def analyze_reasoning(claims: list[dict]) -> ReasoningResult | None:
    if not claims:
        return None
    claim_text = "\n".join(
        f"- [{c.get('claim_type', 'finding').upper()}] {c['text']} "
        f"(support: {int(c.get('evidence_support_score', 0.8) * 100)}%, "
        f"source: {c.get('source_type', 'llm')}, status: {c.get('status', 'active')})"
        for c in claims
    )
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": REASONING_PROMPT},
                {"role": "user", "content": f"Claims in knowledge graph:\n{claim_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content)
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

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": COUNTERFACTUAL_PROMPT},
                {"role": "user", "content": (
                    f"Original leading hypothesis: {original_reasoning.leading_hypothesis} "
                    f"(score: {original_reasoning.evidence_support_score:.2f})\n\n"
                    f"Excluded claim: {excluded['text']}\n\n"
                    f"Remaining claims:\n{remaining_text}"
                )},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content)
        return CounterfactualResult(
            excluded_claim_text=excluded["text"],
            changed_evidence=data.get("changed_evidence", []),
            shifts=[CounterfactualShift(**s) for s in data.get("shifts", [])],
            reasoning_trace=data.get("reasoning_trace", ""),
        )
    except Exception:
        return None


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
