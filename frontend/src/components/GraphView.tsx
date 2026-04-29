'use client'

import { useEffect, useRef, useState } from 'react'
import type { GraphData, GraphNode, ClaimType, ClaimStatus, CounterfactualResult } from '@/lib/api'
import { patchClaim, deleteClaim, runCounterfactual } from '@/lib/api'
import { getTypeMeta, STATUS_META, TREND_META, confColor, confPct, essLabel, ESS_LABEL_META, CLAIM_TYPE_META } from '@/lib/utils'

export type GraphLayout = 'cose' | 'breadthfirst' | 'concentric' | 'grid'

export function buildLayout(name: GraphLayout): any {
  switch (name) {
    case 'breadthfirst':
      return { name: 'breadthfirst', animate: false, directed: true, padding: 50, spacingFactor: 1.6 }
    case 'concentric':
      return {
        name: 'concentric', animate: false, padding: 50,
        concentric: (node: any) => node.data('type') === 'Claim' ? (node.data('evidence_support_score') ?? 0.5) : 0,
        levelWidth: () => 0.25,
      }
    case 'grid':
      return { name: 'grid', animate: false, padding: 40, avoidOverlap: true }
    default:
      return { name: 'cose', animate: false, nodeRepulsion: 12000, idealEdgeLength: 170, padding: 50, randomize: false }
  }
}

interface Props {
  data:             GraphData
  onRefresh:        () => void
  conflictNodeIds?: Set<string>    // claim IDs flagged by conflict engine
  sessionId:        string
  focusClaimIds?:   string[]       // claim IDs to center/zoom to
  layout?:          GraphLayout
  fitTrigger?:      number         // increment to trigger fit from parent
}

