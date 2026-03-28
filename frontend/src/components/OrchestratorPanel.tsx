'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { streamReasoning, getOrchestratorState } from '@/lib/api'
import type { OrchestratorState, OrchestratorAlternative, OrchestratorScoreBreakdown } from '@/lib/api'
import { scoreColor } from '@/lib/utils'

// ── useAnimatedScore ──────────────────────────────────────────────────────────
// Smoothly animates a numeric value from its previous position to a new target.

function useAnimatedScore(target: number, duration = 900): number {
  const [display, setDisplay] = useState(target)   // start at target — no 0→target flash
  const rafRef  = useRef<number | null>(null)
  const fromRef = useRef(target)                    // animate from current value, not 0

  useEffect(() => {
    const from  = fromRef.current
    const start = performance.now()
    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    const tick = (now: number) => {
      const p = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3)      // ease-out cubic
      const val = from + (target - from) * eased
      fromRef.current = val
      setDisplay(val)
      if (p < 1) rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current) }
  }, [target, duration])

  return display
}

// ── ScoreDial ─────────────────────────────────────────────────────────────────
// Animated SVG arc gauge — sweeps from 0 to score like a speedometer.

const ARC_R  = 72
const ARC_CX = 100
const ARC_CY = 90
const ARC_LEN = Math.PI * ARC_R          // semicircle arc length ≈ 226

function ScoreDial({ score, color }: { score: number; color: string }) {
  const animated = useAnimatedScore(score)
  const x0  = ARC_CX - ARC_R
  const x1  = ARC_CX + ARC_R
  const path = `M ${x0} ${ARC_CY} A ${ARC_R} ${ARC_R} 0 0 1 ${x1} ${ARC_CY}`
  const offset = ARC_LEN * (1 - Math.min(Math.max(animated, 0), 1))
  const strokeColor = scoreColor(animated)
  const pctDisplay  = Math.round(animated * 100)

  return (
    <svg viewBox="0 0 200 96" style={{ width: '100%', display: 'block', overflow: 'visible' }}>
      <defs>
        <filter id="dial-glow">
          <feGaussianBlur stdDeviation="3" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {/* Track */}
      <path d={path} fill="none" stroke="rgba(0,0,0,0.08)" strokeWidth="12" strokeLinecap="round" />
      {/* Fill arc */}
      <path
        d={path} fill="none" stroke={strokeColor} strokeWidth="12" strokeLinecap="round"
        strokeDasharray={`${ARC_LEN} ${ARC_LEN}`}
        strokeDashoffset={offset}
        filter="url(#dial-glow)"
      />
      {/* Score text */}
      <text x={ARC_CX} y={ARC_CY - 14} textAnchor="middle" dominantBaseline="middle"
        fontSize="30" fontWeight="800" fill={strokeColor}
        style={{ fontFamily: 'var(--font-mono, monospace)', letterSpacing: '-1px' }}>
        {pctDisplay}%
      </text>
      {/* Min / Max labels */}
      <text x={x0 - 4} y={ARC_CY + 16} textAnchor="middle" fontSize="9" fill="rgba(0,0,0,0.3)">0</text>
      <text x={x1 + 4} y={ARC_CY + 16} textAnchor="middle" fontSize="9" fill="rgba(0,0,0,0.3)">100</text>
    </svg>
  )
}

// ── Leaderboard helpers ───────────────────────────────────────────────────────

const RANK_COLORS = ['#f59e0b', '#94a3b8', '#b45309']

function RankBadge({ rank }: { rank: number }) {
  return (
    <div style={{
      width: 20, height: 20, borderRadius: '50%', flexShrink: 0, fontSize: 10,
      fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: RANK_COLORS[rank] ?? 'var(--surface-2)',
      color: rank < 3 ? '#fff' : 'var(--text-muted)',
    }}>
      {rank + 1}
    </div>
  )
}

