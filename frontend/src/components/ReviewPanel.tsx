'use client'

import type { ReasoningResult } from '@/lib/api'
import { confColor, confPct, essLabel, ESS_LABEL_META } from '@/lib/utils'

interface Props {
  reasoning:        ReasoningResult | null
  loading:          boolean
  onGenerateReport: () => void
  onClear:          () => void
}

/* ── Circular confidence gauge ────────────────────────────────────────── */
function ConfidenceGauge({ value }: { value: number }) {
  const pct    = confPct(value)
  const label  = essLabel(value)
  const color  = confColor(value)

  // SVG arc math — 220° sweep, starting at 160° (bottom-left)
  const R      = 38
  const CX     = 50
  const CY     = 50
  const ARC    = 220                // total degrees
  const START  = 160                // start angle (degrees, clockwise from 3 o'clock)
  const filled = (ARC * pct) / 100

  const toRad  = (d: number) => (d * Math.PI) / 180
  const pt = (angle: number) => ({
    x: CX + R * Math.cos(toRad(angle)),
    y: CY + R * Math.sin(toRad(angle)),
  })

  const arcPath = (endDeg: number, sweep: number) => {
    const s = pt(START)
    const e = pt(START + sweep)
    const large = sweep > 180 ? 1 : 0
    return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`
  }

  const trackEnd   = ARC
  const fillEnd    = filled

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="100" height="80" viewBox="0 0 100 85">
        {/* Track */}
        <path
          d={arcPath(START + trackEnd, trackEnd)}
          fill="none"
          stroke="rgba(100,130,180,0.15)"
          strokeWidth="7"
          strokeLinecap="round"
        />
        {/* Fill */}
        <path
          d={arcPath(START + fillEnd, Math.max(fillEnd, 0.1))}
          fill="none"
          stroke={color}
          strokeWidth="7"
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${color}60)` }}
        />
        {/* Center label */}
        <text x="50" y="50" textAnchor="middle" dominantBaseline="middle"
          fontSize="15" fontWeight="700" fontFamily="Inter, sans-serif"
          fill="var(--text)">
          {pct}%
        </text>
        <text x="50" y="64" textAnchor="middle" dominantBaseline="middle"
          fontSize="8" fontWeight="500" fontFamily="Inter, sans-serif"
          fill="var(--text-muted)" letterSpacing="0.08em">
          CONFIDENCE
        </text>
      </svg>
      <span className="badge" style={{
        background: ESS_LABEL_META[label].bg,
        color:      ESS_LABEL_META[label].text,
        border:     `1px solid ${ESS_LABEL_META[label].text}30`,
        fontSize:   '10px',
      }}>
        {label.toUpperCase()}
      </span>
    </div>
  )
}

