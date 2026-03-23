const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// ── Session token ─────────────────────────────────────────────────────────────

/** In-memory session token.  Persisted to sessionStorage so page refreshes
 *  don't force a new login within the same browser tab. */
let _sessionToken: string | null =
  typeof window !== 'undefined' ? sessionStorage.getItem('alexiona_token') : null

/** Obtain a session token if we don't have one yet.  Called lazily before the
 *  first API request so SSR/build-time imports don't trigger a fetch.
 *  The token is bound to the session_id currently stored in localStorage so
 *  the backend can enforce session ownership. */
async function ensureSession(): Promise<void> {
  if (_sessionToken) return
  const sessionId =
    typeof window !== 'undefined'
      ? (localStorage.getItem('alexiona_session') ?? undefined)
      : undefined
  const res = await fetch(`${API_URL}/api/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: 'clinician', session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Auth failed: HTTP ${res.status}`)
  const data = await res.json() as { token: string }
  _sessionToken = data.token
  if (typeof window !== 'undefined') sessionStorage.setItem('alexiona_token', data.token)
}

/** Normalise any HeadersInit value to a plain object. */
function headersToObject(h: HeadersInit | undefined): Record<string, string> {
  if (!h) return {}
  if (h instanceof Headers) return Object.fromEntries(h.entries())
  if (Array.isArray(h)) return Object.fromEntries(h)
  return h as Record<string, string>
}

/** Headers for every authenticated request. */
async function authHeaders(): Promise<Record<string, string>> {
  await ensureSession()
  if (!_sessionToken) throw new Error('Failed to obtain session token')
  return { 'Content-Type': 'application/json', 'X-Session-Token': _sessionToken }
}

/** Clear the local session token (e.g. on 401 from server). */
export function clearSession(): void {
  _sessionToken = null
  if (typeof window !== 'undefined') sessionStorage.removeItem('alexiona_token')
}

/**
 * Authenticated fetch wrapper.
 * On 401 (expired token): clears session, obtains a new token, retries once.
 */
async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, { ...init, headers: { ...await authHeaders(), ...headersToObject(init.headers) } })
  if (res.status === 401) {
    clearSession()
    return fetch(url, { ...init, headers: { ...await authHeaders(), ...headersToObject(init.headers) } })
  }
  return res
}

/** Parse response body as JSON; throws a descriptive error if body is not valid JSON. */
async function safeJson<T>(res: Response): Promise<T> {
  try {
    return await res.json() as T
  } catch {
    throw new Error(`Server returned non-JSON response (status ${res.status})`)
  }
}

/** Extract a human-readable message from a structured or plain-text error response. */
async function parseError(res: Response): Promise<Error> {
  try {
    const data = await res.json()
    const detail = data?.detail
    if (typeof detail === 'string') return new Error(detail)
    if (typeof detail?.message === 'string') return new Error(detail.message)
    return new Error(JSON.stringify(detail ?? data))
  } catch {
    return new Error((await res.text()) || `HTTP ${res.status}`)
  }
}

// ── Enums ──────────────────────────────────────────────────────────────────

export type ClaimType =
  | 'symptom' | 'finding' | 'lab' | 'imaging'
  | 'hypothesis' | 'diagnosis' | 'therapy' | 'risk_factor' | 'guideline'

export type SourceType =
  | 'clinician' | 'llm' | 'guideline'
  | 'imaging_model' | 'lab_system' | 'imported_document'
  | 'patient_report' | 'wearable' | 'home_device' | 'caregiver_report'

export type ClaimStatus = 'active' | 'observed' | 'inferred' | 'confirmed' | 'contested' | 'refuted' | 'withdrawn' | 'resolved' | 'superseded' | 'tentative'
export type ClaimTrend  = 'improving' | 'worsening' | 'stable' | 'unknown'

export type ConflictType     = 'competing_hypothesis' | 'negation' | 'evidence_mismatch' | 'timeline_gap' | 'therapy_without_indication' | 'stale_hypothesis' | 'contradictory_values' | 'temporal_inconsistency'
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
  derived_from:           string[]   // explicit causal/epistemic derivation
  related_to:             string[]   // heuristic semantic proximity
  status:                 ClaimStatus
  time_offset:            string | null
  trend:                  ClaimTrend
  created_at?:            string
  claimId?:               string
  notes?:                 string
}

export interface Alternative {
  label:                  string
  evidence_support_score: number
  supporting_claim_ids:   string[]
}

