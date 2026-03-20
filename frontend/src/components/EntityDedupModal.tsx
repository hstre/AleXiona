'use client'

import { useEffect, useState } from 'react'
import type { EntityGroup } from '@/lib/api'
import { getEntityDuplicates, mergeEntities } from '@/lib/api'

interface Props {
  sessionId: string
  onClose:   () => void
  onMerged:  () => void
}

export default function EntityDedupModal({ sessionId, onClose, onMerged }: Props) {
  const [groups,   setGroups]   = useState<EntityGroup[]>([])
  const [loading,  setLoading]  = useState(true)
  const [working,  setWorking]  = useState<string | null>(null)  // key of group being merged
  const [error,    setError]    = useState('')
  const [done,     setDone]     = useState<string[]>([])         // keys already merged

  useEffect(() => {
    getEntityDuplicates(sessionId)
      .then(setGroups)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  const handleMerge = async (group: EntityGroup) => {
    setWorking(group.key)
    setError('')
    try {
      await mergeEntities(sessionId, group.canonical, group.aliases)
      setDone(prev => [...prev, group.key])
      onMerged()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setWorking(null)
    }
  }

  const pending = groups.filter(g => !done.includes(g.key))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.35)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>

      <div className="w-full max-w-md rounded-2xl shadow-xl overflow-hidden"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--border)' }}>
          <div>
            <h2 className="font-semibold text-sm">Entity Deduplication</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              Merge entity nodes that refer to the same concept
            </p>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        <div className="p-5 max-h-[60vh] overflow-y-auto space-y-3">
          {loading && (
            <div className="flex justify-center py-8">
              <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
                style={{ borderColor: 'var(--brand)' }} />
            </div>
          )}

          {!loading && pending.length === 0 && done.length === 0 && (
            <div className="text-center py-8">
              <div className="text-3xl mb-2 opacity-20">✓</div>
              <p className="text-sm font-medium">No duplicate entities found</p>
              <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                All entity names in this session are unique.
              </p>
            </div>
          )}

          {!loading && pending.length === 0 && done.length > 0 && (
            <div className="text-center py-8">
              <div className="text-3xl mb-2">✓</div>
              <p className="text-sm font-medium text-green-700">
                All duplicates merged ({done.length})
              </p>
            </div>
          )}

          {pending.map(group => (
            <div key={group.key} className="rounded-xl p-3 border"
              style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}>

              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-xs font-semibold mb-1.5" style={{ color: 'var(--text)' }}>
                    Merge into: <span className="font-mono">{group.canonical}</span>
                  </p>
                  <div className="flex flex-wrap gap-1">
                    {group.aliases.map(alias => (
                      <span key={alias}
                        className="text-xs px-1.5 py-0.5 rounded-md font-mono"
                        style={{ background: '#fef3c7', color: '#92400e' }}>
                        {alias}
                      </span>
                    ))}
                    <span className="text-xs px-1.5 py-0.5 rounded-md font-mono"
                      style={{ background: '#f0fdf4', color: '#14532d' }}>
                      → {group.canonical}
                    </span>
                  </div>
                </div>

                <button
                  onClick={() => handleMerge(group)}
                  disabled={working === group.key}
                  className="shrink-0 text-xs px-3 py-1.5 rounded-lg font-medium disabled:opacity-50"
                  style={{ background: 'var(--brand)', color: 'white' }}>
                  {working === group.key ? '…' : 'Merge'}
                </button>
              </div>
            </div>
          ))}

          {error && (
            <p className="text-xs rounded-lg px-3 py-2"
              style={{ background: '#fef2f2', color: '#ef4444' }}>{error}</p>
          )}
        </div>

        <div className="px-5 pb-4">
          <button onClick={onClose}
            className="w-full py-2 rounded-xl text-sm"
            style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
