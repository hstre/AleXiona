'use client'

import type { AnalysisResult } from '@/lib/api'
import { confColor, confPct } from '@/lib/utils'

interface Props {
  analysis: AnalysisResult | null
  loading: boolean
  onGenerateReport: () => void
  onClear: () => void
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = confPct(value)
  const bg = confColor(value)
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--border)' }}>
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: bg }} />
      </div>
      <span className="text-xs font-bold tabular-nums w-8 text-right"
        style={{ color: bg }}>{pct}%</span>
    </div>
  )
}

export default function ReviewPanel({ analysis, loading, onGenerateReport, onClear }: Props) {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--border)' }}>
        <span className="font-semibold text-sm">AI Reviewer</span>
        <div className="w-2 h-2 rounded-full animate-pulse"
          style={{ background: loading ? '#f59e0b' : analysis ? '#22c55e' : 'var(--border)' }} />
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Empty state */}
        {!analysis && !loading && (
          <div className="text-center py-8">
            <div className="text-3xl mb-2 opacity-20">🔍</div>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Analysis appears after you add evidence
            </p>
          </div>
        )}

        {loading && (
          <div className="space-y-3 animate-pulse">
            {[80, 60, 90, 50].map((w, i) => (
              <div key={i} className="h-4 rounded-lg" style={{ width: `${w}%`, background: 'var(--border)' }} />
            ))}
          </div>
        )}

        {analysis && !loading && (
          <>
            {/* Primary hypothesis */}
            <section>
              <h3 className="text-xs font-semibold uppercase tracking-wider mb-2"
                style={{ color: 'var(--text-muted)' }}>
                Primary Hypothesis
              </h3>
              <div className="rounded-xl p-3 border-l-4"
                style={{ background: 'var(--brand-pale)', borderLeftColor: 'var(--brand)' }}>
                <p className="text-sm font-medium mb-2" style={{ color: 'var(--text)' }}>
                  {analysis.primary_hypothesis}
                </p>
                <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>Confidence</div>
                <ConfidenceBar value={analysis.confidence} />
              </div>
            </section>

            {/* Missing Evidence */}
            {analysis.missing_evidence.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-2"
                  style={{ color: 'var(--text-muted)' }}>
                  Missing Evidence
                </h3>
                <div className="space-y-1.5">
                  {analysis.missing_evidence.map((item, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2"
                      style={{ background: '#fffbeb', border: '1px solid #fde68a' }}>
                      <span className="text-sm shrink-0">⚠</span>
                      <span className="text-xs" style={{ color: '#92400e' }}>{item}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Focus points */}
            {analysis.focus_points.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-2"
                  style={{ color: 'var(--text-muted)' }}>
                  Focus
                </h3>
                <div className="space-y-1.5">
                  {analysis.focus_points.map((item, i) => (
                    <div key={i} className="flex items-start gap-2 rounded-lg px-3 py-2"
                      style={{ background: 'var(--brand-pale)' }}>
                      <span className="text-xs mt-0.5 shrink-0" style={{ color: 'var(--brand)' }}>→</span>
                      <span className="text-xs" style={{ color: 'var(--text)' }}>{item}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {/* Alternatives */}
            {analysis.alternatives.length > 0 && (
              <section>
                <h3 className="text-xs font-semibold uppercase tracking-wider mb-2"
                  style={{ color: 'var(--text-muted)' }}>
                  Alternative Hypotheses
                </h3>
                <div className="space-y-2">
                  {analysis.alternatives.map((alt, i) => (
                    <div key={i} className="rounded-xl p-3"
                      style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-medium" style={{ color: 'var(--text)' }}>
                          {alt.label}
                        </span>
                        <span className="text-xs font-bold px-1.5 py-0.5 rounded-md"
                          style={{ background: 'var(--border)', color: 'var(--text-muted)' }}>
                          {confPct(alt.confidence)}%
                        </span>
                      </div>
                      <ConfidenceBar value={alt.confidence} />
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>

      {/* Footer buttons */}
      <div className="p-3 border-t space-y-2" style={{ borderColor: 'var(--border)' }}>
        <button
          onClick={onGenerateReport}
          disabled={!analysis}
          className="w-full py-2 rounded-xl text-sm font-semibold transition-all disabled:opacity-40"
          style={{ background: 'var(--brand)', color: 'white' }}
        >
          Generate Report
        </button>
        <button
          onClick={onClear}
          disabled={!analysis}
          className="w-full py-2 rounded-xl text-sm transition-all disabled:opacity-30"
          style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
        >
          Clear Review
        </button>
      </div>
    </div>
  )
}
