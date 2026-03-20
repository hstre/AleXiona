'use client'

import type { ReasoningResult, Claim } from '@/lib/api'
import { confPct, confColor } from '@/lib/utils'

interface Props {
  reasoning: ReasoningResult
  claims:    Claim[]
}

type Relation = 'supports' | 'contradicts' | 'neutral'

function cellRelation(claimText: string, hypLabel: string, reasoning: ReasoningResult, isLeading: boolean): Relation {
  const t = claimText.toLowerCase()
  if (isLeading) {
    const sup = reasoning.supporting_evidence.some(e => {
      const el = e.toLowerCase()
      return el.includes(t.slice(0, 20)) || t.includes(el.slice(0, 20))
    })
    const con = reasoning.conflicting_evidence.some(e => {
      const el = e.toLowerCase()
      return el.includes(t.slice(0, 20)) || t.includes(el.slice(0, 20))
    })
    if (sup) return 'supports'
    if (con) return 'contradicts'
    return 'neutral'
  }
  // For alternatives: use supporting_claim_ids if available, else neutral
  return 'neutral'
}

const CELL: Record<Relation, { icon: string; bg: string; text: string; border: string }> = {
  supports:    { icon: '▲', bg: '#f0fdf4', text: '#15803d', border: '#86efac' },
  contradicts: { icon: '▼', bg: '#fef2f2', text: '#dc2626', border: '#fca5a5' },
  neutral:     { icon: '·', bg: 'var(--surface)', text: 'var(--text-muted)', border: 'var(--border)' },
}

export default function EvidenceMatrix({ reasoning, claims }: Props) {
  const activeClaims = claims
    .filter(c => c.status === 'active')
    .slice(0, 12)  // cap rows for readability

  const leading = reasoning.leading_hypothesis.length > 28
    ? reasoning.leading_hypothesis.slice(0, 28) + '…'
    : reasoning.leading_hypothesis

  const hypotheses = [
    { label: leading, ess: reasoning.evidence_support_score, isLeading: true },
    ...reasoning.alternatives.map(a => ({
      label:     a.label.length > 20 ? a.label.slice(0, 20) + '…' : a.label,
      ess:       a.evidence_support_score,
      isLeading: false,
    })),
  ]

  if (activeClaims.length === 0 || hypotheses.length === 0) return null

  return (
    <div className="border-t overflow-x-auto shrink-0"
      style={{ background: 'var(--surface)', borderColor: 'var(--border)', maxHeight: '260px' }}>

      <div className="px-4 pt-3 pb-1 flex items-center gap-2">
        <span className="text-xs font-semibold" style={{ color: 'var(--text)' }}>Evidence × Diagnosis Matrix</span>
        <span className="text-xs px-1.5 py-0.5 rounded"
          style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
          {activeClaims.length} evidence · {hypotheses.length} hypotheses
        </span>
        <div className="ml-auto flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-0.5"><span style={{ color: '#15803d' }}>▲</span> supports</span>
          <span className="flex items-center gap-0.5"><span style={{ color: '#dc2626' }}>▼</span> contradicts</span>
          <span>· neutral</span>
        </div>
      </div>

      <table className="w-full text-xs border-collapse" style={{ minWidth: '500px' }}>
        <thead>
          <tr>
            <th className="text-left px-4 py-1.5 sticky left-0 z-10 font-medium"
              style={{ background: 'var(--surface)', color: 'var(--text-muted)',
                borderBottom: '1px solid var(--border)', minWidth: '200px' }}>
              Evidence node
            </th>
            {hypotheses.map((h, i) => (
              <th key={i} className="px-3 py-1.5 text-center font-medium whitespace-nowrap"
                style={{
                  background: h.isLeading ? '#eff6ff' : 'var(--surface)',
                  color: h.isLeading ? '#1d4ed8' : 'var(--text-muted)',
                  borderBottom: '1px solid var(--border)',
                  borderLeft: '1px solid var(--border)',
                  maxWidth: '140px',
                }}>
                <div className="truncate" style={{ maxWidth: '130px' }} title={h.label}>{h.label}</div>
                <div className="font-normal mt-0.5" style={{ color: confColor(h.ess) }}>
                  {confPct(h.ess)}%
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {activeClaims.map((claim, ri) => (
            <tr key={ri} className="hover:brightness-95 transition-all">
              <td className="px-4 py-1.5 sticky left-0 z-10 truncate"
                style={{
                  background: 'var(--surface)',
                  color: 'var(--text)',
                  borderBottom: '1px solid var(--border)',
                  maxWidth: '200px',
                }}
                title={claim.text}>
                {claim.text.length > 42 ? claim.text.slice(0, 42) + '…' : claim.text}
              </td>
              {hypotheses.map((h, ci) => {
                const rel  = cellRelation(claim.text, h.label, reasoning, h.isLeading)
                const meta = CELL[rel]
                return (
                  <td key={ci} className="text-center py-1.5 px-3"
                    title={`${rel} — ${claim.text}`}
                    style={{
                      background:   meta.bg,
                      color:        meta.text,
                      borderBottom: '1px solid var(--border)',
                      borderLeft:   `1px solid ${meta.border}`,
                      fontWeight:   rel !== 'neutral' ? 600 : 400,
                    }}>
                    {meta.icon}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
