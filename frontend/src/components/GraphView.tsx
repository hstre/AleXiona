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
    if (typeof window === 'undefined') return
    if (!containerRef.current) return

    import('cytoscape').then(({ default: cytoscape }) => {
      if (cyRef.current) {
        cyRef.current.destroy()
      }

      const elements = [
        ...data.nodes.map((n) => ({
          data: {
            id: n.id,
            label: n.label,
            type: n.type,
            fullText: n.fullText,
            claimId: n.claimId,
          },
        })),
        ...data.edges.map((e) => ({
          data: {
            id: e.id,
            source: e.source,
            target: e.target,
            label: e.label,
          },
        })),
      ]

      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: 'node[type="Claim"]',
            style: {
              'background-color': '#4361ee',
              'border-color': '#7b8ef7',
              'border-width': 2,
              label: 'data(label)',
              color: '#ffffff',
              'font-size': '11px',
              'text-wrap': 'wrap',
              'text-max-width': '120px',
              'text-valign': 'center',
              'text-halign': 'center',
              width: 140,
              height: 60,
              shape: 'round-rectangle',
              'padding': '8px',
            },
          },
          {
            selector: 'node[type="Entity"]',
            style: {
              'background-color': '#9b5de5',
              'border-color': '#c084fc',
              'border-width': 2,
              label: 'data(label)',
              color: '#ffffff',
              'font-size': '12px',
              'text-valign': 'center',
              'text-halign': 'center',
              width: 100,
              height: 40,
              shape: 'ellipse',
            },
          },
          {
            selector: 'node:selected',
            style: {
              'border-color': '#f72585',
              'border-width': 3,
            },
          },
          {
            selector: 'edge',
            style: {
              width: 2,
              'line-color': '#2e3250',
              'target-arrow-color': '#4361ee',
              'target-arrow-shape': 'triangle',
              'curve-style': 'bezier',
              label: 'data(label)',
              color: '#8890b5',
              'font-size': '10px',
              'text-background-color': '#1a1d2e',
              'text-background-opacity': 0.9,
              'text-background-padding': '3px',
            },
          },
          {
            selector: 'edge:selected',
            style: {
              'line-color': '#f72585',
              'target-arrow-color': '#f72585',
            },
          },
        ],
        layout: {
          name: 'cose',
          animate: true,
          animationDuration: 500,
          nodeRepulsion: 8000,
          idealEdgeLength: 150,
          padding: 40,
        } as any,
      })

      cy.on('tap', 'node', (evt: any) => {
        const node = evt.target
        const nodeData: GraphNode = {
          id: node.id(),
          label: node.data('label'),
          type: node.data('type'),
          fullText: node.data('fullText'),
          claimId: node.data('claimId'),
        }
        setSelected(nodeData)
        setEditText(nodeData.fullText || nodeData.label)
      })

      cy.on('tap', (evt: any) => {
        if (evt.target === cy) {
          setSelected(null)
        }
      })

      cyRef.current = cy
    })

    return () => {
      if (cyRef.current) {
        cyRef.current.destroy()
        cyRef.current = null
      }
    }
  }, [data])

  const handleSave = async () => {
    if (!selected?.claimId) return
    setSaving(true)
    try {
      await updateClaim(selected.claimId, editText)
      onRefresh()
      setSelected(null)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!selected?.claimId) return
    if (!confirm('Delete this claim?')) return
    setSaving(true)
    try {
      await deleteClaim(selected.claimId)
      onRefresh()
      setSelected(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative w-full h-full">
      {data.nodes.length === 0 && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
          <div className="text-6xl mb-4 opacity-20">◈</div>
          <p className="text-sm opacity-40">
            Start a conversation to build the knowledge graph
          </p>
        </div>
      )}

      <div ref={containerRef} className="w-full h-full" />

      {selected && (
        <div
          className="absolute bottom-4 left-4 right-4 rounded-xl p-4 shadow-2xl"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-2 mb-3">
            <span
              className="text-xs px-2 py-0.5 rounded-full font-medium"
              style={{
                background: selected.type === 'Claim' ? '#4361ee33' : '#9b5de533',
                color: selected.type === 'Claim' ? '#7b8ef7' : '#c084fc',
              }}
            >
              {selected.type}
            </span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {selected.claimId ? 'Editable' : 'Read-only'}
            </span>
          </div>

          {selected.claimId ? (
            <>
              <textarea
                className="w-full rounded-lg p-2 text-sm resize-none"
                style={{
                  background: 'var(--surface-2)',
                  border: '1px solid var(--border)',
                  color: 'var(--text)',
                  minHeight: '60px',
                }}
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
              />
              <div className="flex gap-2 mt-2">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex-1 py-1.5 rounded-lg text-sm font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                  style={{ background: 'var(--brand)', color: 'white' }}
                >
                  Save
                </button>
                <button
                  onClick={handleDelete}
                  disabled={saving}
                  className="py-1.5 px-3 rounded-lg text-sm font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
                  style={{ background: '#f7258520', color: '#f72585' }}
                >
                  Delete
                </button>
                <button
                  onClick={() => setSelected(null)}
                  className="py-1.5 px-3 rounded-lg text-sm"
                  style={{ color: 'var(--text-muted)' }}
                >
                  Close
                </button>
              </div>
            </>
          ) : (
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">{selected.label}</p>
              <button
                onClick={() => setSelected(null)}
                className="text-xs"
                style={{ color: 'var(--text-muted)' }}
              >
                Close
              </button>
            </div>
          )}
        </div>
      )}

      <div
        className="absolute top-3 right-3 flex gap-1.5 text-xs"
        style={{ color: 'var(--text-muted)' }}
      >
        <span className="flex items-center gap-1">
          <span className="w-2.5 h-2.5 rounded-sm inline-block" style={{ background: '#4361ee' }} />
          Claim
        </span>
        <span className="flex items-center gap-1 ml-2">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ background: '#9b5de5' }} />
          Entity
        </span>
      </div>
    </div>
  )
}
