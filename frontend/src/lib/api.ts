const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Relation {
  from_entity: string
  to_entity: string
  type: string
}

export interface Claim {
  text: string
  entities: string[]
  relations: Relation[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  reply: string
  claims: Claim[]
  session_id: string
}

export interface GraphNode {
  id: string
  label: string
  type: 'Claim' | 'Entity'
  fullText?: string
  claimId?: string
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  label: string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export async function sendMessage(
  message: string,
  sessionId: string,
  history: ChatMessage[]
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, history }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getGraph(sessionId: string): Promise<GraphData> {
  const res = await fetch(`${API_URL}/api/graph/${sessionId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateClaim(claimId: string, text: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/graph/claim/${claimId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function deleteClaim(claimId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/graph/claim/${claimId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error(await res.text())
}
