'use client'

/**
 * ReplayPanel — Epistemic Time Machine.
 *
 * Shows a horizontal timeline of OrchestratorSnapshots.
 * Clicking or scrubbing a snapshot renders the full orchestrator state
 * at that moment in time, making it possible to see:
 *   - Which hypothesis was leading at T
 *   - What the score and status were
 *   - What conflicts / missing evidence existed
 *   - How the state evolved step by step
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { getSnapshots } from '@/lib/api'
import type { OrchestratorSnapshot, OrchestratorAlternative } from '@/lib/api'
import { scoreColor } from '@/lib/utils'

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmt(iso: string, opts?: Intl.DateTimeFormatOptions): string {
  try {
    return new Date(iso).toLocaleTimeString('de-DE', opts ?? {
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return iso }
}

function fmtFull(iso: string): string {
  try {
    return new Date(iso).toLocaleString('de-DE', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  } catch { return iso }
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  confident:    { label: 'Sicher',         color: '#10b981' },
  undecided:    { label: 'Offen',          color: '#f59e0b' },
  contested:    { label: 'Kontrovers',     color: '#ef4444' },
  insufficient: { label: 'Unzureichend',   color: '#6b7280' },
}

const TRIGGER_ICON: Record<string, string> = {
  chat_input:      '💬',
  manual_edit:     '✏️',
  intake:          '📋',
  manual_refresh:  '↺',
}

function ScoreArc({ score }: { score: number }) {
  const r        = 28
  const circ     = 2 * Math.PI * r
  const arc      = circ * 0.75               // 270° arc
  const offset   = arc * (1 - Math.max(0, Math.min(1, score)))
  const startDeg = 135
  const color    = scoreColor(score)

  return (
    <svg width="72" height="72" viewBox="0 0 72 72">
      {/* Track */}
      <circle cx="36" cy="36" r={r}
        fill="none" stroke="var(--border)" strokeWidth="6"
        strokeDasharray={`${arc} ${circ - arc}`}
        strokeLinecap="round"
        style={{ transform: `rotate(${startDeg}deg)`, transformOrigin: '50% 50%' }} />
      {/* Fill */}
      <circle cx="36" cy="36" r={r}
        fill="none" stroke={color} strokeWidth="6"
        strokeDasharray={`${arc - offset} ${circ - (arc - offset)}`}
        strokeLinecap="round"
        style={{ transform: `rotate(${startDeg}deg)`, transformOrigin: '50% 50%',
                 transition: 'stroke-dasharray 0.5s ease' }} />
      <text x="36" y="39" textAnchor="middle" fontSize="13" fontWeight="700"
        fill={color} fontFamily="monospace">
        {Math.round(score * 100)}%
      </text>
    </svg>
  )
}

// ── Diff view ─────────────────────────────────────────────────────────────────

function DiffBadge({ prev, next, label, color }: {
  prev: string | null | undefined
  next: string | null | undefined
  label: string
  color: string
}) {
  if (prev === next) return null
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="px-2 py-0.5 rounded-full text-xs line-through"
          style={{ background: '#ef444422', color: '#ef4444' }}>
          {prev ?? 'n/a'}
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>→</span>
        <span className="px-2 py-0.5 rounded-full text-xs font-medium"
          style={{ background: color + '22', color }}>
          {next ?? 'n/a'}
        </span>
      </div>
    </div>
  )
}

