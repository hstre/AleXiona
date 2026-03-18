import os
import json
from openai import OpenAI
from models import Claim, ClaimExtractionResult, ChatMessage

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

EXTRACTION_SYSTEM_PROMPT = """You are a knowledge extraction engine.
Your task is to analyze text and extract structured claims, entities, and relations.

For each input, extract:
- claims: discrete factual statements or assertions
- entities: key concepts, objects, people, or things mentioned
- relations: directed relationships between entities with types like "causes", "is", "belongs_to", "enables", "reduces", "produces"

Respond ONLY with valid JSON matching this schema:
{
  "claims": [
    {
      "text": "string - the claim as a clear statement",
      "entities": ["string", ...],
      "relations": [
        {
          "from_entity": "string",
          "to_entity": "string",
          "type": "string - one of: causes, is, belongs_to, enables, reduces, produces, contains, requires, supports"
        }
      ]
    }
  ]
}

Extract 1-5 meaningful claims. Be concise. Use German or English based on input language."""

QUERY_SYSTEM_PROMPT = """You are AleXiona, a knowledge assistant.
You have access to a structured knowledge graph built from previous user inputs.
When answering questions, reference the relevant claims from the knowledge graph.
Be precise and reference specific facts from the provided context."""


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

    raw = response.choices[0].message.content
    data = json.loads(raw)

    claims = []
    for c in data.get("claims", []):
        from models import Relation
        relations = [
            Relation(
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
        ))

    return ClaimExtractionResult(claims=claims)


def answer_with_context(
    user_message: str,
    history: list[ChatMessage],
    graph_context: str,
) -> str:
    messages = [{"role": "system", "content": QUERY_SYSTEM_PROMPT}]

    if graph_context:
        messages.append({
            "role": "system",
            "content": f"Knowledge graph context (established facts):\n{graph_context}"
        })

    for msg in history[-6:]:  # last 3 turns
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.3,
    )

    return response.choices[0].message.content