function AnimatedBar({ value }: { value: number }) {
  const animated = useAnimatedScore(value)
  const color = scoreColor(animated)
  return (
    <div style={{ flex: 1, height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{
        width: `${Math.min(animated, 1) * 100}%`, height: '100%', borderRadius: 3,
        background: color, boxShadow: `0 0 6px ${color}88`,
      }} />
    </div>
  )
}

interface LeaderboardItemProps {
  alt:    OrchestratorAlternative
  rank:   number
  itemH:  number
}
function LeaderboardItem({ alt, rank, itemH }: LeaderboardItemProps) {
  const animated = useAnimatedScore(alt.score)
  return (
    <div style={{
      position: 'absolute', left: 0, right: 0,
      top: rank * itemH,
      transition: 'top 0.55s cubic-bezier(0.4, 0, 0.2, 1)',
      display: 'flex', alignItems: 'center', gap: 8,
      height: itemH - 4,
    }}>
      <RankBadge rank={rank} />
      <div style={{ flex: 1, fontSize: 12, color: 'var(--text)', lineHeight: 1.3 }}>{alt.text}</div>
      <AnimatedBar value={alt.score} />
      <div style={{
        width: 34, fontSize: 12, textAlign: 'right',
        fontVariantNumeric: 'tabular-nums',
        color: scoreColor(animated), fontWeight: 600,
      }}>
        {Math.round(animated * 100)}%
      </div>
    </div>
  )
}

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_META: Record<string, { label: string; color: string; bg: string }> = {
  confident:    { label: 'Konfident',    color: '#15803d', bg: '#f0fdf4' },
  undecided:    { label: 'Offen',        color: '#92400e', bg: '#fffbeb' },
  contested:    { label: 'Umstritten',   color: '#991b1b', bg: '#fef2f2' },
  insufficient: { label: 'Unzureichend', color: '#1e40af', bg: '#eff6ff' },
}

const FACTOR_META: { key: keyof OrchestratorScoreBreakdown; label: string; weight: string }[] = [
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
  const [state,          setState]          = useState<OrchestratorState | null>(null)
  const [loading,        setLoading]        = useState(false)
  const [error,          setError]          = useState<string | null>(null)
  const [narrative,  setNarrative]  = useState<string>('')
  const [narLoading, setNarLoading] = useState(false)
  const [narError,   setNarError]   = useState<string | null>(null)
  const narCtrlRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setState(await getOrchestratorState(sessionId))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  const startNarrative = useCallback(async () => {
    narCtrlRef.current?.abort()                   // cancel any in-flight stream
    const ctrl = new AbortController()
    narCtrlRef.current = ctrl
    setNarLoading(true)
    setNarrative('')
    setNarError(null)
    try {
      for await (const event of streamReasoning(sessionId, ctrl.signal)) {
        if (ctrl.signal.aborted) break
        if (event.type === 'token') setNarrative(prev => prev + event.content)
        if (event.type === 'error') { setNarError(event.message); break }
      }
    } catch (e: unknown) {
      if (!ctrl.signal.aborted)
        setNarError(e instanceof Error ? e.message : String(e))
    } finally {
      setNarLoading(false)
    }
  }, [sessionId])

  // Abort any running stream when component unmounts
  useEffect(() => () => { narCtrlRef.current?.abort() }, [])

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

        {/* Score dial */}
        <div style={{ marginBottom: 6, marginTop: 4 }}>
          <ScoreDial score={score} color={sm.color} />
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

      {/* ── Alternatives Leaderboard ──────────────────────────────────────── */}
      {state.alternatives.length > 0 && (() => {
        const ITEM_H = 38
        const sorted = [...state.alternatives].sort((a, b) => b.score - a.score)
        return (
          <div style={{
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: 10, padding: '14px 16px',
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
              letterSpacing: '0.06em', color: 'var(--text-muted)', marginBottom: 12 }}>
              Differentialdiagnosen
            </div>
            <div style={{ position: 'relative', height: sorted.length * ITEM_H }}>
              {sorted.map((a, rank) => (
                <LeaderboardItem key={a.text} alt={a} rank={rank} itemH={ITEM_H} />
              ))}
            </div>
          </div>
        )
      })()}

      {/* ── KI-Analyse (streaming narrative) ─────────────────────────────── */}
      <div style={{
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: 10, padding: '14px 16px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: narrative || narLoading || narError ? 10 : 0 }}>
          <div style={{ flex: 1, fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.06em', color: 'var(--text-muted)' }}>
            ✦ KI-Analyse
          </div>
          <button
            onClick={startNarrative}
            disabled={narLoading}
            style={{
              padding: '3px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer',
              border: '1px solid var(--border)', background: 'var(--surface-2)',
              color: 'var(--text-muted)', opacity: narLoading ? 0.5 : 1,
            }}
          >
            {narLoading ? '…' : narrative ? '⟳ Neu' : 'Starten'}
          </button>
        </div>

        {narError && (
          <div style={{ fontSize: 12, color: '#b91c1c', lineHeight: 1.5 }}>
            {narError}
          </div>
        )}

        {(narrative || narLoading) && (
          <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
            {narrative}
            {narLoading && (
              <span style={{ display: 'inline-block', width: 8, height: 12,
                background: 'var(--brand)', marginLeft: 2, verticalAlign: 'middle',
                animation: 'blink 1s step-start infinite',
                borderRadius: 1,
              }} />
            )}
          </div>
        )}

        {!narrative && !narLoading && !narError && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Narrative klinische Einschätzung per LLM — auf Abruf.
          </div>
        )}
      </div>

      {/* ── Footer disclaimer ─────────────────────────────────────────────── */}
      <div style={{ fontSize: 10, color: '#9ca3af', lineHeight: 1.5, paddingBottom: 8 }}>
        Orchestrator-Zustand: deterministisch. KI-Analyse: LLM-generiert, nicht validiert.
        Alle klinischen Entscheidungen obliegen dem behandelnden Arzt.
      </div>
    </div>
  )
}
