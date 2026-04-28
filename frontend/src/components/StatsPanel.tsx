'use client'

import type { GraphData } from '@/lib/api'
import type { ClaimType, ClaimStatus } from '@/lib/api'
import { CLAIM_TYPE_META, STATUS_META, confPct } from '@/lib/utils'
import { confColor } from '@/lib/utils'

interface Props {
  data: GraphData
}

export default function StatsPanel({ data }: Props) {
  const claims   = data.nodes.filter(n => n.type === 'Claim')
  const entities = data.nodes.filter(n => n.type === 'Entity')

  if (claims.length === 0) {
    return (
      <div className="px-4 py-3 text-xs text-center border-t"
        style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--surface)' }}>
        No data
      </div>
    )
  }

  // Claims by type
  const byType = new Map<string, number>()
  for (const c of claims) {
    if (c.claim_type) byType.set(c.claim_type, (byType.get(c.claim_type) ?? 0) + 1)
  }
  const sortedTypes = Array.from(byType.entries()).sort((a, b) => b[1] - a[1])

  // Average ESS
  const avgEss = claims.reduce((s, c) => s + (c.evidence_support_score ?? 0.8), 0) / claims.length

  // Status distribution
  const byStatus = new Map<ClaimStatus, number>()
  for (const c of claims) {
    const s = (c.status ?? 'active') as ClaimStatus
    byStatus.set(s, (byStatus.get(s) ?? 0) + 1)
  }

  // Top entities by mention count
  const entityMentions = new Map<string, number>()
  for (const e of data.edges) {
    if (e.label === 'mentions') {
      const tgt = data.nodes.find(n => n.id === e.target)
      if (tgt?.type === 'Entity') {
        entityMentions.set(tgt.label, (entityMentions.get(tgt.label) ?? 0) + 1)
      }
    }
  }
  const topEntities = Array.from(entityMentions.entries()).sort((a, b) => b[1] - a[1]).slice(0, 4)

  return (
    <div className="px-4 py-3 border-t grid grid-cols-3 gap-3 text-xs shrink-0"
      style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}>

      {/* Summary pills */}
      <div className="rounded-lg p-2 text-center" style={{ background: 'var(--surface-2)' }}>
        <p className="text-base font-bold" style={{ color: 'var(--brand)' }}>{claims.length}</p>
        <p style={{ color: 'var(--text-muted)' }}>claims</p>
      </div>
      <div className="rounded-lg p-2 text-center" style={{ background: 'var(--surface-2)' }}>
        <p className="text-base font-bold" style={{ color: 'var(--brand)' }}>{entities.length}</p>
        <p style={{ color: 'var(--text-muted)' }}>entities</p>
      </div>
      <div className="rounded-lg p-2 text-center" style={{ background: 'var(--surface-2)' }}>
        <p className="text-base font-bold" style={{ color: confColor(avgEss) }}>{confPct(avgEss)}%</p>
        <p style={{ color: 'var(--text-muted)' }}>avg ESS</p>
      </div>

      {/* Type distribution bars */}
      <div className="col-span-2 space-y-1.5">
        {sortedTypes.map(([ct, n]) => {
          const meta = CLAIM_TYPE_META[ct as ClaimType]
          if (!meta) return null
          const pct = Math.round(n / claims.length * 100)
          return (
            <div key={ct} className="flex items-center gap-1.5">
              <span className="shrink-0" style={{ color: meta.color }}>{meta.icon}</span>
              <span className="w-16 truncate shrink-0" style={{ color: 'var(--text-muted)' }}>{meta.label}</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--border)' }}>
                <div className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: meta.color }} />
              </div>
              <span className="w-4 text-right font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>{n}</span>
            </div>
          )
        })}
      </div>

      {/* Status + top entities */}
      <div className="space-y-2">
        <div>
          <p className="font-semibold mb-1" style={{ color: 'var(--text-muted)' }}>Status</p>
          {(['active', 'observed', 'resolved', 'superseded'] as ClaimStatus[]).map(s => {
            const n = byStatus.get(s) ?? 0
            if (n === 0) return null
            return (
              <div key={s} className="flex justify-between">
                <span style={{ color: STATUS_META[s].color }}>{STATUS_META[s].label}</span>
                <span style={{ color: 'var(--text-muted)' }}>{n}</span>
              </div>
            )
          })}
        </div>
        {topEntities.length > 0 && (
          <div>
            <p className="font-semibold mb-1" style={{ color: 'var(--text-muted)' }}>Top entities</p>
            {topEntities.map(([name, count]) => (
              <div key={name} className="flex justify-between gap-1">
                <span className="truncate" style={{ color: 'var(--text)', maxWidth: '72px' }} title={name}>{name}</span>
                <span className="font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>{count}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