function SnapshotDiff({ prev, curr }: {
  prev: OrchestratorSnapshot
  curr: OrchestratorSnapshot
}) {
  const scoreDelta = curr.orchestrated_score - prev.orchestrated_score
  const scoreUp    = scoreDelta >= 0
  const scoreColor = scoreUp ? '#10b981' : '#ef4444'

  // Compute added/removed items in lists
  const prevConflicts = new Set(prev.key_conflicts)
  const currConflicts = new Set(curr.key_conflicts)
  const newConflicts  = curr.key_conflicts.filter(c => !prevConflicts.has(c))
  const resolvedConflicts = prev.key_conflicts.filter(c => !currConflicts.has(c))

  const prevMissing = new Set(prev.missing_critical)
  const currMissing = new Set(curr.missing_critical)
  const newMissing     = curr.missing_critical.filter(m => !prevMissing.has(m))
  const resolvedMissing = prev.missing_critical.filter(m => !currMissing.has(m))

  const prevAlts = new Map(prev.alternatives.map(a => [a.text, a.score]))
  const rankChanges = curr.alternatives.map((a, i) => {
    const prevScore = prevAlts.get(a.text)
    const delta = prevScore !== undefined ? a.score - prevScore : null
    return { text: a.text, rank: i + 1, delta }
  }).filter(r => r.delta !== null && Math.abs(r.delta as number) >= 0.04)

  const hasChanges =
    prev.leading_hypothesis !== curr.leading_hypothesis ||
    prev.status !== curr.status ||
    Math.abs(scoreDelta) >= 0.02 ||
    newConflicts.length > 0 || resolvedConflicts.length > 0 ||
    newMissing.length > 0 || resolvedMissing.length > 0 ||
    rankChanges.length > 0

  if (!hasChanges) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-2 px-6 text-center">
        <span className="text-2xl">≈</span>
        <p className="text-sm font-medium" style={{ color: 'var(--text)' }}>Keine signifikante Änderung</p>
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          Zwischen diesem und dem vorherigen Snapshot wurde keine klinisch relevante Änderung erkannt.
        </p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {/* Score delta */}
      {Math.abs(scoreDelta) >= 0.02 && (
        <div className="flex items-center gap-3 px-3 py-2 rounded-lg"
          style={{ background: scoreColor + '15', border: `1px solid ${scoreColor}44` }}>
          <span className="text-xl font-bold" style={{ color: scoreColor }}>
            {scoreUp ? '▲' : '▼'}
          </span>
          <div>
            <div className="text-xs font-medium" style={{ color: scoreColor }}>Score</div>
            <div className="text-sm font-mono font-bold" style={{ color: scoreColor }}>
              {Math.round(prev.orchestrated_score * 100)}%
              <span className="mx-1 font-normal">→</span>
              {Math.round(curr.orchestrated_score * 100)}%
              <span className="ml-1 text-xs opacity-70">
                ({scoreUp ? '+' : ''}{Math.round(scoreDelta * 100)}pp)
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Hypothesis change */}
      <DiffBadge
        prev={prev.leading_hypothesis ?? 'Unzureichend'}
        next={curr.leading_hypothesis ?? 'Unzureichend'}
        label="Führende Hypothese"
        color="#3b8eea"
      />

      {/* Status change */}
      <DiffBadge
        prev={prev.status}
        next={curr.status}
        label="Status"
        color={STATUS_META[curr.status]?.color ?? '#6b7280'}
      />

      {/* Conflicts */}
      {(newConflicts.length > 0 || resolvedConflicts.length > 0) && (
        <div className="space-y-1">
          <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Konflikte</div>
          {newConflicts.map((c, i) => (
            <div key={i} className="flex items-start gap-2 text-xs"
              style={{ color: '#ef4444' }}>
              <span className="shrink-0">+ neu:</span>
              <span>{c}</span>
            </div>
          ))}
          {resolvedConflicts.map((c, i) => (
            <div key={i} className="flex items-start gap-2 text-xs"
              style={{ color: '#10b981' }}>
              <span className="shrink-0">✓ gelöst:</span>
              <span className="line-through opacity-60">{c}</span>
            </div>
          ))}
        </div>
      )}

      {/* Missing evidence */}
      {(newMissing.length > 0 || resolvedMissing.length > 0) && (
        <div className="space-y-1">
          <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Fehlende Evidenz</div>
          {newMissing.map((m, i) => (
            <div key={i} className="flex items-start gap-2 text-xs"
              style={{ color: '#f59e0b' }}>
              <span className="shrink-0">+ neu:</span>
              <span>{m}</span>
            </div>
          ))}
          {resolvedMissing.map((m, i) => (
            <div key={i} className="flex items-start gap-2 text-xs"
              style={{ color: '#10b981' }}>
              <span className="shrink-0">✓ erhalten:</span>
              <span className="line-through opacity-60">{m}</span>
            </div>
          ))}
        </div>
      )}

      {/* Alternative score shifts */}
      {rankChanges.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
            Alternativen (Score-Verschiebung ≥ 4pp)
          </div>
          {rankChanges.map((r, i) => {
            const up = (r.delta as number) > 0
            const c  = up ? '#10b981' : '#ef4444'
            return (
              <div key={i} className="flex items-center gap-2 text-xs">
                <span className="flex-1 truncate" style={{ color: 'var(--text-light)' }}>{r.text}</span>
                <span style={{ color: c, fontWeight: 600 }}>
                  {up ? '▲' : '▼'} {Math.round(Math.abs(r.delta as number) * 100)}pp
                </span>
              </div>
            )
          })}
        </div>
      )}

      {/* Next action change */}
      {prev.next_action !== curr.next_action && (
        <div className="space-y-1">
          <div className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Nächste Maßnahme</div>
          <div className="text-xs line-through opacity-50" style={{ color: 'var(--text-light)' }}>
            {prev.next_action}
          </div>
          <div className="flex items-start gap-1.5 px-2.5 py-1.5 rounded-lg"
            style={{ background: 'var(--brand-pale)' }}>
            <span className="shrink-0 text-xs" style={{ color: 'var(--brand)' }}>▶</span>
            <span className="text-xs" style={{ color: 'var(--brand)' }}>{curr.next_action}</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Snapshot detail panel ──────────────────────────────────────────────────────

function SnapshotDetail({ snapshot, isLatest }: { snapshot: OrchestratorSnapshot; isLatest: boolean }) {
  const statusMeta = STATUS_META[snapshot.status] ?? { label: snapshot.status, color: '#6b7280' }

  return (
    <div className="flex flex-col gap-4 py-4 px-4 flex-1 overflow-y-auto">
      {/* Time + trigger */}
      <div className="flex items-center gap-3">
        <div className="flex flex-col">
          <span className="text-xs font-mono font-bold" style={{ color: 'var(--text)' }}>
            {fmtFull(snapshot.recorded_at)}
          </span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {TRIGGER_ICON[snapshot.trigger] ?? '↺'} Auslöser: {snapshot.trigger}
            {isLatest && (
              <span className="ml-2 px-1.5 py-0.5 rounded text-xs font-medium"
                style={{ background: 'var(--brand-pale)', color: 'var(--brand)' }}>
                Aktuell
              </span>
            )}
          </span>
        </div>
      </div>

      {/* Score + hypothesis */}
      <div className="flex items-center gap-4 rounded-xl p-3"
        style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
        <ScoreArc score={snapshot.orchestrated_score} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>
            Führende Hypothese
          </div>
          <div className="text-sm font-semibold leading-tight" style={{ color: 'var(--text)' }}>
            {snapshot.leading_hypothesis ?? (
              <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Unzureichend</span>
            )}
          </div>
          <div className="mt-1.5 inline-flex items-center gap-1">
            <span className="text-xs px-2 py-0.5 rounded-full font-medium"
              style={{ background: statusMeta.color + '18', color: statusMeta.color }}>
              {statusMeta.label}
            </span>
            {snapshot.state_transition && (
              <span className="text-xs px-2 py-0.5 rounded-full"
                style={{ background: 'var(--surface)', color: 'var(--text-muted)',
                         border: '1px solid var(--border)' }}>
                {snapshot.state_transition}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Verdict */}
      <div>
        <div className="text-xs font-medium mb-1.5" style={{ color: 'var(--text-muted)' }}>
          Begründung
        </div>
        <p className="text-xs leading-relaxed" style={{ color: 'var(--text)' }}>
          {snapshot.why}
        </p>
      </div>

      {/* Next action */}
      {snapshot.next_action && (
        <div className="flex items-start gap-2 px-3 py-2 rounded-lg"
          style={{ background: 'var(--brand-pale)', border: '1px solid ' + 'var(--brand)' + '44' }}>
          <span className="text-xs mt-0.5 shrink-0" style={{ color: 'var(--brand)' }}>▶</span>
          <span className="text-xs" style={{ color: 'var(--brand)' }}>{snapshot.next_action}</span>
        </div>
      )}

      {/* Score breakdown */}
      <div>
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-muted)' }}>
          Score-Aufschlüsselung
        </div>
        <div className="space-y-1.5">
          {([
            ['Evidenz',         snapshot.score_breakdown.evidence,  '#3b8eea'],
            ['Leitlinie',       snapshot.score_breakdown.guideline, '#8b5cf6'],
            ['Composite',       snapshot.score_breakdown.composite, '#06b6d4'],
            ['Zeitlicher Bonus', snapshot.score_breakdown.temporal,  '#10b981'],
            ['Konflikt-Malus',  snapshot.score_breakdown.conflict,  '#ef4444'],
          ] as [string, number, string][]).map(([label, val, color]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="text-xs w-28 shrink-0" style={{ color: 'var(--text-muted)' }}>
                {label}
              </span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden"
                style={{ background: 'var(--surface-2)' }}>
                <div className="h-full rounded-full"
                  style={{ width: `${Math.round(Math.abs(val) * 100)}%`, background: color,
                           transition: 'width 0.4s ease' }} />
              </div>
              <span className="text-xs font-mono w-8 text-right shrink-0"
                style={{ color }}>
                {Math.round(val * 100)}%
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Alternatives */}
      {snapshot.alternatives.length > 0 && (
        <div>
          <div className="text-xs font-medium mb-1.5" style={{ color: 'var(--text-muted)' }}>
            Alternative Hypothesen
          </div>
          <div className="space-y-1">
            {snapshot.alternatives.map((a: OrchestratorAlternative) => {
              const aColor = scoreColor(a.score)
              return (
                <div key={a.text} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg"
                  style={{ background: 'var(--surface-2)' }}>
                  <span className="flex-1 text-xs truncate" style={{ color: 'var(--text-light)' }}>
                    {a.text}
                  </span>
                  <span className="text-xs font-mono font-semibold shrink-0"
                    style={{ color: aColor }}>
                    {Math.round(a.score * 100)}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Conflicts */}
      {snapshot.key_conflicts.length > 0 && (
        <div>
          <div className="text-xs font-medium mb-1.5" style={{ color: '#ef4444' }}>
            Konflikte
          </div>
          <ul className="space-y-0.5">
            {snapshot.key_conflicts.map((c, i) => (
              <li key={i} className="text-xs" style={{ color: 'var(--text-light)' }}>
                ⚠ {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Missing */}
      {snapshot.missing_critical.length > 0 && (
        <div>
          <div className="text-xs font-medium mb-1.5" style={{ color: '#f59e0b' }}>
            Fehlende kritische Evidenz
          </div>
          <ul className="space-y-0.5">
            {snapshot.missing_critical.map((m, i) => (
              <li key={i} className="text-xs" style={{ color: 'var(--text-light)' }}>
                ? {m}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

// ── Timeline scrubber ──────────────────────────────────────────────────────────

function TimelineScrubber({
  snapshots,
  selectedIdx,
  onSelect,
}: {
  snapshots:   OrchestratorSnapshot[]
  selectedIdx: number
  onSelect:    (i: number) => void
}) {
  const railRef = useRef<HTMLDivElement>(null)

  if (snapshots.length === 0) return null

  return (
    <div className="shrink-0 px-4 pb-3 pt-2 border-t"
      style={{ borderColor: 'var(--border)' }}>
      {/* Rail */}
      <div ref={railRef} className="relative h-10 flex items-center">
        {/* Background track */}
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 rounded-full"
          style={{ background: 'var(--surface-2)' }} />

        {/* Progress fill up to selected */}
        <div className="absolute left-0 top-1/2 -translate-y-1/2 h-1 rounded-full"
          style={{
            background: 'var(--brand)',
            width: snapshots.length > 1
              ? `${(selectedIdx / (snapshots.length - 1)) * 100}%`
              : '100%',
            transition: 'width 0.2s ease',
          }} />

        {/* Snapshot dots */}
        {snapshots.map((sn, i) => {
          const left = snapshots.length > 1
            ? `${(i / (snapshots.length - 1)) * 100}%`
            : '50%'
          const isSelected = i === selectedIdx
          const statusColor = STATUS_META[sn.status]?.color ?? '#6b7280'

          return (
            <button
              key={sn.id}
              onClick={() => onSelect(i)}
              title={`${fmtFull(sn.recorded_at)} · ${sn.leading_hypothesis ?? 'Unzureichend'}`}
              className="absolute -translate-x-1/2 -translate-y-1/2 top-1/2 rounded-full transition-all"
              style={{
                left,
                width:   isSelected ? 16 : 10,
                height:  isSelected ? 16 : 10,
                background: isSelected ? statusColor : 'var(--surface)',
                border:  `2px solid ${statusColor}`,
                zIndex:  isSelected ? 10 : 5,
                boxShadow: isSelected ? `0 0 0 3px ${statusColor}33` : 'none',
              }}
            />
          )
        })}
      </div>

      {/* Timestamp labels: first + selected + last */}
      <div className="flex justify-between text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
        <span>{fmt(snapshots[0].recorded_at, { hour: '2-digit', minute: '2-digit' })}</span>
        {selectedIdx > 0 && selectedIdx < snapshots.length - 1 && (
          <span className="font-medium" style={{ color: 'var(--brand)' }}>
            ◆ {fmt(snapshots[selectedIdx].recorded_at, { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        )}
        <span>{fmt(snapshots[snapshots.length - 1].recorded_at, { hour: '2-digit', minute: '2-digit' })}</span>
      </div>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

interface Props {
  sessionId: string
}

export default function ReplayPanel({ sessionId }: Props) {
  const [snapshots,    setSnapshots]    = useState<OrchestratorSnapshot[]>([])
  const [selectedIdx,  setSelectedIdx]  = useState(0)
  const [loading,      setLoading]      = useState(false)
  const [error,        setError]        = useState<string | null>(null)
  const [showDiff,     setShowDiff]     = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getSnapshots(sessionId)
      setSnapshots(data.snapshots)
      setSelectedIdx(data.snapshots.length > 0 ? data.snapshots.length - 1 : 0)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Fehler beim Laden')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  const selected = snapshots[selectedIdx] ?? null

  const handleKey = useCallback((e: KeyboardEvent) => {
    if (snapshots.length === 0) return
    if (e.key === 'ArrowLeft')  setSelectedIdx(i => Math.max(0, i - 1))
    if (e.key === 'ArrowRight') setSelectedIdx(i => Math.min(snapshots.length - 1, i + 1))
  }, [snapshots.length])

  useEffect(() => {
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [handleKey])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}>
        <div>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            Epistemic Time Machine
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            {snapshots.length} Snapshots · ← → zum Navigieren
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Step controls */}
          {snapshots.length > 1 && (
            <div className="flex items-center gap-2">
              {/* Diff toggle */}
              {selectedIdx > 0 && (
                <button
                  onClick={() => setShowDiff(v => !v)}
                  className="text-xs px-2.5 py-1 rounded-lg border transition-colors"
                  style={{
                    background:   showDiff ? 'var(--brand-pale)' : 'var(--surface)',
                    color:        showDiff ? 'var(--brand)'      : 'var(--text-muted)',
                    borderColor:  showDiff ? 'var(--brand)'      : 'var(--border)',
                  }}>
                  ⊿ Diff
                </button>
              )}
              <div className="flex items-center rounded-lg overflow-hidden border"
                style={{ borderColor: 'var(--border)' }}>
                <button onClick={() => setSelectedIdx(i => Math.max(0, i - 1))}
                  disabled={selectedIdx === 0}
                  className="w-7 h-7 flex items-center justify-center hover:opacity-70 disabled:opacity-30"
                  style={{ color: 'var(--text-muted)', background: 'var(--surface)' }}>‹</button>
                <span className="px-2 text-xs font-mono"
                  style={{ color: 'var(--text-muted)', background: 'var(--surface)' }}>
                  {selectedIdx + 1}/{snapshots.length}
                </span>
                <button onClick={() => setSelectedIdx(i => Math.min(snapshots.length - 1, i + 1))}
                  disabled={selectedIdx === snapshots.length - 1}
                  className="w-7 h-7 flex items-center justify-center hover:opacity-70 disabled:opacity-30"
                  style={{ color: 'var(--text-muted)', background: 'var(--surface)' }}>›</button>
              </div>
            </div>
          )}
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
      </div>

      {/* Content */}
      {loading && snapshots.length === 0 ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
            style={{ borderColor: 'var(--brand)' }} />
        </div>
      ) : error ? (
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="text-xs px-3 py-2 rounded-lg"
            style={{ background: '#fef2f2', color: '#dc2626' }}>{error}</div>
        </div>
      ) : snapshots.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-6">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl"
            style={{ background: 'var(--surface-2)' }}>⏱</div>
          <p className="text-sm font-medium" style={{ color: 'var(--text)' }}>
            Noch keine Snapshots
          </p>
          <p className="text-xs max-w-xs" style={{ color: 'var(--text-muted)' }}>
            Jedes Mal, wenn der Orchestrator aufgerufen wird, wird ein Snapshot gespeichert.
            Öffne den Orchestrator-Tab um den ersten zu erzeugen.
          </p>
        </div>
      ) : selected ? (
        <>
          {showDiff && selectedIdx > 0 ? (
            <SnapshotDiff
              prev={snapshots[selectedIdx - 1]}
              curr={selected}
            />
          ) : (
            <SnapshotDetail
              snapshot={selected}
              isLatest={selectedIdx === snapshots.length - 1}
            />
          )}
          <TimelineScrubber
            snapshots={snapshots}
            selectedIdx={selectedIdx}
            onSelect={(i) => { setSelectedIdx(i); if (i === 0) setShowDiff(false) }}
          />
        </>
      ) : null}
    </div>
  )
}
