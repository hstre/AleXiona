'use client'

import type { GraphNode } from '@/lib/api'
import { getTypeMeta } from '@/lib/utils'

// Parse "t+6h" → 6,  "t+0h" → 0,  null → 0
export function parseOffset(offset: string | null | undefined): number {
  if (!offset) return 0
  const m = offset.match(/t[+-]?(\d+(?:\.\d+)?)h/i)
  return m ? parseFloat(m[1]) : 0
}

interface Props {
  claimNodes:   GraphNode[]
  currentHours: number
  onChange:     (hours: number) => void
}

export default function TimeSlider({ claimNodes, currentHours, onChange }: Props) {
  // Unique sorted time points
  const timePoints = Array.from(
    new Set(claimNodes.map(n => parseOffset(n.time_offset)))
  ).sort((a, b) => a - b)

  if (timePoints.length < 2) return null  // nothing to slide

  const maxHours = timePoints[timePoints.length - 1]

  // Build event markers
  const events = claimNodes
    .filter(n => n.time_offset)
    .reduce<Record<number, GraphNode[]>>((acc, n) => {
      const h = parseOffset(n.time_offset)
      acc[h] = acc[h] ? [...acc[h], n] : [n]
      return acc
    }, {})

  return (
    <div className="flex flex-col gap-1 w-full">
      {/* Event dots above slider */}
      <div className="relative h-5" style={{ marginLeft: '8px', marginRight: '8px' }}>
        {Object.entries(events).map(([h, nodes]) => {
          const pct = maxHours === 0 ? 0 : (parseFloat(h) / maxHours) * 100
          const meta = getTypeMeta(nodes[0].claim_type)
          return (
            <div
              key={h}
              className="absolute flex flex-col items-center"
              style={{ left: `${pct}%`, transform: 'translateX(-50%)' }}
              title={nodes.map(n => n.label).join('\n')}
            >
              <div className="w-2 h-2 rounded-full border border-white"
                style={{ background: meta.color }} />
              <span className="text-xs" style={{ color: 'var(--text-light)', fontSize: '9px' }}>
                t+{h}h
              </span>
            </div>
          )
        })}
      </div>

      {/* Slider */}
      <div className="flex items-center gap-2">
        <span className="text-xs tabular-nums shrink-0" style={{ color: 'var(--text-muted)', width: '28px' }}>
          t+0h
        </span>
        <input
          type="range"
          min={0}
          max={maxHours}
          step={1}
          value={currentHours}
          onChange={e => onChange(parseInt(e.target.value))}
          className="flex-1"
        />
        <span className="text-xs tabular-nums shrink-0" style={{ color: 'var(--text-muted)', width: '36px' }}>
          t+{maxHours}h
        </span>
        {currentHours < maxHours && (
          <span className="text-xs font-bold shrink-0"
            style={{ color: 'var(--brand)', minWidth: '48px', textAlign: 'right' }}>
            ≤ t+{currentHours}h
          </span>
        )}
        {currentHours >= maxHours && (
          <span className="text-xs shrink-0" style={{ color: 'var(--text-muted)', minWidth: '48px', textAlign: 'right' }}>
            All
          </span>
        )}
      </div>
    </div>
  )
}
