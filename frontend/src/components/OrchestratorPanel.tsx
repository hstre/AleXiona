'use client'

import { useState, useEffect, useCallback } from 'react'

const API_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '')

// ── Types ─────────────────────────────────────────────────────────────────────

interface ScoreBreakdown {
  evidence:  number
  guideline: number
  composite: number
  temporal:  number
  conflict:  number
}

interface Alternative {
  text:                        string
  score:                       number
  composite_score_contribution: number
}

interface OrchestratorState {
  session_id:         string
  leading_hypothesis: string | null
  orchestrated_score: number
  status:             'confident' | 'undecided' | 'contested' | 'insufficient'
  why:                string
  key_conflicts:      string[]
  missing_critical:   string[]
  next_action:        string
  score_breakdown:    ScoreBreakdown
  alternatives:       Alternative[]
  generated_at:       string
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  confident:    { label: 'Konfident',    color: '#15803d', bg: '#f0fdf4' },
  undecided:    { label: 'Offen',        color: '#92400e', bg: '#fffbeb' },
  contested:    { label: 'Umstritten',   color: '#991b1b', bg: '#fef2f2' },
  insufficient: { label: 'Unzureichend', color: '#1e40af', bg: '#eff6ff' },
}

const FACTOR_META: { key: keyof ScoreBreakdown; label: string; weight: string }[] = [
  { key: 'evidence',  label: 'Evidenz',        weight: '40 %' },
  { key: 'guideline', label: 'Leitlinie',       weight: '25 %' },
  { key: 'composite', label: 'Klin. Scores',    weight: '15 %' },
  { key: 'temporal',  label: 'Aktualität',      weight: '10 %' },
  { key: 'conflict',  label: 'Konflikte',       weight: '−10 %' },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

const pct = (v: number) => `${Math.round(Math.abs(v) * 100)} %`

function ScoreBar({ value, max = 0.4, isNeg = false }: { value: number; max?: number; isNeg?: boolean }) {
  const w = Math.min(Math.abs(value) / max, 1) * 100
  return (
    <div style={{ flex: 1, height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{
        width: `${w}%`, height: '100%', borderRadius: 3,
        background: isNeg ? '#ef4444' : '#3b82f6',
        transition: 'width 0.4s ease',
      }} />
    </div>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface Props {
  sessionId: string
}

export default function OrchestratorPanel({ sessionId }: Props) {
  const [state,   setState]   = useState<OrchestratorState | null>(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/graph/${sessionId}/orchestrate`)
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data?.detail?.message ?? data?.detail ?? `Fehler ${res.status}`)
      }
      setState(await res.json())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  // ── Empty / error states ──────────────────────────────────────────────────

  if (loading) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', gap: 12, color: 'var(--text-muted)' }}>
      <div style={{ fontSize: 32 }}>✦</div>
      <div style={{ fontSize: 14 }}>Orchestrator läuft …</div>
    </div>
  )

  if (error) return (
    <div style={{ padding: 24 }}>
      <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8,
        padding: '12px 16px', color: '#991b1b', fontSize: 13 }}>{error}</div>
    </div>
  )

  if (!state) return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', gap: 10, color: 'var(--text-muted)' }}>
      <div style={{ fontSize: 36 }}>◎</div>
      <div style={{ fontSize: 14, fontWeight: 600 }}>Kein klinischer Zustand geladen</div>
    </div>
  )

  const sm = STATUS_META[state.status] ?? STATUS_META.insufficient
  const score = state.orchestrated_score
  const bd    = state.score_breakdown

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: '16px 20px',
      display: 'flex', flexDirection: 'column', gap: 14 }}>

      {/* ── Header: Status + Refresh ──────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em',
            color: 'var(--text-muted)', marginBottom: 4 }}>Klinischer Zustand</div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {new Date(state.generated_at).toLocaleTimeString('de-DE')}
          </div>
        </div>
        <button onClick={load} style={{
          padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)',
          background: 'var(--surface-elevated)', fontSize: 12, cursor: 'pointer',
          color: 'var(--text-muted)',
        }}>⟳ Aktualisieren</button>
      </div>

      {/* ── Hero: Leading Hypothesis ──────────────────────────────────────── */}
      <div style={{
        background: sm.bg, border: `2px solid ${sm.color}`,
        borderRadius: 12, padding: '16px 20px',
      }}>
        {/* Status badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <div style={{
            background: sm.color, color: '#fff', fontSize: 11, fontWeight: 700,
            padding: '2px 10px', borderRadius: 20, textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>{sm.label}</div>
          <div style={{ fontSize: 12, color: sm.color, fontWeight: 600 }}>
            Gesamtscore: {pct(score)}
          </div>
        </div>

        {/* Hypothesis text */}
        <div style={{ fontSize: 18, fontWeight: 700, color: sm.color, lineHeight: 1.3,
          marginBottom: 10 }}>
          {state.leading_hypothesis ?? 'Keine Hypothese'}
        </div>

        {/* Score arc / visual meter */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ height: 8, background: '#e5e7eb', borderRadius: 4, overflow: 'hidden' }}>
            <div style={{
              width: `${score * 100}%`, height: '100%',
              background: score >= 0.52 ? sm.color : score >= 0.25 ? '#f59e0b' : '#6b7280',
              borderRadius: 4, transition: 'width 0.5s ease',
            }} />
          </div>
        </div>

        {/* Why */}
        <div style={{ fontSize: 13, color: sm.color, lineHeight: 1.6, opacity: 0.9 }}>
          {state.why}
        </div>
      </div>

      {/* ── Next Action ───────────────────────────────────────────────────── */}
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 10, padding: '14px 16px',
      }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: 'var(--brand)', marginBottom: 8 }}>
          → Nächste Maßnahme
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', lineHeight: 1.5 }}>
          {state.next_action}
        </div>
      </div>

      {/* ── Score Breakdown ───────────────────────────────────────────────── */}
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 10, padding: '14px 16px',
      }}>
        <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
          letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 12 }}>
          Score-Aufschlüsselung
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {FACTOR_META.map(f => {
            const v   = bd[f.key]
            const neg = v < 0
            return (
              <div key={f.key} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ width: 90, fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 }}>
                  {f.label}
                </div>
                <ScoreBar value={v} max={0.40} isNeg={neg} />
                <div style={{
                  width: 44, fontSize: 12, textAlign: 'right', fontVariantNumeric: 'tabular-nums',
                  color: neg ? '#ef4444' : 'var(--text)',
                }}>
                  {neg ? '−' : '+'}{pct(v)}
                </div>
                <div style={{ width: 38, fontSize: 10, color: '#9ca3af', textAlign: 'right' }}>
                  {f.weight}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Two-column: Conflicts + Missing ──────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>

        {/* Conflicts */}
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '14px 16px',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: '#991b1b', marginBottom: 8 }}>
            ⚡ Konflikte ({state.key_conflicts.length})
          </div>
          {state.key_conflicts.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Keine Konflikte.</div>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex',
              flexDirection: 'column', gap: 6 }}>
              {state.key_conflicts.map((c, i) => (
                <li key={i} style={{ fontSize: 12, color: '#991b1b', lineHeight: 1.4,
                  paddingLeft: 14, position: 'relative' }}>
                  <span style={{ position: 'absolute', left: 0 }}>!</span>
                  {c}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Missing */}
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '14px 16px',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: '#1e40af', marginBottom: 8 }}>
            ⬜ Fehlend ({state.missing_critical.length})
          </div>
          {state.missing_critical.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Nichts kritisch fehlend.</div>
          ) : (
            <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex',
              flexDirection: 'column', gap: 6 }}>
              {state.missing_critical.map((m, i) => (
                <li key={i} style={{ fontSize: 12, color: '#1e40af', lineHeight: 1.4,
                  paddingLeft: 14, position: 'relative' }}>
                  <span style={{ position: 'absolute', left: 0 }}>−</span>
                  {m}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* ── Alternatives ─────────────────────────────────────────────────── */}
      {state.alternatives.length > 0 && (
        <div style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '14px 16px',
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 10 }}>
            Alternativen
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {state.alternatives.map((a, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ flex: 1, fontSize: 13, color: 'var(--text)' }}>{a.text}</div>
                <div style={{ width: 80 }}>
                  <ScoreBar value={a.score} max={1} />
                </div>
                <div style={{ width: 36, fontSize: 12, color: 'var(--text-muted)',
                  textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {pct(a.score)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Footer disclaimer ─────────────────────────────────────────────── */}
      <div style={{ fontSize: 10, color: '#9ca3af', lineHeight: 1.5, paddingBottom: 8 }}>
        Dieser Zustand wird deterministisch aus dem Evidenzgraphen berechnet — kein LLM-Aufruf.
        Alle klinischen Entscheidungen obliegen dem behandelnden Arzt.
      </div>
    </div>
  )
}
