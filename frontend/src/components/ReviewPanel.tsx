'use client'

import { useState, useCallback } from 'react'
import type { ReasoningResult, HypothesisCounterfactualResult } from '@/lib/api'
import { hypothesisCounterfactual } from '@/lib/api'
import { confColor, confPct, essLabel, ESS_LABEL_META } from '@/lib/utils'

interface Props {
  reasoning:        ReasoningResult | null
  loading:          boolean
  sessionId:        string | null
  onGenerateReport: () => void
  onClear:          () => void
}

/* ── Circular confidence gauge ───────────────────────────────────────────── */
function ConfidenceGauge({ value }: { value: number }) {
  const pct   = confPct(value)
  const color = confColor(value)
  const level = essLabel(value)
  const meta  = ESS_LABEL_META[level]

  const R     = 36
  const CX    = 48
  const CY    = 48
  const ARC   = 220
  const START = 160
  const filled = (ARC * pct) / 100

  const toRad = (d: number) => (d * Math.PI) / 180
  const pt    = (angle: number) => ({
    x: CX + R * Math.cos(toRad(angle)),
    y: CY + R * Math.sin(toRad(angle)),
  })
  const arcPath = (sweep: number) => {
    if (sweep <= 0) return ''
    const s     = pt(START)
    const e     = pt(START + sweep)
    const large = sweep > 180 ? 1 : 0
    return `M ${s.x} ${s.y} A ${R} ${R} 0 ${large} 1 ${e.x} ${e.y}`
  }

  return (
    <div className="flex flex-col items-center gap-1 shrink-0">
      <svg width="96" height="78" viewBox="0 0 96 82">
        <path d={arcPath(ARC)} fill="none"
          stroke="var(--border)" strokeWidth="6" strokeLinecap="round" />
        <path d={arcPath(filled)} fill="none"
          stroke={color} strokeWidth="6" strokeLinecap="round" />
        <text x={CX} y={CY - 2} textAnchor="middle" dominantBaseline="middle"
          fontSize="14" fontWeight="700" fontFamily="Inter, sans-serif"
          fill="var(--text)">
          {pct}%
        </text>
        <text x={CX} y={CY + 13} textAnchor="middle" dominantBaseline="middle"
          fontSize="7.5" fontWeight="500" fontFamily="Inter, sans-serif"
          fill="var(--text-muted)" letterSpacing="0.07em">
          CONFIDENCE
        </text>
      </svg>
      <span className="text-xs font-semibold capitalize px-2 py-0.5 rounded-md"
        style={{ background: meta.bg, color: meta.text }}>
        {level}
      </span>
    </div>
  )
}

/* ── Horizontal support bar ──────────────────────────────────────────────── */
function SupportBar({ value }: { value: number }) {
  const pct   = confPct(value)
  const bg    = confColor(value)
  const level = essLabel(value)
  const meta  = ESS_LABEL_META[level]
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--border)' }}>
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: bg }} />
      </div>
      <span className="text-xs font-semibold capitalize px-1.5 py-0.5 rounded-md"
        style={{ background: meta.bg, color: meta.text }}>
        {level}
      </span>
    </div>
  )
}

/* ── Section header ──────────────────────────────────────────────────────── */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-xs font-semibold uppercase tracking-wider mb-2"
        style={{ color: 'var(--text-muted)' }}>
        {title}
      </h3>
      {children}
    </section>
  )
}

