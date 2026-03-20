'use client'

import { useState, useCallback } from 'react'
import type { Claim, CounterfactualResult } from '@/lib/api'
import { runCounterfactual } from '@/lib/api'
import { confPct, confColor, CLAIM_TYPE_META, getTypeMeta } from '@/lib/utils'

interface Props {
  claims:    Claim[]
  sessionId: string
}

interface ResultState {
  claimId:  string
  result:   CounterfactualResult
  loading?: false
}
interface LoadingState {
  claimId: string
  loading: true
}
type CfState = ResultState | LoadingState

export default function CounterfactualPanel({ claims, sessionId }: Props) {
  const [cfState, setCfState] = useState<CfState | null>(null)
  const [error,   setError]   = useState<string | null>(null)

  const activeClaims = claims.filter(c => c.status === 'active' && c.claimId)

  const run = useCallback(async (claim: Claim) => {
    if (!claim.claimId) return
    setError(null)
    setCfState({ claimId: claim.claimId, loading: true })
    try {
      const result = await runCounterfactual(sessionId, claim.claimId)
      setCfState({ claimId: claim.claimId, result })
    } catch (e: any) {
      setCfState(null)
      setError(e.message ?? 'Counterfactual failed')
    }
  }, [sessionId])

  const loadingId = cfState?.loading ? cfState.claimId : null
  const result    = cfState && !cfState.loading ? (cfState as ResultState).result : null

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}>
        <div className="font-semibold text-sm" style={{ color: 'var(--text)' }}>What-If? Counterfactual</div>
        <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
          Click an evidence node to see how removing it shifts the diagnosis scores
        </p>
      </div>

      <div className="flex flex-1 overflow-hidden">

        {/* Left: claim list */}
        <div className="w-56 shrink-0 border-r overflow-y-auto"
          style={{ borderColor: 'var(--border)' }}>
          {activeClaims.length === 0 && (
            <p className="p-4 text-xs" style={{ color: 'var(--text-muted)' }}>No active evidence nodes.</p>
          )}
          {activeClaims.map(claim => {
            const meta      = getTypeMeta(claim.claim_type)
            const isLoading = loadingId === claim.claimId
            const isActive  = cfState && !cfState.loading && (cfState as ResultState).claimId === claim.claimId
            return (
              <button
                key={claim.claimId}
                onClick={() => run(claim)}
                disabled={!!loadingId}
                className="w-full text-left px-3 py-2.5 border-b transition-colors hover:brightness-95 disabled:opacity-50"
                style={{
                  borderColor: 'var(--border)',
                  background: isActive ? meta.bg : 'var(--surface)',
                  borderLeft: isActive ? `3px solid ${meta.color}` : '3px solid transparent',
                }}>
                <div className="flex items-start gap-1.5">
                  <span className="shrink-0 mt-0.5">{meta.icon}</span>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs leading-snug line-clamp-2"
                      style={{ color: 'var(--text)' }}>
                      {claim.text.length > 55 ? claim.text.slice(0, 55) + '…' : claim.text}
                    </p>
                    <div className="flex items-center gap-1.5 mt-1">
                      <span className="text-xs font-mono"
                        style={{ color: confColor(claim.evidence_support_score) }}>
                        {confPct(claim.evidence_support_score)}%
                      </span>
                      {isLoading && (
                        <span className="text-xs animate-pulse" style={{ color: 'var(--brand)' }}>running…</span>
                      )}
                    </div>
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        {/* Right: result */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {error && (
            <div className="text-xs px-3 py-2 rounded-lg mb-3"
              style={{ background: '#fef2f2', color: '#dc2626' }}>
              {error}
            </div>
          )}

          {!result && !loadingId && !error && (
            <div className="flex flex-col items-center justify-center h-full gap-2"
              style={{ color: 'var(--text-muted)' }}>
              <span className="text-2xl">💡</span>
              <p className="text-xs text-center">Select an evidence node on the left to run the counterfactual analysis</p>
            </div>
          )}

          {loadingId && (
            <div className="flex flex-col items-center justify-center h-full gap-2">
              <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
                style={{ borderColor: 'var(--brand)' }} />
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Running counterfactual…</p>
            </div>
          )}

          {result && (
            <div className="space-y-4">
              {/* Excluded claim */}
              <div className="p-3 rounded-lg text-xs"
                style={{ background: 'var(--surface-2)', color: 'var(--text)' }}>
                <span className="font-semibold" style={{ color: 'var(--text-muted)' }}>Excluded: </span>
                {result.excluded_claim_text}
              </div>

              {/* Hypothesis shifts */}
              {result.shifts.length > 0 && (
                <div>
                  <p className="text-xs font-semibold mb-2" style={{ color: 'var(--text)' }}>
                    Diagnosis Score Shifts
                  </p>
                  <div className="space-y-3">
                    {result.shifts.map((s, i) => {
                      const delta    = s.score_after - s.score_before
                      const pctBefore = confPct(s.score_before)
                      const pctAfter  = confPct(s.score_after)
                      const negative  = delta < 0
                      return (
                        <div key={i}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-medium truncate"
                              style={{ color: 'var(--text)', maxWidth: '60%' }}>
                              {s.hypothesis}
                            </span>
                            <span className="text-xs font-mono font-semibold"
                              style={{ color: negative ? '#dc2626' : '#16a34a' }}>
                              {negative ? '' : '+'}{Math.round(delta * 100)}%
                            </span>
                          </div>
                          {/* Bar */}
                          <div className="relative h-4 rounded overflow-hidden"
                            style={{ background: 'var(--surface-2)' }}>
                            {/* Before bar */}
                            <div className="absolute top-0 left-0 h-full rounded transition-all"
                              style={{ width: `${pctBefore}%`, background: '#94a3b8', opacity: 0.5 }} />
                            {/* After bar */}
                            <div className="absolute top-0 left-0 h-full rounded transition-all"
                              style={{
                                width: `${pctAfter}%`,
                                background: confColor(s.score_after),
                              }} />
                            <span className="absolute inset-0 flex items-center px-2 text-xs font-mono text-white"
                              style={{ textShadow: '0 1px 2px rgba(0,0,0,0.4)' }}>
                              {pctBefore}% → {pctAfter}%
                            </span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Reasoning trace */}
              {result.reasoning_trace && (
                <div>
                  <p className="text-xs font-semibold mb-1" style={{ color: 'var(--text)' }}>Reasoning</p>
                  <p className="text-xs leading-relaxed p-3 rounded-lg"
                    style={{ background: 'var(--surface-2)', color: 'var(--text)', lineHeight: 1.7 }}>
                    {result.reasoning_trace}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
