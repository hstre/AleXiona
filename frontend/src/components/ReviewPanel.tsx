'use client'

import type { ReasoningResult } from '@/lib/api'
import { confColor, confPct, essLabel, ESS_LABEL_META } from '@/lib/utils'

interface Props {
  reasoning:        ReasoningResult | null
  loading:          boolean
  onGenerateReport: () => void
  onClear:          () => void
}

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

export default function ReviewPanel({ reasoning, loading, onGenerateReport, onClear }: Props) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--border)' }}>
        <div>
          <span className="font-semibold text-sm">Clinical Reasoning</span>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>AI-assisted · not a diagnosis</p>
        </div>
        <div className="w-2 h-2 rounded-full animate-pulse"
          style={{ background: loading ? '#f59e0b' : reasoning ? '#22c55e' : 'var(--border)' }} />
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
            {/* Leading hypothesis */}
            <Section title="Current Leading Hypothesis">
              <div className="rounded-xl p-3 border-l-4"
                style={{ background: 'var(--brand-pale)', borderLeftColor: 'var(--brand)' }}>
                <p className="text-sm font-medium mb-2" style={{ color: 'var(--text)' }}>
                  {reasoning.leading_hypothesis}
                </p>
                <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>
                  Evidence support
                </div>
                <SupportBar value={reasoning.evidence_support_score} />
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

            {/* Missing evidence (diagnosis-linked) */}
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

            {/* Alternative hypotheses */}
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
      <div className="p-3 border-t space-y-2" style={{ borderColor: 'var(--border)' }}>
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
