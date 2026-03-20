const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Enums ──────────────────────────────────────────────────────────────────

export type ClaimType =
  | 'symptom' | 'finding' | 'lab' | 'imaging'
  | 'hypothesis' | 'diagnosis' | 'therapy' | 'risk_factor' | 'guideline'

export type SourceType =
  | 'clinician' | 'llm' | 'guideline'
  | 'imaging_model' | 'lab_system' | 'imported_document'

export type ClaimStatus = 'active' | 'resolved' | 'superseded'
export type ClaimTrend  = 'improving' | 'worsening' | 'stable' | 'unknown'

export type ConflictType     = 'competing_hypothesis' | 'negation' | 'evidence_mismatch' | 'timeline_gap' | 'therapy_without_indication' | 'stale_hypothesis' | 'contradictory_values'
export type ConflictSeverity = 'error' | 'warning' | 'info'

// ── Core models ─────────────────────────────────────────────────────────────

export interface Relation {
  from_entity: string
  to_entity:   string
  type:        string
}

export interface Claim {
  text:                   string
  entities:               string[]
  relations:              Relation[]
  evidence_support_score: number
  claim_type:             ClaimType
  source_type:            SourceType
  source_ref:             string
  derived_from:           string[]
  status:                 ClaimStatus
  time_offset:            string | null
  trend:                  ClaimTrend
  created_at?:            string
  claimId?:               string
}

export interface Alternative {
  label:                  string
  evidence_support_score: number
  supporting_claim_ids:   string[]
}

export interface MissingEvidence {
  description:  string
  needed_for:   string
  test_or_type: string
}

export interface ReasoningResult {
  leading_hypothesis:     string
  supporting_evidence:    string[]
  conflicting_evidence:   string[]
  evidence_support_score: number
  alternatives:           Alternative[]
  missing_evidence:       MissingEvidence[]
  focus_points:           string[]
}

export interface Conflict {
  id:                  string
  type:                ConflictType
  severity:            ConflictSeverity
  message:             string
  affected_claim_ids:  string[]
}

export interface CounterfactualShift {
  hypothesis:   string
  score_before: number
  score_after:  number
}

export interface CounterfactualResult {
  excluded_claim_text: string
  changed_evidence:    string[]
  shifts:              CounterfactualShift[]
  reasoning_trace:     string
}

// ── Graph ────────────────────────────────────────────────────────────────────

export interface GraphNode {
  id:                     string
  label:                  string
  type:                   'Claim' | 'Entity'
  fullText?:              string
  claimId?:               string
  evidence_support_score?: number
  claim_type?:            ClaimType
  source_type?:           SourceType
  source_ref?:            string
  status?:                ClaimStatus
  time_offset?:           string | null
  trend?:                 ClaimTrend
  created_at?:            string
  derived_from?:          string[]   // claimIds this claim was derived from
}

export interface GraphEdge {
  id:     string
  source: string
  target: string
  label:  string
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatMessage {
  role:    'user' | 'assistant'
  content: string
}

export interface ChatResponse {
  reply:      string
  claims:     Claim[]
  session_id: string
  reasoning:  ReasoningResult | null
  conflicts:  Conflict[]
}

export interface SessionInfo {
  session_id:  string
  claim_count: number
}

// ── Streaming SSE types ───────────────────────────────────────────────────────

export type StreamEvent =
  | { type: 'claims';  claims: Claim[] }
  | { type: 'token';   content: string }
  | { type: 'done';    reply: string; claims: Claim[]; reasoning: ReasoningResult | null; conflicts: Conflict[]; session_id: string }
  | { type: 'error';   message: string }

// ── API calls ─────────────────────────────────────────────────────────────────

export async function sendMessage(
  message: string, sessionId: string, history: ChatMessage[]
): Promise<ChatResponse> {
  const res = await fetch(`${API_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, history }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function* streamMessage(
  message: string, sessionId: string, history: ChatMessage[]
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_URL}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, history }),
  })
  if (!res.ok) throw new Error(await res.text())

  const reader  = res.body!.getReader()
  const decoder = new TextDecoder()
  let   buf     = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const text = line.slice(6).trim()
      if (!text) continue
      try {
        yield JSON.parse(text) as StreamEvent
      } catch {
        // malformed line — skip
      }
    }
  }
}

export async function getGraph(sessionId: string): Promise<GraphData> {
  const res = await fetch(`${API_URL}/api/graph/${sessionId}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ClaimPatch {
  text?:                   string
  evidence_support_score?: number
  claim_type?:             ClaimType
  status?:                 ClaimStatus
  trend?:                  string
  time_offset?:            string | null
  source_ref?:             string
}

export async function patchClaim(claimId: string, fields: ClaimPatch): Promise<void> {
  const res = await fetch(`${API_URL}/api/graph/claim/${claimId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  })
  if (!res.ok) throw new Error(await res.text())
}

export async function deleteClaim(claimId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/graph/claim/${claimId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
}

export async function runCounterfactual(
  sessionId: string, claimId: string
): Promise<CounterfactualResult> {
  const res = await fetch(`${API_URL}/api/graph/${sessionId}/counterfactual/${claimId}`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
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

export async function seedDemo(sessionId: string): Promise<{ seeded: boolean; claim_count?: number; reason?: string }> {
  const res = await fetch(`${API_URL}/api/demo/seed/${sessionId}`, { method: 'POST' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface ManualClaim {
  text:                   string
  claim_type:             ClaimType
  source_type:            SourceType
  source_ref:             string
  evidence_support_score: number
  time_offset:            string
  trend:                  ClaimTrend
  status:                 ClaimStatus
  derived_from?:          string[]   // explicit claimIds selected by the user
}

export async function addManualClaim(sessionId: string, claim: ManualClaim): Promise<void> {
  const res = await fetch(`${API_URL}/api/graph/${sessionId}/claims`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(claim),
  })
  if (!res.ok) throw new Error(await res.text())
}
