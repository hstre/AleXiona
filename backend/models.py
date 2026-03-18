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


class ClaimExtractionResult(BaseModel):
    claims: list[Claim]


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str
    history: list[ChatMessage] = []


class ChatResponse(BaseModel):
    reply: str
    claims: list[Claim]
    session_id: str


class NodeUpdate(BaseModel):
    text: str


class ClaimNode(BaseModel):
    id: str
    text: str
    type: str = "Claim"


class EntityNode(BaseModel):
    id: str
    name: str
    type: str = "Entity"


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation_type: str


class GraphData(BaseModel):
    nodes: list[dict]
    edges: list[dict]
