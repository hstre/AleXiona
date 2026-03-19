from pydantic import BaseModel
from typing import Optional


class Relation(BaseModel):
    from_entity: str
    to_entity: str
    type: str


class Claim(BaseModel):
    text: str
    entities: list[str]
    relations: list[Relation]
    confidence: float = 0.8
    tag: str = "Claim"


class ClaimExtractionResult(BaseModel):
    claims: list[Claim]


class Alternative(BaseModel):
    label: str
    confidence: float


class AnalysisResult(BaseModel):
    primary_hypothesis: str
    confidence: float
    alternatives: list[Alternative]
    missing_evidence: list[str]
    focus_points: list[str]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str
    claims: list[Claim]
    session_id: str
    analysis: Optional[AnalysisResult] = None


class NodeUpdate(BaseModel):
    text: str


class GraphData(BaseModel):
    nodes: list[dict]
    edges: list[dict]