const NODE_STYLES = [
  {
    selector: '*',
    style: {
      'transition-property': 'none',
      'transition-duration': '0s',
      'transition-delay': '0s',
    },
  },
  {
    selector: 'node[type="Entity"]',
    style: {
      'background-color': '#ffffff', 'border-color': '#1a7ab3', 'border-width': 2,
      label: 'data(label)', color: '#1a2b3c', 'font-size': '12px', 'font-weight': '500',
      'text-valign': 'center', 'text-halign': 'center',
      width: 110, height: 40, shape: 'ellipse',
    },
  },
  {
    selector: 'node[type="Claim"]',
    style: {
      'background-color': '#1a7ab3', 'border-color': '#0d5a8a', 'border-width': 2,
      label: 'data(label)', color: '#ffffff', 'font-size': '11px', 'font-weight': '500',
      'text-wrap': 'wrap', 'text-max-width': '130px',
      'text-valign': 'center', 'text-halign': 'center',
      width: 150, height: 56, shape: 'round-rectangle', padding: '10px',
    },
  },
  ...([
    ['symptom',     '#f59e0b', '#b45309'],
    ['finding',     '#3b82f6', '#1d4ed8'],
    ['lab',         '#8b5cf6', '#6d28d9'],
    ['imaging',     '#06b6d4', '#0e7490'],
    ['hypothesis',  '#eab308', '#a16207'],
    ['diagnosis',   '#1a7ab3', '#0d5a8a'],
    ['therapy',     '#22c55e', '#15803d'],
    ['risk_factor', '#ef4444', '#b91c1c'],
    ['guideline',   '#6b7280', '#374151'],
  ] as [string, string, string][]).map(([ct, fill, border]) => ({
    selector: `node[type="Claim"][claim_type="${ct}"]`,
    style: { 'background-color': fill, 'border-color': border },
  })),
  {
    selector: 'node[status="superseded"], node[status="resolved"]',
    style: { opacity: 0.45, 'border-style': 'dashed' },
  },
  {
    selector: 'node.conflict',
    style: {
      'border-color': '#ef4444', 'border-width': 3,
      'outline-color': '#fca5a5', 'outline-width': 3, 'outline-offset': 2,
    },
  },
  { selector: 'node:selected', style: { 'border-color': '#f59e0b', 'border-width': 3 } },
  {
    selector: 'edge',
    style: {
      width: 1.5, 'line-color': '#b0c4de',
      'target-arrow-color': '#6b9fc4', 'target-arrow-shape': 'triangle',
      'arrow-scale': 0.8, 'curve-style': 'bezier',
      label: 'data(label)', color: '#6b7fa3', 'font-size': '10px',
      'text-background-color': '#f4f7fb', 'text-background-opacity': 1,
      'text-background-padding': '3px', 'text-background-shape': 'round-rectangle',
    },
  },
  {
    selector: 'edge[label="mentions"]',
    style: {
      'line-style': 'dashed', 'line-dash-pattern': [4, 3],
      width: 1, 'line-color': '#c8d8e8', 'target-arrow-color': '#c8d8e8', label: '',
    },
  },
  {
    selector: 'edge[label="derives_from"]',
    style: {
      'line-style': 'dashed', 'line-dash-pattern': [6, 3],
      width: 1.5, 'line-color': '#a78bfa', 'target-arrow-color': '#a78bfa',
      label: 'derives from', color: '#7c3aed', 'font-size': '9px',
      'text-background-color': '#f5f3ff', 'text-background-opacity': 1,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'edge[label="possible_related"]',
    style: {
      'line-style': 'dotted', 'line-dash-pattern': [2, 4],
      width: 1, 'line-color': '#d1d5db', 'target-arrow-color': '#d1d5db',
      label: 'similar topic', color: '#9ca3af', 'font-size': '9px',
      'text-background-color': '#f9fafb', 'text-background-opacity': 1,
      'text-background-padding': '2px',
    },
  },
  { selector: 'edge:selected', style: { 'line-color': '#f59e0b', 'target-arrow-color': '#f59e0b' } },
  // ── Chain highlight ──────────────────────────────────────────────────────
  {
    selector: 'node.chain-ancestor',
    style: {
      'border-color': '#a78bfa', 'border-width': 3,
      'outline-color': '#ddd6fe', 'outline-width': 3, 'outline-offset': 2,
    },
  },
  {
    selector: 'node.chain-descendant',
    style: {
      'border-color': '#34d399', 'border-width': 3,
      'outline-color': '#a7f3d0', 'outline-width': 3, 'outline-offset': 2,
    },
  },
  {
    selector: 'edge.chain-edge',
    style: { width: 3, 'line-color': '#a78bfa', 'target-arrow-color': '#a78bfa' },
  },
]

export default function GraphView({ data, onRefresh, conflictNodeIds, sessionId, focusClaimIds, layout = 'cose', fitTrigger }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef        = useRef<any>(null)
  const [selected,       setSelected]       = useState<GraphNode | null>(null)
  const [editText,       setEditText]       = useState('')
  const [editEss,        setEditEss]        = useState(0.8)
  const [editType,       setEditType]       = useState<ClaimType>('finding')
  const [editStatus,     setEditStatus]     = useState<ClaimStatus>('active')
  const [editTrend,      setEditTrend]      = useState('unknown')
  const [editTimeOffset, setEditTimeOffset] = useState('')
  const [editSourceRef,  setEditSourceRef]  = useState('')
  const [editNotes,      setEditNotes]      = useState('')
  const [saving,         setSaving]         = useState(false)
  const [counterfactual, setCounterfactual] = useState<CounterfactualResult | null>(null)
  const [cfLoading,      setCfLoading]      = useState(false)
  const [cfError,        setCfError]        = useState('')
  const [showLegend,     setShowLegend]     = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined' || !containerRef.current) return
    let cancelled = false
    let rafId: number

    rafId = requestAnimationFrame(() => {
    import('cytoscape').then(({ default: cytoscape }) => {
      try {
      if (cancelled || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return

      // Patch missing null-guard in overrideBypass — crashes iOS Safari with
      // "undefined is not an object (evaluating 'v.color')" when an animation
      // step runs for an unrecognised property name.
      try {
        const _tmp = (cytoscape as any)({ headless: true, elements: [] })
        const styleProto = Object.getPrototypeOf(_tmp.style())
        const origOverride = styleProto.overrideBypass
        if (origOverride && !(origOverride as any)._patched) {
          styleProto.overrideBypass = function(eles: any, name: string, value: any) {
            if (!this.properties || !this.properties[name]) return
            return origOverride.call(this, eles, name, value)
          };
          (styleProto.overrideBypass as any)._patched = true
        }
        _tmp.destroy()
      } catch {}

      if (cyRef.current) cyRef.current.destroy()

      const elements = [
        ...data.nodes.map(n => ({
          data: {
            id: n.id, label: n.label, type: n.type,
            fullText: n.fullText, claimId: n.claimId,
            evidence_support_score: n.evidence_support_score ?? 0.8,
            claim_type:  n.claim_type  ?? 'finding',
            source_type: n.source_type ?? 'llm',
            source_ref:  n.source_ref  ?? '',
            status:      n.status      ?? 'active',
            time_offset: n.time_offset,
            trend:       n.trend       ?? 'unknown',
            created_at:  n.created_at  ?? '',
            derived_from: n.derived_from ?? [],
            notes:       n.notes       ?? '',
          },
          classes: conflictNodeIds?.has(n.claimId ?? '') ? 'conflict' : '',
        })),
        ...data.edges.map(e => ({
          data: { id: e.id, source: e.source, target: e.target, label: e.label },
        })),
      ]

      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: NODE_STYLES as any,
        layout: buildLayout(layout),
        userZoomingEnabled: true, userPanningEnabled: true, boxSelectionEnabled: false,
      })

      cy.on('tap', 'node', (evt: any) => {
        const n = evt.target
        const node: GraphNode = {
          id: n.id(), label: n.data('label'), type: n.data('type'),
          fullText:     n.data('fullText'),    claimId: n.data('claimId'),
          evidence_support_score: n.data('evidence_support_score'),
          claim_type:   n.data('claim_type'),  source_type: n.data('source_type'),
          source_ref:   n.data('source_ref'),  status:      n.data('status'),
          time_offset:  n.data('time_offset'), trend:       n.data('trend'),
          created_at:   n.data('created_at'),  derived_from: n.data('derived_from') ?? [],
        }
        setSelected(node)
        setEditText(n.data('fullText') || n.data('label'))
        setEditEss(n.data('evidence_support_score') ?? 0.8)
        setEditType(n.data('claim_type') ?? 'finding')
        setEditStatus(n.data('status') ?? 'active')
        setEditTrend(n.data('trend') ?? 'unknown')
        setEditTimeOffset(n.data('time_offset') ?? '')
        setEditSourceRef(n.data('source_ref') ?? '')
        setEditNotes(n.data('notes') ?? '')
        setCounterfactual(null)
        setCfError('')

        // ── Evidence-chain highlight ─────────────────────────────────────
        cy.elements().removeClass('chain-ancestor chain-descendant chain-edge')
        if (n.data('type') === 'Claim') {
          const visited = new Set<string>([n.id()])
          // BFS queue: {nodeId, isAncestor (true = upstream, false = downstream)}
          const queue: Array<{ id: string; ancestor: boolean }> = []
          n.connectedEdges('[label="derives_from"]').forEach((e: any) => {
            const isAncestor = e.source().id() === n.id()   // n→target means target is n's source
            const other = isAncestor ? e.target() : e.source()
            e.addClass('chain-edge')
            if (!visited.has(other.id())) {
              visited.add(other.id())
              other.addClass(isAncestor ? 'chain-ancestor' : 'chain-descendant')
              queue.push({ id: other.id(), ancestor: isAncestor })
            }
          })
          while (queue.length) {
            const { id: curId, ancestor } = queue.shift()!
            const cur = cy.$('#' + curId)
            cur.connectedEdges('[label="derives_from"]').forEach((e: any) => {
              e.addClass('chain-edge')
              const other = e.source().id() === curId ? e.target() : e.source()
              if (!visited.has(other.id())) {
                visited.add(other.id())
                other.addClass(ancestor ? 'chain-ancestor' : 'chain-descendant')
                queue.push({ id: other.id(), ancestor })
              }
            })
          }
        }
      })
      cy.on('tap', (evt: any) => {
        if (evt.target === cy) {
          setSelected(null)
          cy.elements().removeClass('chain-ancestor chain-descendant chain-edge')
        }
      })
      cyRef.current = cy
      } catch (err) {
        console.error('[GraphView] Cytoscape init failed:', err)
      }
    }).catch((err) => {
      console.error('[GraphView] Cytoscape import failed:', err)
    })
    }) // end requestAnimationFrame
    return () => {
      cancelled = true
      cancelAnimationFrame(rafId)
      if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null }
    }
  }, [data, conflictNodeIds, layout])

  // Fit graph when parent requests it (keyboard shortcut 'f')
  useEffect(() => {
    if (fitTrigger && cyRef.current) cyRef.current.fit(undefined, 40)
  }, [fitTrigger])

  // Focus on specified claim nodes when prop changes
  useEffect(() => {
    if (!cyRef.current || !focusClaimIds?.length) return
    const targets = cyRef.current.nodes().filter((n: any) =>
      focusClaimIds.includes(n.data('claimId') ?? '')
    )
    if (targets.length) cyRef.current.fit(targets, 80)
  }, [focusClaimIds])

  const handleSave = async () => {
    if (!selected?.claimId) return
    setSaving(true)
    try {
      await patchClaim(selected.claimId, {
        text:                   editText,
        evidence_support_score: editEss,
        claim_type:             editType,
        status:                 editStatus,
        trend:                  editTrend,
        time_offset:            editTimeOffset || null,
        source_ref:             editSourceRef,
        notes:                  editNotes,
      })
      onRefresh()
      setSelected(null)
    } finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!selected?.claimId || !confirm('Delete this claim?')) return
    setSaving(true)
    try { await deleteClaim(selected.claimId); onRefresh(); setSelected(null) }
    finally { setSaving(false) }
  }

  const handleCounterfactual = async () => {
    if (!selected?.claimId) return
    setCfLoading(true)
    setCfError('')
    setCounterfactual(null)
    try {
      const result = await runCounterfactual(sessionId, selected.claimId)
      setCounterfactual(result)
    } catch (e: any) {
      setCfError(e.message ?? 'Counterfactual analysis failed')
    } finally { setCfLoading(false) }
  }

  const fitGraph = () => cyRef.current?.fit(undefined, 40)

  const exportPng = () => {
    if (!cyRef.current) return
    const uri = cyRef.current.png({ scale: 2, bg: '#f4f7fb', full: true })
    const a   = document.createElement('a')
    a.href    = uri
    a.download = 'alexiona-graph.png'
    a.click()
  }
  const CLAIM_TYPES = Object.keys(CLAIM_TYPE_META) as ClaimType[]

  return (
    <div className="relative w-full h-full" style={{ background: 'var(--surface-2)' }}>
      {data.nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="text-5xl mb-3 opacity-10">◈</div>
          <p className="text-sm opacity-30">Knowledge graph will appear here</p>
        </div>
      )}

      {/* Fit button */}
      {data.nodes.length > 0 && (
        <button onClick={fitGraph}
          className="absolute top-3 left-3 z-10 w-7 h-7 rounded-lg flex items-center justify-center text-xs shadow-sm hover:opacity-80"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}
          title="Fit graph">⊞</button>
      )}

      {/* PNG export */}
      {data.nodes.length > 0 && (
        <button onClick={exportPng}
          className="absolute top-3 left-12 z-10 w-7 h-7 rounded-lg flex items-center justify-center text-xs shadow-sm hover:opacity-80"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}
          title="Export graph as PNG">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/>
            <polyline points="21 15 16 10 5 21"/>
          </svg>
        </button>
      )}

      {/* Legend toggle */}
      <button onClick={() => setShowLegend(v => !v)}
        className="absolute top-3 left-[5rem] z-10 h-7 px-2 rounded-lg text-xs flex items-center gap-1 shadow-sm hover:opacity-80"
        style={{
          background: showLegend ? 'var(--brand-pale)' : 'var(--surface)',
          border: `1px solid ${showLegend ? 'var(--brand)' : 'var(--border)'}`,
          color: showLegend ? 'var(--brand)' : 'var(--text-muted)',
        }}>
        ⬡ Types
      </button>

      {/* Legend panel */}
      {showLegend && (
        <div className="absolute top-12 left-3 z-20 rounded-xl shadow-lg p-3 w-52"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
          <p className="text-xs font-semibold mb-2" style={{ color: 'var(--text-muted)' }}>
            Claim Types
          </p>
          <div className="space-y-1.5">
            {CLAIM_TYPES.map(ct => {
              const m = CLAIM_TYPE_META[ct]
              return (
                <div key={ct} className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-sm shrink-0" style={{ background: m.color }} />
                  <span className="text-xs" style={{ color: 'var(--text)' }}>{m.icon} {m.label}</span>
                </div>
              )
            })}
          </div>
          <div className="border-t mt-2 pt-2 space-y-1.5" style={{ borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full border-2 shrink-0" style={{ borderColor: '#1a7ab3' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Entity</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0.5 rounded shrink-0" style={{ background: '#a78bfa' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>derives from (explicit)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-0.5 shrink-0" style={{ background: '#d1d5db', borderTop: '1px dotted #9ca3af' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>possible related (heuristic)</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-sm shrink-0"
                style={{ background: '#ef4444', outline: '2px solid #fca5a5', outlineOffset: '1px' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>conflict</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-sm shrink-0"
                style={{ border: '3px solid #a78bfa', outline: '2px solid #ddd6fe', outlineOffset: '1px' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>chain ancestor</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-sm shrink-0"
                style={{ border: '3px solid #34d399', outline: '2px solid #a7f3d0', outlineOffset: '1px' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>chain descendant</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-sm border-dashed border-2 shrink-0"
                style={{ borderColor: '#6b7280', opacity: 0.5 }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>superseded / resolved</span>
            </div>
          </div>
        </div>
      )}

      {/* Graph canvas */}
      <div ref={containerRef} className="absolute inset-0" />

      {/* Node detail panel */}
      {selected && (
        <div className="absolute top-3 right-3 w-80 rounded-2xl shadow-lg overflow-hidden z-10"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>

          <div className="flex items-center justify-between px-4 py-3 border-b"
            style={{ borderColor: 'var(--border)' }}>
            {selected.type === 'Claim' && selected.claim_type ? (() => {
              const meta = getTypeMeta(selected.claim_type)
              return (
                <span className="text-xs font-medium px-2 py-0.5 rounded-full"
                  style={{ background: meta.bg, color: meta.text }}>
                  {meta.icon} {meta.label}
                </span>
              )
            })() : (
              <span className="text-xs px-2 py-0.5 rounded-full"
                style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                Entity
              </span>
            )}
            <button onClick={() => setSelected(null)} style={{ color: 'var(--text-muted)' }}>✕</button>
          </div>

          <div className="p-4 space-y-3 max-h-[75vh] overflow-y-auto">
            {selected.claimId ? (
              <>
                {/* Text */}
                <textarea
                  className="w-full text-sm rounded-lg p-2 resize-none outline-none"
                  style={{ background: 'var(--surface-2)', border: '1px solid var(--border)',
                           color: 'var(--text)', minHeight: '65px' }}
                  value={editText}
                  onChange={e => setEditText(e.target.value)}
                />

                {/* Editable fields grid */}
                <div className="rounded-lg p-3 space-y-2 text-xs"
                  style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>

                  {/* ESS slider */}
                  <div>
                    <div className="flex justify-between items-center mb-1">
                      <span style={{ color: 'var(--text-muted)' }}>Evidence support
                        <span className="ml-1 opacity-50">(not probability)</span>
                      </span>
                      <span className="text-xs font-medium px-1.5 py-0.5 rounded-md"
                        style={{ background: ESS_LABEL_META[essLabel(editEss)].bg, color: ESS_LABEL_META[essLabel(editEss)].text }}>
                        {essLabel(editEss)} · {confPct(editEss)}%
                      </span>
                    </div>
                    <input type="range" min={0} max={100}
                      value={Math.round(editEss * 100)}
                      onChange={e => setEditEss(Number(e.target.value) / 100)}
                      className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                      style={{ accentColor: confColor(editEss) }}
                    />
                  </div>

                  {/* Type + Status row */}
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <p className="mb-1" style={{ color: 'var(--text-muted)' }}>Type</p>
                      <select value={editType} onChange={e => setEditType(e.target.value as ClaimType)}
                        className="w-full text-xs rounded-md px-1.5 py-1 outline-none"
                        style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}>
                        {(Object.keys(CLAIM_TYPE_META) as ClaimType[]).map(ct => (
                          <option key={ct} value={ct}>{CLAIM_TYPE_META[ct].icon} {CLAIM_TYPE_META[ct].label}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex-1">
                      <p className="mb-1" style={{ color: 'var(--text-muted)' }}>Status</p>
                      <select value={editStatus} onChange={e => setEditStatus(e.target.value as ClaimStatus)}
                        className="w-full text-xs rounded-md px-1.5 py-1 outline-none"
                        style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}>
                        {(['active', 'observed', 'resolved', 'superseded'] as const).map(s => (
                          <option key={s} value={s}>{STATUS_META[s].label}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Trend + Time offset row */}
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <p className="mb-1" style={{ color: 'var(--text-muted)' }}>Trend</p>
                      <select value={editTrend} onChange={e => setEditTrend(e.target.value)}
                        className="w-full text-xs rounded-md px-1.5 py-1 outline-none"
                        style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}>
                        {Object.entries(TREND_META).map(([k, v]) => (
                          <option key={k} value={k}>{v.icon} {k}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex-1">
                      <p className="mb-1" style={{ color: 'var(--text-muted)' }}>Time offset</p>
                      <input type="text" placeholder="t+6h"
                        value={editTimeOffset}
                        onChange={e => setEditTimeOffset(e.target.value)}
                        className="w-full text-xs rounded-md px-1.5 py-1 outline-none font-mono"
                        style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}
                      />
                    </div>
                  </div>

                  {/* Source ref */}
                  <div>
                    <p className="mb-1" style={{ color: 'var(--text-muted)' }}>
                      Source ref <span className="opacity-50">(source: {selected.source_type})</span>
                    </p>
                    <input type="text" placeholder="e.g. Lab result #42"
                      value={editSourceRef}
                      onChange={e => setEditSourceRef(e.target.value)}
                      className="w-full text-xs rounded-md px-1.5 py-1 outline-none"
                      style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)' }}
                    />
                  </div>

                  {/* Notes */}
                  <div>
                    <p className="mb-1" style={{ color: 'var(--text-muted)' }}>Notes</p>
                    <textarea
                      placeholder="Add a clinical annotation…"
                      value={editNotes}
                      onChange={e => setEditNotes(e.target.value)}
                      className="w-full text-xs rounded-md px-1.5 py-1 resize-none outline-none"
                      style={{ background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text)', minHeight: '52px' }}
                      rows={2}
                    />
                  </div>

                  {/* Read-only: created + derived_from */}
                  {selected.created_at && (
                    <div className="flex justify-between pt-1 border-t" style={{ borderColor: 'var(--border)' }}>
                      <span style={{ color: 'var(--text-muted)' }}>Created</span>
                      <span style={{ color: 'var(--text)' }}>
                        {new Date(selected.created_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {(selected.derived_from?.length ?? 0) > 0 && (
                    <div className="pt-1 border-t" style={{ borderColor: 'var(--border)' }}>
                      <p className="mb-1" style={{ color: 'var(--text-muted)' }}>Derived from</p>
                      <div className="flex flex-wrap gap-1">
                        {selected.derived_from!.map((id, i) => (
                          <span key={i} className="px-1.5 py-0.5 rounded-md font-mono"
                            style={{ background: '#f5f3ff', color: '#7c3aed', fontSize: '10px' }}>
                            {id.slice(0, 8)}…
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm font-medium">{selected.label}</p>
            )}

            {/* Counterfactual error */}
            {cfError && (
              <div className="rounded-lg px-3 py-2 text-xs"
                style={{ background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca' }}>
                {cfError}
              </div>
            )}

            {/* Counterfactual result */}
            {counterfactual && (
              <div className="rounded-lg p-3 space-y-2"
                style={{ background: '#eff6ff', border: '1px solid #bfdbfe' }}>
                <p className="text-xs font-semibold" style={{ color: '#1e3a8a' }}>
                  Counterfactual — if this claim is removed
                </p>

                {/* Changed evidence items */}
                {counterfactual.changed_evidence.length > 0 && (
                  <div className="space-y-0.5">
                    <p className="text-xs font-medium" style={{ color: '#3730a3' }}>
                      Evidence affected:
                    </p>
                    {counterfactual.changed_evidence.map((e, i) => (
                      <p key={i} className="text-xs pl-2" style={{ color: '#1e40af' }}>· {e}</p>
                    ))}
                  </div>
                )}

                {counterfactual.shifts.map((s, i) => {
                  const delta      = s.score_after - s.score_before
                  const deltaPp    = Math.abs(Math.round(delta * 100))
                  const deltaSign  = delta >= 0 ? '+' : '−'
                  const deltaColor = Math.abs(delta) < 0.01
                    ? '#6b7280' : delta < 0 ? '#f59e0b' : '#3b82f6'
                  return (
                    <div key={i} className="rounded-md px-2 py-1.5"
                      style={{ background: 'white', border: '1px solid #dbeafe' }}>
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-xs font-medium" style={{ color: '#1e3a8a' }}>
                          {s.hypothesis}
                        </span>
                        <span className="text-xs font-bold px-1.5 py-0.5 rounded"
                          style={{ background: deltaColor + '22', color: deltaColor }}>
                          {deltaSign}{deltaPp}pp
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5 text-xs font-mono">
                        <span style={{ color: confColor(s.score_before) }}>{confPct(s.score_before)}%</span>
                        <span style={{ color: '#94a3b8' }}>→</span>
                        <span style={{ color: confColor(s.score_after) }}>{confPct(s.score_after)}%</span>
                      </div>
                    </div>
                  )
                })}
                {counterfactual.reasoning_trace && (
                  <p className="text-xs italic mt-1" style={{ color: '#3730a3' }}>
                    {counterfactual.reasoning_trace}
                  </p>
                )}
              </div>
            )}

            {/* Actions */}
            {selected.claimId && (
              <div className="space-y-2">
                <div className="flex gap-1.5">
                  <button onClick={handleSave} disabled={saving}
                    className="flex-1 py-1.5 rounded-lg text-xs font-medium disabled:opacity-50"
                    style={{ background: 'var(--brand)', color: 'white' }}>
                    {saving ? 'Saving…' : 'Save changes'}
                  </button>
                  <button onClick={handleDelete} disabled={saving}
                    className="py-1.5 px-3 rounded-lg text-xs disabled:opacity-50"
                    style={{ background: '#fef2f2', color: '#ef4444' }}>
                    Delete
                  </button>
                </div>
                <button onClick={handleCounterfactual} disabled={cfLoading}
                  className="w-full py-1.5 rounded-lg text-xs font-medium hover:opacity-80 disabled:opacity-50"
                  style={{ background: '#eff6ff', color: '#1e3a8a' }}>
                  {cfLoading ? 'Analysing…' : '⚡ Run Counterfactual'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