/* ── Inline counterfactual result ────────────────────────────────────────── */
function CounterfactualInline({ result }: { result: HypothesisCounterfactualResult }) {
  return (
    <div className="mt-2 rounded-xl overflow-hidden"
      style={{ border: '1px solid #e0d7ff', background: '#faf5ff' }}>
      {/* Header */}
      <div className="px-3 py-2 flex items-center gap-1.5"
        style={{ background: '#ede9fe', borderBottom: '1px solid #e0d7ff' }}>
        <span className="text-xs font-semibold" style={{ color: '#5b21b6' }}>
          ↙ Counterfactual
        </span>
        <span className="text-xs" style={{ color: '#7c3aed' }}>
          — What would need to change?
        </span>
      </div>

      <div className="p-3 space-y-2.5">
        {/* Required changes */}
        {result.required_changes.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-1.5" style={{ color: '#6d28d9' }}>
              These findings would need to be different:
            </div>
            <div className="space-y-1">
              {result.required_changes.map((c, i) => (
                <div key={i} className="flex items-start gap-2 text-xs px-2.5 py-1.5 rounded-lg"
                  style={{ background: '#ede9fe', color: '#3b0764' }}>
                  <span className="shrink-0 mt-0.5" style={{ color: '#7c3aed' }}>✗</span>
                  {c}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Critical evidence */}
        {result.critical_evidence.length > 0 && (
          <div>
            <div className="text-xs font-medium mb-1.5" style={{ color: '#6d28d9' }}>
              Decisive supporting evidence:
            </div>
            <div className="space-y-1">
              {result.critical_evidence.map((e, i) => (
                <div key={i} className="flex items-start gap-2 text-xs px-2.5 py-1.5 rounded-lg"
                  style={{ background: '#f5f3ff', color: '#4c1d95', border: '1px solid #e0d7ff' }}>
                  <span className="shrink-0 mt-0.5" style={{ color: '#7c3aed' }}>⬟</span>
                  {e}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Alternative if false */}
        {result.alternative_if_false && (
          <div className="flex items-start gap-2 text-xs px-2.5 py-1.5 rounded-lg"
            style={{ background: '#fef3c7', border: '1px solid #fde68a', color: '#78350f' }}>
            <span className="shrink-0 font-medium" style={{ color: '#92400e' }}>→</span>
            <span>
              <span className="font-medium">If false: </span>
              {result.alternative_if_false}
            </span>
          </div>
        )}

        {/* Reasoning trace */}
        {result.reasoning_trace && (
          <p className="text-xs italic px-1" style={{ color: '#7c3aed' }}>
            {result.reasoning_trace}
          </p>
        )}
      </div>
    </div>
  )
}

/* ── Counterfactual button ────────────────────────────────────────────────── */
function CounterfactualButton({
  hypothesis,
  sessionId,
}: {
  hypothesis: string
  sessionId:  string | null
}) {
  const [open,    setOpen]    = useState(false)
  const [loading, setLoading] = useState(false)
  const [result,  setResult]  = useState<HypothesisCounterfactualResult | null>(null)
  const [error,   setError]   = useState('')

  const run = useCallback(async () => {
    if (!sessionId) return
    if (open && result) { setOpen(false); return }
    if (open) { setOpen(false); return }

    setLoading(true)
    setError('')
    setOpen(true)
    try {
      const r = await hypothesisCounterfactual(sessionId, hypothesis)
      setResult(r)
    } catch (e: any) {
      setError(e.message || 'Request failed')
      setOpen(false)
    } finally {
      setLoading(false)
    }
  }, [sessionId, hypothesis, open, result])

  return (
    <div>
      <button
        onClick={run}
        disabled={!sessionId || loading}
        title="Was müsste sich ändern, damit diese Hypothese falsch ist?"
        className="mt-2 flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg font-medium transition-all disabled:opacity-40"
        style={{
          background: open && result ? '#ede9fe' : 'var(--surface)',
          color:      open && result ? '#5b21b6' : 'var(--text-muted)',
          border:     `1px solid ${open && result ? '#c4b5fd' : 'var(--border)'}`,
        }}>
        {loading ? (
          <>
            <span className="w-3 h-3 rounded-full border border-t-transparent animate-spin"
              style={{ borderColor: '#7c3aed' }} />
            Analyzing…
          </>
        ) : (
          <>
            <span style={{ color: '#7c3aed' }}>↙</span>
            {open && result ? 'Hide counterfactual' : 'What would refute this?'}
          </>
        )}
      </button>

      {error && (
        <p className="text-xs mt-1 px-1" style={{ color: '#b91c1c' }}>{error}</p>
      )}

      {open && result && !loading && (
        <CounterfactualInline result={result} />
      )}

      {open && loading && (
        <div className="mt-2 rounded-xl p-4 space-y-2 animate-pulse"
          style={{ background: '#faf5ff', border: '1px solid #e0d7ff' }}>
          {[90, 70, 85, 60].map((w, i) => (
            <div key={i} className="h-3 rounded-lg" style={{ width: `${w}%`, background: '#ede9fe' }} />
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Main component ──────────────────────────────────────────────────────── */
export default function ReviewPanel({ reasoning, loading, sessionId, onGenerateReport, onClear }: Props) {
  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--surface)' }}>

      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between shrink-0"
        style={{ borderColor: 'var(--border)' }}>
        <div>
          <span className="font-semibold text-sm">AI Reviewer</span>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>AI-assisted · not a diagnosis</p>
        </div>
        <div className="w-2 h-2 rounded-full"
          style={{
            background: loading ? '#f59e0b' : reasoning ? '#22c55e' : 'var(--border)',
            animation: (loading || reasoning) ? 'pulse 2s ease-in-out infinite' : 'none',
          }} />
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">

        {/* Empty state */}
        {!reasoning && !loading && (
          <div className="text-center py-8">
            <div className="text-3xl mb-2 opacity-20">🔍</div>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Reasoning summary appears after evidence is added
            </p>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="space-y-3 animate-pulse">
            {[80, 60, 90, 50, 70].map((w, i) => (
              <div key={i} className="h-4 rounded-lg" style={{ width: `${w}%`, background: 'var(--border)' }} />
            ))}
          </div>
        )}

        {reasoning && !loading && (
          <>
            {/* Leading hypothesis — with gauge + bar + counterfactual */}
            <Section title="Current Leading Hypothesis">
              <div className="rounded-xl p-3 border-l-4"
                style={{ background: 'var(--brand-pale)', borderLeftColor: 'var(--brand)' }}>
                <div className="flex items-start gap-3">
                  <ConfidenceGauge value={reasoning.evidence_support_score} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium mb-2" style={{ color: 'var(--text)' }}>
                      {reasoning.leading_hypothesis}
                    </p>
                    <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>
                      Evidence support
                    </div>
                    <SupportBar value={reasoning.evidence_support_score} />
                  </div>
                </div>
                <CounterfactualButton
                  hypothesis={reasoning.leading_hypothesis}
                  sessionId={sessionId}
                />
              </div>
            </Section>

            {/* Supporting evidence */}
            {reasoning.supporting_evidence.length > 0 && (
              <Section title="Supporting Evidence">
                <div className="space-y-1.5">
                  {reasoning.supporting_evidence.map((e, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2"
                      style={{ background: '#f0fdf4', border: '1px solid #bbf7d0' }}>
                      <span className="text-xs shrink-0" style={{ color: '#15803d' }}>✓</span>
                      <span className="text-xs" style={{ color: '#14532d' }}>{e}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Conflicting evidence */}
            {reasoning.conflicting_evidence.length > 0 && (
              <Section title="Conflicting Evidence">
                <div className="space-y-1.5">
                  {reasoning.conflicting_evidence.map((e, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2"
                      style={{ background: '#fef2f2', border: '1px solid #fecaca' }}>
                      <span className="text-xs shrink-0" style={{ color: '#b91c1c' }}>⚡</span>
                      <span className="text-xs" style={{ color: '#7f1d1d' }}>{e}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Missing evidence */}
            {reasoning.missing_evidence.length > 0 && (
              <Section title="Missing Evidence">
                <div className="space-y-2">
                  {reasoning.missing_evidence.map((m, i) => (
                    <div key={i} className="rounded-xl p-3"
                      style={{ background: '#fffbeb', border: '1px solid #fde68a' }}>
                      <div className="flex items-start gap-2 mb-1">
                        <span className="text-sm shrink-0">⚠</span>
                        <span className="text-xs font-medium" style={{ color: '#92400e' }}>
                          {m.test_or_type}
                        </span>
                      </div>
                      <p className="text-xs ml-5" style={{ color: '#78350f' }}>{m.description}</p>
                      <p className="text-xs ml-5 mt-0.5 italic" style={{ color: '#a16207' }}>
                        Needed to clarify: {m.needed_for}
                      </p>
                      {m.differentiates_between && m.differentiates_between.length >= 2 && (
                        <div className="ml-5 mt-1.5 flex flex-wrap gap-1">
                          <span className="text-xs" style={{ color: '#a16207' }}>Differentiates:</span>
                          {m.differentiates_between.map((h, hi) => (
                            <span key={hi} className="text-xs px-1.5 py-0.5 rounded-md font-medium"
                              style={{ background: '#fef3c7', color: '#92400e', border: '1px solid #fde68a' }}>
                              {h}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Focus points */}
            {reasoning.focus_points.length > 0 && (
              <Section title="Focus Points">
                <div className="space-y-1.5">
                  {reasoning.focus_points.map((f, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2"
                      style={{ background: 'var(--brand-pale)' }}>
                      <span className="text-xs mt-0.5 shrink-0" style={{ color: 'var(--brand)' }}>→</span>
                      <span className="text-xs" style={{ color: 'var(--text)' }}>{f}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Alternative hypotheses — each with its own counterfactual button */}
            {reasoning.alternatives.length > 0 && (
              <Section title="Alternative Hypotheses">
                <div className="space-y-2">
                  {reasoning.alternatives.map((alt, i) => (
                    <div key={i} className="rounded-xl p-3"
                      style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-medium" style={{ color: 'var(--text)' }}>
                          {alt.label}
                        </span>
                        <span className="text-xs font-semibold capitalize px-1.5 py-0.5 rounded-md"
                          style={{
                            background: ESS_LABEL_META[essLabel(alt.evidence_support_score)].bg,
                            color:      ESS_LABEL_META[essLabel(alt.evidence_support_score)].text,
                          }}>
                          {essLabel(alt.evidence_support_score)}
                        </span>
                      </div>
                      <SupportBar value={alt.evidence_support_score} />
                      <CounterfactualButton
                        hypothesis={alt.label}
                        sessionId={sessionId}
                      />
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Disclaimer */}
            <p className="text-xs italic text-center px-2"
              style={{ color: 'var(--text-light)', borderTop: '1px solid var(--border)', paddingTop: '8px' }}>
              This is a reasoning aid, not a clinical decision. All conclusions must be verified by a qualified clinician.
            </p>
          </>
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t space-y-2 shrink-0" style={{ borderColor: 'var(--border)' }}>
        <button onClick={onGenerateReport} disabled={!reasoning}
          className="w-full py-2 rounded-xl text-sm font-semibold transition-all disabled:opacity-40"
          style={{ background: 'var(--brand)', color: 'white' }}>
          Generate Report
        </button>
        <button onClick={onClear} disabled={!reasoning}
          className="w-full py-2 rounded-xl text-sm transition-all disabled:opacity-30"
          style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
          Clear Review
        </button>
      </div>
    </div>
  )
}
