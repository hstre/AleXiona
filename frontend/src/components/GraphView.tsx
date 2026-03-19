'use client'

import { useEffect, useRef, useState } from 'react'
import type { GraphData, GraphNode } from '@/lib/api'
import { updateClaim, deleteClaim } from '@/lib/api'

interface Props {
  data: GraphData
  onRefresh: () => void
}

export default function GraphView({ data, onRefresh }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<any>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [editText, setEditText] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (typeof window === 'undefined' || !containerRef.current) return

    import('cytoscape').then(({ default: cytoscape }) => {
      if (cyRef.current) cyRef.current.destroy()

      const elements = [
        ...data.nodes.map(n => ({
          data: { id: n.id, label: n.label, type: n.type,
                  fullText: n.fullText, claimId: n.claimId,
                  confidence: n.confidence ?? 0.8 },
        })),
        ...data.edges.map(e => ({
          data: { id: e.id, source: e.source, target: e.target, label: e.label },
        })),
      ]

      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: 'node[type="Claim"]',
            style: {
              'background-color': '#1a7ab3',
              'border-color': '#0d5a8a',
              'border-width': 2,
              label: 'data(label)',
              color: '#ffffff',
              'font-size': '11px',
              'font-weight': '500',
              'text-wrap': 'wrap',
              'text-max-width': '130px',
              'text-valign': 'center',
              'text-halign': 'center',
              width: 150,
              height: 56,
              shape: 'round-rectangle',
              'padding': '10px',
            },
          },
          {
            selector: 'node[type="Entity"]',
            style: {
              'background-color': '#ffffff',
              'border-color': '#1a7ab3',
              'border-width': 2,
              label: 'data(label)',
              color: '#1a2b3c',
              'font-size': '12px',
              'font-weight': '500',
              'text-valign': 'center',
              'text-halign': 'center',
              width: 110,
              height: 42,
              shape: 'ellipse',
            },
          },
          {
            selector: 'node:selected',
            style: {
              'border-color': '#f59e0b',
              'border-width': 3,
              'box-shadow': '0 0 0 4px rgba(245,158,11,0.2)',
            },
          },
          {
            selector: 'edge',
            style: {
              width: 1.5,
              'line-color': '#b0c4de',
              'target-arrow-color': '#6b9fc4',
              'target-arrow-shape': 'triangle',
              'arrow-scale': 0.8,
              'curve-style': 'bezier',
              label: 'data(label)',
              color: '#6b7fa3',
              'font-size': '10px',
              'text-background-color': '#f4f7fb',
              'text-background-opacity': 1,
              'text-background-padding': '3px',
              'text-background-shape': 'round-rectangle',
            },
          },
          {
            selector: 'edge[label="mentions"]',
            style: {
              'line-style': 'dashed',
              'line-dash-pattern': [4, 3],
              width: 1,
              'line-color': '#c8d8e8',
              'target-arrow-color': '#c8d8e8',
              label: '',
            },
          },
          {
            selector: 'edge:selected',
            style: {
              'line-color': '#f59e0b',
              'target-arrow-color': '#f59e0b',
            },
          },
        ],
        layout: {
          name: 'cose',
          animate: true,
          animationDuration: 600,
          nodeRepulsion: 10000,
          idealEdgeLength: 160,
          padding: 50,
          randomize: false,
        } as any,
        userZoomingEnabled: true,
        userPanningEnabled: true,
        boxSelectionEnabled: false,
      })

      cy.on('tap', 'node', (evt: any) => {
        const n = evt.target
        setSelected({
          id: n.id(), label: n.data('label'), type: n.data('type'),
          fullText: n.data('fullText'), claimId: n.data('claimId'),
        })
        setEditText(n.data('fullText') || n.data('label'))
      })
      cy.on('tap', (evt: any) => { if (evt.target === cy) setSelected(null) })

      cyRef.current = cy
    })

    return () => { if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null } }
  }, [data])

  const handleSave = async () => {
    if (!selected?.claimId) return
    setSaving(true)
    try { await updateClaim(selected.claimId, editText); onRefresh(); setSelected(null) }
    finally { setSaving(false) }
  }

  const handleDelete = async () => {
    if (!selected?.claimId || !confirm('Delete this node?')) return
    setSaving(true)
    try { await deleteClaim(selected.claimId); onRefresh(); setSelected(null) }
    finally { setSaving(false) }
  }

  const claimCount = data.nodes.filter(n => n.type === 'Claim').length
  const entityCount = data.nodes.filter(n => n.type === 'Entity').length

  return (
    <div className="relative w-full h-full" style={{ background: 'var(--surface-2)' }}>
      {/* Empty state */}
      {data.nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="text-5xl mb-3 opacity-10">◈</div>
          <p className="text-sm opacity-30">Knowledge graph will appear here</p>
        </div>
      )}

      {/* Graph canvas */}
      <div ref={containerRef} className="absolute inset-0" style={{ bottom: '48px' }} />

      {/* Timeline bar */}
      <div
        className="absolute bottom-0 left-0 right-0 h-12 flex items-center px-4 gap-3 border-t"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-3 flex-1 overflow-x-auto">
          <span className="text-xs shrink-0" style={{ color: 'var(--text-muted)' }}>
            {claimCount} claims
          </span>
          <div className="h-px flex-1 min-w-8" style={{ background: 'var(--border)' }} />

          {data.nodes.filter(n => n.type === 'Claim').slice(0, 6).map((node, i) => (
            <div key={i} className="flex items-center gap-1.5 shrink-0">
              <div className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--brand)' }} />
              <span className="text-xs whitespace-nowrap" style={{ color: 'var(--text-muted)', maxWidth: '100px',
                overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {node.label.split(' ').slice(0, 3).join(' ')}
              </span>
            </div>
          ))}

          {claimCount > 6 && (
            <span className="text-xs shrink-0" style={{ color: 'var(--text-light)' }}>
              +{claimCount - 6} more
            </span>
          )}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 shrink-0 border-l pl-3" style={{ borderColor: 'var(--border)' }}>
          <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span className="w-3 h-3 rounded-sm inline-block" style={{ background: '#1a7ab3' }} />
            Claim
          </span>
          <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span className="w-3 h-3 rounded-full inline-block border-2" style={{ borderColor: '#1a7ab3' }} />
            Entity
          </span>
        </div>
      </div>

      {/* Node detail panel */}
      {selected && (
        <div
          className="absolute top-3 right-3 w-72 rounded-2xl shadow-lg p-4"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)', zIndex: 10 }}
        >
          <div className="flex items-center justify-between mb-3">
            <span
              className="text-xs font-medium px-2 py-0.5 rounded-full"
              style={{
                background: selected.type === 'Claim' ? 'var(--brand-pale)' : 'var(--teal-pale)',
                color: selected.type === 'Claim' ? 'var(--brand)' : 'var(--teal)',
              }}
            >
              {selected.type}
            </span>
            <button onClick={() => setSelected(null)} className="text-sm"
              style={{ color: 'var(--text-muted)' }}>✕</button>
          </div>

          {selected.claimId ? (
            <>
              <textarea
                className="w-full text-sm rounded-lg p-2 resize-none outline-none"
                style={{ background: 'var(--surface-2)', border: '1px solid var(--border)',
                         color: 'var(--text)', minHeight: '70px' }}
                value={editText}
                onChange={e => setEditText(e.target.value)}
              />
              <div className="flex gap-2 mt-2">
                <button onClick={handleSave} disabled={saving}
                  className="flex-1 py-1.5 rounded-lg text-xs font-medium disabled:opacity-50"
                  style={{ background: 'var(--brand)', color: 'white' }}>
                  Save
                </button>
                <button onClick={handleDelete} disabled={saving}
                  className="py-1.5 px-3 rounded-lg text-xs font-medium disabled:opacity-50"
                  style={{ background: '#fef2f2', color: '#ef4444' }}>
                  Delete
                </button>
              </div>
            </>
          ) : (
            <p className="text-sm font-medium">{selected.label}</p>
          )}
        </div>
      )}
    </div>
  )
}
