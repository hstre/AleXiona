'use client'

/**
 * DecisionLedger — chronological log of every clinically significant state change.
 *
 * Fetches from GET /api/graph/{sessionId}/decisions and renders each
 * DecisionEntry as an expandable card. Entries are computed from consecutive
 * OrchestratorSnapshots (persisted every time the Orchestrator is invoked).
 */

import { useState, useEffect, useCallback } from 'react'
import { getDecisions } from '@/lib/api'
import type { DecisionEntry, OrchestratorAlternative } from '@/lib/api'
import { scoreColor } from '@/lib/utils'

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('de-DE', {
      hour:   '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch { return iso }
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('de-DE', {
      day:   '2-digit',
      month: '2-digit',
      year:  'numeric',
    })
  } catch { return '' }
}

const CHANGE_META: Record<string, { label: string; color: string; icon: string }> = {
  initial:           { label: 'Initialer Zustand',       color: '#6366f1', icon: '◎' },
  hypothesis_change: { label: 'Hypothese gewechselt',    color: '#f59e0b', icon: '⇄' },
  status_change:     { label: 'Status geändert',         color: '#3b8eea', icon: '⊙' },
  score_shift:       { label: 'Score-Verschiebung',      color: '#10b981', icon: '↕' },
}

const STATUS_COLOR: Record<string, string> = {
  confident:    '#10b981',
  undecided:    '#f59e0b',
  contested:    '#ef4444',
  insufficient: '#6b7280',
}

function ScorePill({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = scoreColor(score)
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-xs font-mono font-semibold"
      style={{ background: color + '22', color }}>
      {pct}%
    </span>
  )
}

function ScoreDelta({ delta }: { delta: number | null }) {
  if (delta === null) return null
  const abs = Math.abs(delta)
  if (abs < 0.01) return null
  const up    = delta > 0
  const color = up ? '#10b981' : '#ef4444'
  return (
    <span className="text-xs font-mono" style={{ color }}>
      {up ? '▲' : '▼'} {Math.round(abs * 100)}pp
    </span>
  )
}

// ── Entry card ─────────────────────────────────────────────────────────────────

