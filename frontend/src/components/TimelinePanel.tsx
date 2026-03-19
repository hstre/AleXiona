'use client'

import { useMemo, useState } from 'react'
import type { GraphNode } from '@/lib/api'
import { getTypeMeta, CLAIM_TYPE_META, confColor, confPct } from '@/lib/utils'
import { parseOffset } from './TimeSlider'
import type { ClaimType } from '@/lib/api'

interface Props {
  claimNodes:    GraphNode[]
  onFocusClaim?: (claimId: string) => void
}

// SVG canvas dimensions
const W    = 800
const H    = 220
const PAD  = { top: 20, right: 24, bottom: 36, left: 48 }
const IW   = W - PAD.left - PAD.right
const IH   = H - PAD.top  - PAD.bottom

const EVIDENCE_TYPES = new Set<ClaimType>(['lab', 'imaging', 'finding', 'symptom'])

export default function TimelinePanel({ claimNodes, onFocusClaim }: Props) {
  const [hovered, setHovered] = useState<GraphNode | null>(null)

  // Only claims with a time offset
  const timedClaims = useMemo(
    () => claimNodes.filter(n => n.time_offset),
    [claimNodes]
  )

  const maxH = useMemo(
    () => Math.max(0, ...timedClaims.map(n => parseOffset(n.time_offset))),
    [timedClaims]
  )

  const timePoints = useMemo(
    () => Array.from(new Set(timedClaims.map(n => parseOffset(n.time_offset)))).sort((a, b) => a - b),
    [timedClaims]
  )

  // Evidence accumulation: running avg ESS of evidence-type claims up to each time point
  const accumLine = useMemo(() => {
    return timePoints.map(t => {
      const pool = timedClaims.filter(
        n => EVIDENCE_TYPES.has(n.claim_type as ClaimType) && parseOffset(n.time_offset) <= t
      )
      const avg = pool.length === 0
        ? null
        : pool.reduce((s, n) => s + (n.evidence_support_score ?? 0.8), 0) / pool.length
      return { t, avg }
    }).filter(p => p.avg !== null) as { t: number; avg: number }[]
  }, [timedClaims, timePoints])

  if (timedClaims.length === 0 || maxH === 0) return null

  const xOf = (h: number) => PAD.left + (maxH === 0 ? 0 : (h / maxH) * IW)
  const yOf = (v: number) => PAD.top + (1 - v) * IH

  // Line path for evidence accumulation
  const linePath = accumLine.length > 1
    ? accumLine.map((p, i) => `${i === 0 ? 'M' : 'L'} ${xOf(p.t)} ${yOf(p.avg)}`).join(' ')
    : null

  // Area fill
  const areaPath = linePath
    ? `${linePath} L ${xOf(accumLine[accumLine.length - 1].t)} ${yOf(0)} L ${xOf(accumLine[0].t)} ${yOf(0)} Z`
    : null

  const Y_TICKS = [0, 0.25, 0.5, 0.75, 1]

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--surface-2)' }}>
      {/* Header */}
      <div className="px-5 pt-4 pb-2 flex items-start justify-between shrink-0">
        <div>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text)' }}>
            Evidence Timeline
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            Evidence support score per claim over time · dashed line = running evidence average
          </p>
        </div>
        {/* Legend (claim types present in data) */}
        <div className="flex flex-wrap gap-2 justify-end max-w-xs">
          {(Array.from(new Set(timedClaims.map(n => n.claim_type))) as ClaimType[]).map(ct => {
            const m = CLAIM_TYPE_META[ct]
            if (!m) return null
            return (
              <span key={ct} className="flex items-center gap-1 text-xs"
                style={{ color: 'var(--text-muted)' }}>
                <span className="w-2.5 h-2.5 rounded-full inline-block shrink-0"
                  style={{ background: m.color }} />
                {m.label}
              </span>
            )
          })}
        </div>
      </div>

      {/* SVG chart */}
      <div className="flex-1 px-4 pb-2">
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', height: '100%' }}>
          <defs>
            <linearGradient id="accumGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor="#1a7ab3" stopOpacity="0.18" />
              <stop offset="100%" stopColor="#1a7ab3" stopOpacity="0.02" />
            </linearGradient>
          </defs>

          {/* Y grid + labels */}
          {Y_TICKS.map(v => (
            <g key={v}>
              <line
                x1={PAD.left} y1={yOf(v)} x2={PAD.left + IW} y2={yOf(v)}
                stroke="var(--border)" strokeWidth={v === 0 || v === 1 ? 1 : 0.5}
              />
              <text x={PAD.left - 6} y={yOf(v) + 4}
                textAnchor="end" fontSize="11" fill="var(--text-light)">
                {Math.round(v * 100)}%
              </text>
            </g>
          ))}

          {/* X axis time labels */}
          {timePoints.map(t => (
            <g key={t}>
              <line
                x1={xOf(t)} y1={PAD.top} x2={xOf(t)} y2={PAD.top + IH}
                stroke="var(--border)" strokeWidth="0.5" strokeDasharray="3 3"
              />
              <text x={xOf(t)} y={H - 6}
                textAnchor="middle" fontSize="11" fill="var(--text-light)">
                t+{t}h
              </text>
            </g>
          ))}

          {/* Area fill under accumulation line */}
          {areaPath && (
            <path d={areaPath} fill="url(#accumGrad)" />
          )}

          {/* Accumulation line */}
          {linePath && (
            <path d={linePath} fill="none" stroke="#1a7ab3" strokeWidth="1.5"
              strokeDasharray="6 3" opacity="0.7" />
          )}

          {/* Claim dots */}
          {timedClaims.map(n => {
            const x    = xOf(parseOffset(n.time_offset))
            const y    = yOf(n.evidence_support_score ?? 0.8)
            const meta = getTypeMeta(n.claim_type)
            const dim  = n.status === 'superseded' || n.status === 'resolved'
            const hot  = hovered?.id === n.id
            return (
              <g key={n.id}>
                {hot && (
                  <circle cx={x} cy={y} r={11}
                    fill={meta.color} opacity={0.15} />
                )}
                <circle
                  cx={x} cy={y}
                  r={hot ? 7 : 5}
                  fill={meta.color}
                  opacity={dim ? 0.3 : 1}
                  stroke={hot ? 'white' : 'transparent'}
                  strokeWidth="2"
                  style={{ cursor: n.claimId ? 'pointer' : 'default', transition: 'r 0.1s' }}
                  onMouseEnter={() => setHovered(n)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => n.claimId && onFocusClaim?.(n.claimId)}
                />
              </g>
            )
          })}

          {/* Hover info balloon */}
          {hovered && (() => {
            const x    = xOf(parseOffset(hovered.time_offset))
            const y    = yOf(hovered.evidence_support_score ?? 0.8)
            const meta = getTypeMeta(hovered.claim_type)
            const txt  = (hovered.fullText || hovered.label).slice(0, 52) +
                         ((hovered.fullText || hovered.label).length > 52 ? '…' : '')
            const bx   = Math.min(Math.max(x - 120, PAD.left), PAD.left + IW - 240)
            const by   = y > PAD.top + 60 ? y - 68 : y + 14
            return (
              <g style={{ pointerEvents: 'none' }}>
                <rect x={bx} y={by} width={240} height={54} rx={6}
                  fill="var(--surface)" stroke={meta.color} strokeWidth="1.5"
                  filter="drop-shadow(0 2px 6px rgba(0,0,0,0.12))" />
                <text x={bx + 10} y={by + 17} fontSize="11" fontWeight="600"
                  fill={meta.color}>
                  {meta.icon} {meta.label}
                  {' · '}{hovered.time_offset}
                  {' · '}
                  <tspan fill={confColor(hovered.evidence_support_score ?? 0.8)}>
                    {confPct(hovered.evidence_support_score ?? 0.8)}%
                  </tspan>
                </text>
                <text x={bx + 10} y={by + 34} fontSize="10" fill="var(--text)">
                  {txt}
                </text>
                {hovered.status !== 'active' && (
                  <text x={bx + 10} y={by + 48} fontSize="9" fill="var(--text-light)"
                    fontStyle="italic">
                    {hovered.status}
                  </text>
                )}
              </g>
            )
          })()}
        </svg>
      </div>

      {/* Bottom: count summary */}
      <div className="px-5 pb-3 flex items-center gap-4 shrink-0 border-t"
        style={{ borderColor: 'var(--border)' }}>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          <strong style={{ color: 'var(--text)' }}>{timedClaims.length}</strong> timed claims
          over <strong style={{ color: 'var(--text)' }}>t+0h → t+{maxH}h</strong>
        </span>
        {accumLine.length > 0 && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Final evidence avg:{' '}
            <strong style={{ color: confColor(accumLine[accumLine.length - 1].avg) }}>
              {confPct(accumLine[accumLine.length - 1].avg)}%
            </strong>
          </span>
        )}
        <span className="text-xs ml-auto" style={{ color: 'var(--text-light)' }}>
          Click a dot to focus in graph
        </span>
      </div>
    </div>
  )
}
