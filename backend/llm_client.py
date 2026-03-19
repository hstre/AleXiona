import os
import json
from openai import OpenAI
from models import Claim, ClaimExtractionResult, ChatMessage, AnalysisResult, Alternative

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EXTRACTION_SYSTEM_PROMPT = """You are a knowledge extraction engine.
Analyze the input and extract structured claims with confidence scores.

For each claim extract:
- text: the claim as a clear, concise statement
- entities: key concepts, objects, people, or things
- relations: directed relationships between entities
- confidence: 0.0–1.0 how confident this claim is supported by the input
- tag: one of "Fact", "Hypothesis", "Observation", "Evidence", "Symptom", "Finding", "Claim"

Relation types: causes, is, belongs_to, enables, reduces, produces, contains, requires, supports, indicates, contradicts

Respond ONLY with valid JSON:
{
  "claims": [
    {
      "text": "string",
      "entities": ["string"],
      "relations": [{"from_entity": "string", "to_entity": "string", "type": "string"}],
      "confidence": 0.85,
      "tag": "string"
    }
  ]
}

Extract 1–6 meaningful claims. Use the input language."""

ANALYSIS_SYSTEM_PROMPT = """You are an analytical AI reviewer.
Given a set of claims/evidence from a knowledge graph, produce a structured analysis.

Respond ONLY with valid JSON:
{
  "primary_hypothesis": "string - the most supported conclusion or main point",
  "confidence": 0.72,
  "alternatives": [
    {"label": "string", "confidence": 0.18},
    {"label": "string", "confidence": 0.10}
  ],
  "missing_evidence": ["string - what additional information would strengthen the analysis"],
  "focus_points": ["string - key areas to investigate or consider"]
}

Keep it concise. Max 2 alternatives, 2 missing evidence items, 2 focus points."""

QUERY_SYSTEM_PROMPT = """You are AleXiona, a knowledge graph assistant.
You have access to a structured knowledge graph built from user inputs.
Answer questions by referencing specific claims from the provided context.
Be precise and grounded — do not hallucinate facts not present in the context."""


def extract_claims(text: str) -> ClaimExtractionResult:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    data = json.loads(response.choices[0].message.content)
    claims = []
    for c in data.get("claims", []):
        relations = [
            __import__('models').Relation(
                from_entity=r["from_entity"],
                to_entity=r["to_entity"],
                type=r["type"],
            )
            for r in c.get("relations", [])
        ]
        claims.append(Claim(
            text=c["text"],
            entities=c.get("entities", []),
            relations=relations,
            confidence=float(c.get("confidence", 0.8)),
            tag=c.get("tag", "Claim"),
        ))
    return ClaimExtractionResult(claims=claims)


def analyze_graph(claims: list[dict]) -> AnalysisResult | None:
    if not claims:
        return None
    claim_text = "\n".join(f"- [{c['tag']}] {c['text']} (confidence: {int(c['confidence']*100)}%)"
                           for c in claims)
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": f"Claims in knowledge graph:\n{claim_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content)
        return AnalysisResult(
            primary_hypothesis=data["primary_hypothesis"],
            confidence=float(data["confidence"]),
            alternatives=[Alternative(**a) for a in data.get("alternatives", [])],
            missing_evidence=data.get("missing_evidence", []),
            focus_points=data.get("focus_points", []),
        )
    except Exception:
        return None


def answer_with_context(
    user_message: str,
    history: list[ChatMessage],
    graph_context: str,
) -> str:
    messages = [{"role": "system", "content": QUERY_SYSTEM_PROMPT}]
    if graph_context:
        messages.append({
            "role": "system",
            "content": f"Knowledge graph context:\n{graph_context}"
        })
    for msg in history[-6:]:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
    )
    return response.choices[0].message.content