function DecisionCard({ entry, index }: { entry: DecisionEntry; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const meta   = CHANGE_META[entry.change_type] ?? CHANGE_META.score_shift
  const sColor = STATUS_COLOR[entry.status] ?? '#6b7280'

  return (
    <div className="relative">
      {/* Vertical connector line */}
      <div className="absolute left-4 top-8 bottom-0 w-px"
        style={{ background: 'var(--border)', zIndex: 0 }} />

      <div className="relative z-10 flex gap-3">
        {/* Timeline dot */}
        <div className="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm font-bold"
          style={{ background: meta.color + '22', color: meta.color, border: `2px solid ${meta.color}` }}>
          {meta.icon}
        </div>

        {/* Card */}
        <div className="flex-1 mb-4 rounded-xl overflow-hidden"
          style={{ border: '1px solid var(--border)', background: 'var(--surface)' }}>

          {/* Header row */}
          <button
            className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:opacity-80 transition-opacity"
            onClick={() => setExpanded(v => !v)}>

            {/* Timestamp + date */}
            <div className="flex flex-col shrink-0">
              <span className="text-xs font-mono font-semibold" style={{ color: 'var(--text)' }}>
                {fmt(entry.recorded_at)}
              </span>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                {fmtDate(entry.recorded_at)}
              </span>
            </div>

            <div className="w-px h-6 shrink-0" style={{ background: 'var(--border)' }} />

            {/* Change badge */}
            <span className="shrink-0 text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: meta.color + '18', color: meta.color }}>
              {meta.label}
            </span>

            {/* Hypothesis */}
            <span className="flex-1 text-xs font-medium truncate"
              style={{ color: 'var(--text)' }}>
              {entry.hypothesis ?? <em style={{ color: 'var(--text-muted)' }}>Unzureichend</em>}
            </span>

            {/* Score + delta */}
            <div className="flex items-center gap-1.5 shrink-0">
              <ScorePill score={entry.score} />
              <ScoreDelta delta={entry.score_delta} />
            </div>

            {/* Status badge */}
            <span className="shrink-0 text-xs px-1.5 py-0.5 rounded font-medium"
              style={{ background: sColor + '18', color: sColor }}>
              {entry.status}
            </span>

            {/* Expand chevron */}
            <span className="shrink-0 text-xs" style={{ color: 'var(--text-muted)' }}>
              {expanded ? '▲' : '▼'}
            </span>
          </button>

          {/* Expanded detail */}
          {expanded && (
            <div className="px-3 pb-3 pt-1 space-y-3 border-t"
              style={{ borderColor: 'var(--border)' }}>

              {/* Hypothesis change diff */}
              {entry.change_type === 'hypothesis_change' && entry.previous_hypothesis && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="px-2 py-0.5 rounded-full line-through"
                    style={{ background: '#ef444422', color: '#ef4444' }}>
                    {entry.previous_hypothesis}
                  </span>
                  <span style={{ color: 'var(--text-muted)' }}>→</span>
                  <span className="px-2 py-0.5 rounded-full"
                    style={{ background: '#10b98122', color: '#10b981' }}>
                    {entry.hypothesis ?? 'Unzureichend'}
                  </span>
                </div>
              )}

              {/* Status change diff */}
              {entry.change_type === 'status_change' && entry.previous_status && (
                <div className="flex items-center gap-2 text-xs">
                  <span className="px-2 py-0.5 rounded-full"
                    style={{ background: (STATUS_COLOR[entry.previous_status] ?? '#6b7280') + '22',
                             color:       STATUS_COLOR[entry.previous_status] ?? '#6b7280' }}>
                    {entry.previous_status}
                  </span>
                  <span style={{ color: 'var(--text-muted)' }}>→</span>
                  <span className="px-2 py-0.5 rounded-full"
                    style={{ background: sColor + '22', color: sColor }}>
                    {entry.status}
                  </span>
                </div>
              )}

              {/* Rationale */}
              <div>
                <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>
                  Begründung
                </div>
                <p className="text-xs leading-relaxed" style={{ color: 'var(--text)' }}>
                  {entry.rationale}
                </p>
              </div>

              {/* Next action */}
              {entry.next_action && (
                <div className="flex items-start gap-2 px-2.5 py-2 rounded-lg"
                  style={{ background: 'var(--brand-pale)', border: '1px solid var(--brand)' + '44' }}>
                  <span className="text-xs shrink-0 mt-0.5" style={{ color: 'var(--brand)' }}>▶</span>
                  <span className="text-xs" style={{ color: 'var(--brand)' }}>{entry.next_action}</span>
                </div>
              )}

              {/* Alternatives */}
              {entry.alternatives.length > 0 && (
                <div>
                  <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>
                    Verworfen / Alternativen
                  </div>
                  <div className="space-y-1">
                    {entry.alternatives.map((a: OrchestratorAlternative) => (
                      <div key={a.text} className="flex items-center justify-between gap-2">
                        <span className="text-xs truncate flex-1" style={{ color: 'var(--text-light)' }}>
                          {a.text}
                        </span>
                        <ScorePill score={a.score} />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Conflicts */}
              {entry.key_conflicts.length > 0 && (
                <div>
                  <div className="text-xs font-medium mb-1" style={{ color: '#ef4444' }}>
                    Konflikte
                  </div>
                  <ul className="space-y-0.5">
                    {entry.key_conflicts.map((c, i) => (
                      <li key={i} className="text-xs" style={{ color: 'var(--text-light)' }}>⚠ {c}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Missing */}
              {entry.missing_critical.length > 0 && (
                <div>
                  <div className="text-xs font-medium mb-1" style={{ color: '#f59e0b' }}>
                    Fehlende Evidenz
                  </div>
                  <ul className="space-y-0.5">
                    {entry.missing_critical.map((m, i) => (
                      <li key={i} className="text-xs" style={{ color: 'var(--text-light)' }}>? {m}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

interface Props {
  sessionId: string
}

export default function DecisionLedger({ sessionId }: Props) {
  const [decisions, setDecisions] = useState<DecisionEntry[]>([])
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getDecisions(sessionId)
      setDecisions(data.decisions)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fehler beim Laden')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}>
        <div>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            Decision Ledger
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            Klinisch signifikante Zustandsübergänge · {decisions.length} Einträge
          </p>
        </div>
        <button onClick={load} disabled={loading}
          className="w-7 h-7 rounded-lg flex items-center justify-center hover:opacity-70 disabled:opacity-40"
          title="Aktualisieren">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)"
            strokeWidth="2" className={loading ? 'animate-spin' : ''}>
            <path d="M23 4v6h-6M1 20v-6h6" />
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
          </svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {loading && decisions.length === 0 && (
          <div className="flex items-center justify-center py-12">
            <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
              style={{ borderColor: 'var(--brand)' }} />
          </div>
        )}

        {error && (
          <div className="text-xs px-3 py-2 rounded-lg"
            style={{ background: '#fef2f2', color: '#dc2626' }}>
            {error}
          </div>
        )}

        {!loading && !error && decisions.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 gap-3 text-center">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl"
              style={{ background: 'var(--surface-2)' }}>◎</div>
            <p className="text-sm font-medium" style={{ color: 'var(--text)' }}>
              Noch keine Entscheidungen
            </p>
            <p className="text-xs max-w-xs" style={{ color: 'var(--text-muted)' }}>
              Jedes Mal, wenn der Orchestrator aufgerufen wird, wird ein Snapshot gespeichert.
              Signifikante Zustandsänderungen erscheinen hier.
            </p>
          </div>
        )}

        {decisions.length > 0 && (
          // Reverse so newest is at top
          [...decisions].reverse().map((entry, i) => (
            <DecisionCard
              key={entry.snapshot_id}
              entry={entry}
              index={decisions.length - 1 - i}
            />
          ))
        )}
      </div>
    </div>
  )
}