export interface MissingEvidence {
  description:            string
  needed_for:             string
  test_or_type:           string
  differentiates_between: string[]  // hypothesis labels this would help differentiate
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

export interface HypothesisCounterfactualResult {
  hypothesis:           string
  required_changes:     string[]   // what would need to be different
  critical_evidence:    string[]   // the decisive supporting claims
  alternative_if_false: string     // which hypothesis takes over
  reasoning_trace:      string
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
  derived_from?:          string[]   // claimIds this claim was derived from (explicit causal)
  related_to?:            string[]   // claimIds heuristically related (semantic proximity)
  notes?:                 string
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
  const res = await apiFetch(`${API_URL}/api/chat`, {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId, history }),
  })
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export async function* streamMessage(
  message: string, sessionId: string, history: ChatMessage[]
): AsyncGenerator<StreamEvent> {
  const res = await apiFetch(`${API_URL}/api/chat/stream`, {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId, history }),
  })
  if (!res.ok) throw await parseError(res)

  if (!res.body) throw new Error('Streaming response body is null')
  const reader  = res.body.getReader()
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
      } catch (e) {
        console.warn('[stream] malformed SSE line, skipping:', text, e)
      }
    }
  }
}

export async function getGraph(sessionId: string): Promise<GraphData> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}`)
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export interface ClaimPatch {
  text?:                   string
  evidence_support_score?: number
  claim_type?:             ClaimType
  status?:                 ClaimStatus
  trend?:                  ClaimTrend
  time_offset?:            string | null
  source_ref?:             string
  notes?:                  string
}

export async function patchClaim(claimId: string, fields: ClaimPatch): Promise<void> {
  const res = await apiFetch(`${API_URL}/api/graph/claim/${claimId}`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  })
  if (!res.ok) throw await parseError(res)
}

export async function deleteClaim(claimId: string): Promise<void> {
  const res = await apiFetch(`${API_URL}/api/graph/claim/${claimId}`, { method: 'DELETE' })
  if (!res.ok) throw await parseError(res)
}

/** Patch multiple claims in parallel. Returns count of failures (0 = all ok). */
export async function batchPatch(ids: string[], fields: ClaimPatch): Promise<number> {
  const results = await Promise.allSettled(ids.map(id => patchClaim(id, fields)))
  return results.filter(r => r.status === 'rejected').length
}

/** Delete multiple claims in parallel. Returns count of failures (0 = all ok). */
export async function batchDelete(ids: string[]): Promise<number> {
  const results = await Promise.allSettled(ids.map(id => deleteClaim(id)))
  return results.filter(r => r.status === 'rejected').length
}

export async function runCounterfactual(
  sessionId: string, claimId: string
): Promise<CounterfactualResult> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/counterfactual/${claimId}`, {
    method: 'POST',
  })
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export async function hypothesisCounterfactual(
  sessionId: string, hypothesis: string
): Promise<HypothesisCounterfactualResult> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/counterfactual/hypothesis`, {
    method: 'POST',
    body: JSON.stringify({ hypothesis }),
  })
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export async function listSessions(): Promise<SessionInfo[]> {
  const res = await apiFetch(`${API_URL}/api/sessions`)
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await apiFetch(`${API_URL}/api/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw await parseError(res)
}

export type DemoScenario = 'cap' | 'pe' | 'ards' | 'nstemi'

export async function seedDemo(
  sessionId: string,
  lang:     'en' | 'de'   = 'en',
  scenario: DemoScenario  = 'cap',
): Promise<{ seeded: boolean; claim_count?: number; reason?: string }> {
  const res = await apiFetch(`${API_URL}/api/demo/seed/${sessionId}?lang=${lang}&scenario=${scenario}`, { method: 'POST' })
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

// ── Entity deduplication ─────────────────────────────────────────────────────

export interface EntityGroup {
  key:       string
  canonical: string
  aliases:   string[]
}

export async function getEntityDuplicates(sessionId: string): Promise<EntityGroup[]> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/entity-duplicates`)
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export async function mergeEntities(
  sessionId: string, canonical: string, aliases: string[]
): Promise<{ merged: number }> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/entities/merge`, {
    method: 'POST',
    body: JSON.stringify({ canonical, aliases }),
  })
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

// ── Session export / import ──────────────────────────────────────────────────

export async function exportSession(sessionId: string): Promise<object> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/export`)
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
}

export async function importSession(
  sessionId: string, claims: object[]
): Promise<{ imported: number; skipped: number }> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/import`, {
    method: 'POST',
    body: JSON.stringify({ claims }),
  })
  if (!res.ok) throw await parseError(res)
  return safeJson(res)
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

export async function explainConflict(
  sessionId: string,
  conflict: Pick<Conflict, 'type' | 'severity' | 'message' | 'affected_claim_ids'>,
): Promise<string> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/conflicts/explain`, {
    method: 'POST',
    body: JSON.stringify(conflict),
  })
  if (!res.ok) throw await parseError(res)
  const data = await safeJson<{ explanation?: string }>(res)
  if (typeof data.explanation !== 'string') throw new Error('Unexpected response format from explain endpoint')
  return data.explanation
}

export async function addManualClaim(sessionId: string, claim: ManualClaim): Promise<void> {
  const res = await apiFetch(`${API_URL}/api/graph/${sessionId}/claims`, {
    method: 'POST',
    body: JSON.stringify(claim),
  })
  if (!res.ok) throw await parseError(res)
}