/* ── Small bar for alternatives ──────────────────────────────────────── */
function MiniBar({ value }: { value: number }) {
  const pct   = confPct(value)
  const color = confColor(value)
  return (
    <div className="conf-track flex-1">
      <div className="conf-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

/* ── Section wrapper ─────────────────────────────────────────────────── */
function Section({ title, icon, children }: { title: string; icon?: string; children: React.ReactNode }) {
  return (
    <section className="animate-fade-in">
      <div className="flex items-center gap-2 mb-2.5">
        {icon && <span style={{ fontSize: '12px' }}>{icon}</span>}
        <span className="section-label">{title}</span>
      </div>
      {children}
    </section>
  )
}

/* ── Evidence item ───────────────────────────────────────────────────── */
function EvidenceItem({
  text, variant,
}: { text: string; variant: 'support' | 'conflict' | 'focus' }) {
  const cfg = {
    support:  { bg: 'rgba(34,197,94,0.07)',  border: 'rgba(34,197,94,0.2)',  dot: '#4ade80',  dotGlow: '#4ade8040' },
    conflict: { bg: 'rgba(239,68,68,0.07)',  border: 'rgba(239,68,68,0.2)',  dot: '#f87171',  dotGlow: '#f8717140' },
    focus:    { bg: 'rgba(59,142,234,0.07)', border: 'rgba(59,142,234,0.2)', dot: 'var(--brand)', dotGlow: 'var(--brand-glow)' },
  }[variant]

  return (
    <div className="flex items-start gap-2.5 rounded-lg px-3 py-2.5"
      style={{ background: cfg.bg, border: `1px solid ${cfg.border}` }}>
      <span className="mt-0.5 shrink-0 w-1.5 h-1.5 rounded-full"
        style={{ background: cfg.dot, boxShadow: `0 0 6px ${cfg.dotGlow}`, marginTop: '5px' }} />
      <span className="text-xs leading-relaxed" style={{ color: 'var(--text)' }}>{text}</span>
    </div>
  )
}

/* ── Missing evidence item ───────────────────────────────────────────── */
function MissingItem({ test, desc, needed }: { test: string; desc: string; needed: string }) {
  return (
    <div className="rounded-xl p-3"
      style={{ background: 'rgba(245,158,11,0.07)', border: '1px solid rgba(245,158,11,0.2)' }}>
      <div className="flex items-center gap-2 mb-1">
        <span style={{ fontSize: '11px' }}>⚠</span>
        <span className="text-xs font-semibold" style={{ color: '#fbbf24' }}>{test}</span>
      </div>
      <p className="text-xs leading-relaxed mb-1" style={{ color: 'var(--text-muted)', paddingLeft: '19px' }}>{desc}</p>
      <p className="text-xs italic" style={{ color: 'var(--text-light)', paddingLeft: '19px' }}>
        Clarifies: {needed}
      </p>
    </div>
  )
}

/* ── Alternative hypothesis row ──────────────────────────────────────── */
function AltRow({ label, score, rank }: { label: string; score: number; rank: number }) {
  const pct   = confPct(score)
  const color = confColor(score)
  const lvl   = essLabel(score)
  const meta  = ESS_LABEL_META[lvl]

  return (
    <div className="rounded-xl p-3 transition-all"
      style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-mono font-medium shrink-0"
            style={{ color: 'var(--text-light)', width: '16px' }}>
            {rank}.
          </span>
          <span className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>
            {label}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          <span className="text-xs font-bold tabular-nums" style={{ color }}>{pct}%</span>
          <span className="badge" style={{
            background: meta.bg, color: meta.text,
            border: `1px solid ${meta.text}30`, fontSize: '9px', padding: '1px 6px',
          }}>
            {lvl.toUpperCase()}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-xs shrink-0" style={{ color: 'var(--text-light)', width: '16px' }} />
        <MiniBar value={score} />
      </div>
    </div>
  )
}

/* ── Main component ──────────────────────────────────────────────────── */
export default function ReviewPanel({ reasoning, loading, onGenerateReport, onClear }: Props) {
  const hasReasoning = !!reasoning && !loading

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--surface)' }}>

      {/* Header */}
      <div className="panel-header shrink-0">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm tracking-tight" style={{ color: 'var(--text)' }}>
              AI Reviewer
            </span>
            {hasReasoning && (
              <span className="badge badge-green">Active</span>
            )}
          </div>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            Clinical reasoning · not a diagnosis
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {loading && (
            <div className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--accent)' }}>
              <div className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: 'var(--accent)' }} />
              Analyzing
            </div>
          )}
          {!loading && !reasoning && (
            <div className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--border-strong)' }} />
          )}
          {!loading && reasoning && (
            <div className="w-1.5 h-1.5 rounded-full"
              style={{ background: 'var(--accent-green)', boxShadow: '0 0 8px var(--accent-green)' }} />
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">

        {/* Empty state */}
        {!reasoning && !loading && (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--text-light)" strokeWidth="1.5">
                <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
              </svg>
            </div>
            <p className="text-sm font-medium mb-1" style={{ color: 'var(--text-muted)' }}>
              No reasoning yet
            </p>
            <p className="text-xs" style={{ color: 'var(--text-light)' }}>
              Add evidence to generate an AI review
            </p>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-4 animate-fade-in">
            <div className="flex justify-center py-4">
              <div className="skeleton w-24 h-24 rounded-full" />
            </div>
            {[85, 65, 90, 55, 75].map((w, i) => (
              <div key={i} className="skeleton h-3" style={{ width: `${w}%` }} />
            ))}
          </div>
        )}

        {hasReasoning && (
          <>
            {/* Leading hypothesis + gauge */}
            <Section title="Leading Hypothesis">
              <div className="rounded-xl p-4" style={{
                background: 'linear-gradient(135deg, rgba(59,142,234,0.1) 0%, rgba(15,184,184,0.06) 100%)',
                border: '1px solid rgba(59,142,234,0.25)',
              }}>
                <div className="flex items-start gap-4">
                  <div className="shrink-0">
                    <ConfidenceGauge value={reasoning.evidence_support_score} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold leading-snug mb-3"
                      style={{ color: 'var(--text)' }}>
                      {reasoning.leading_hypothesis}
                    </p>
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs" style={{ color: 'var(--text-muted)' }}>
                        <span>Evidence support</span>
                        <span className="font-medium tabular-nums" style={{ color: 'var(--brand-light)' }}>
                          {confPct(reasoning.evidence_support_score)}%
                        </span>
                      </div>
                      <div className="conf-track">
                        <div className="conf-fill" style={{
                          width: `${confPct(reasoning.evidence_support_score)}%`,
                          background: `linear-gradient(90deg, var(--brand) 0%, var(--teal) 100%)`,
                        }} />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </Section>

            {/* Supporting evidence */}
            {reasoning.supporting_evidence.length > 0 && (
              <Section title="Supporting Evidence" icon="●">
                <div className="space-y-1.5">
                  {reasoning.supporting_evidence.map((e, i) => (
                    <EvidenceItem key={i} text={e} variant="support" />
                  ))}
                </div>
              </Section>
            )}

            {/* Conflicting evidence */}
            {reasoning.conflicting_evidence.length > 0 && (
              <Section title="Conflicting Evidence" icon="●">
                <div className="space-y-1.5">
                  {reasoning.conflicting_evidence.map((e, i) => (
                    <EvidenceItem key={i} text={e} variant="conflict" />
                  ))}
                </div>
              </Section>
            )}

            {/* Missing evidence */}
            {reasoning.missing_evidence.length > 0 && (
              <Section title="Missing Evidence">
                <div className="space-y-2">
                  {reasoning.missing_evidence.map((m, i) => (
                    <MissingItem key={i}
                      test={m.test_or_type}
                      desc={m.description}
                      needed={m.needed_for}
                    />
                  ))}
                </div>
              </Section>
            )}

            {/* Focus points */}
            {reasoning.focus_points.length > 0 && (
              <Section title="Focus Points">
                <div className="space-y-1.5">
                  {reasoning.focus_points.map((f, i) => (
                    <EvidenceItem key={i} text={f} variant="focus" />
                  ))}
                </div>
              </Section>
            )}

            {/* Alternatives */}
            {reasoning.alternatives.length > 0 && (
              <Section title="Alternative Diagnoses">
                <div className="space-y-2">
                  {reasoning.alternatives.map((alt, i) => (
                    <AltRow key={i}
                      label={alt.label}
                      score={alt.evidence_support_score}
                      rank={i + 1}
                    />
                  ))}
                </div>
              </Section>
            )}

            {/* Disclaimer */}
            <div className="rounded-lg px-3 py-2.5 text-xs italic text-center"
              style={{ background: 'rgba(100,130,180,0.06)', border: '1px solid var(--border-light)', color: 'var(--text-light)' }}>
              Reasoning aid only — all conclusions require clinician verification.
            </div>
          </>
        )}
      </div>

      {/* Footer actions */}
      <div className="p-3 border-t shrink-0 space-y-2" style={{ borderColor: 'var(--border-light)' }}>
        <button onClick={onGenerateReport} disabled={!reasoning}
          className="btn-primary w-full">
          Generate Report
        </button>
        <button onClick={onClear} disabled={!reasoning}
          className="btn-ghost w-full">
          Clear Review
        </button>
      </div>
    </div>
  )
}
