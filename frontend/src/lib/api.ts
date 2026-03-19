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
  confidence: number
  tag: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface AnalysisResult {
  primary_hypothesis: string
  confidence: number
  alternatives: { label: string; confidence: number }[]
  missing_evidence: string[]
  focus_points: string[]
}

export interface ChatResponse {
  reply: string
  claims: Claim[]
  session_id: string
  analysis: AnalysisResult | null
}

export interface GraphNode {
  id: string
  label: string
  type: 'Claim' | 'Entity'
  fullText?: string
  claimId?: string
  confidence?: number
  tag?: string
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

export interface SessionInfo {
  session_id: string
  claim_count: number
}

export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${API_URL}/api/sessions`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}
