'use client'

import { useState, useEffect } from 'react'
import { listSessions, deleteSession } from '@/lib/api'
import type { SessionInfo } from '@/lib/api'

interface Props {
  currentSessionId: string
  onSwitch: (id: string) => void
  onNew: () => void
}

export default function SessionSidebar({ currentSessionId, onSwitch, onNew }: Props) {
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [loading, setLoading] = useState(true)

  const load = async () => {
    try {
      const data = await listSessions()
      setSessions(data)
    } catch {
      /* backend may not be ready yet */
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation()
    if (!confirm('Delete this session and its claims?')) return
    await deleteSession(sessionId)
    if (sessionId === currentSessionId) onNew()
    load()
  }

  const shortId = (id: string) => id.slice(0, 8)

  return (
    <div className="flex flex-col h-full">
      <div
        className="px-4 py-3 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--border)' }}
      >
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
          Sessions
        </span>
        <button
          onClick={onNew}
          className="text-xs px-2 py-1 rounded-lg"
          style={{ background: 'var(--brand)', color: 'white' }}
        >
          + New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {loading && (
          <p className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>
            Loading...
          </p>
        )}

        {!loading && sessions.length === 0 && (
          <p className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>
            No sessions yet
          </p>
        )}

        {/* Always show current session even if not in list yet */}
        {!sessions.find(s => s.session_id === currentSessionId) && (
          <div
            className="flex items-center justify-between px-3 py-2 rounded-lg"
            style={{ background: 'var(--brand)20', border: '1px solid var(--brand)' }}
          >
            <div>
              <p className="text-xs font-mono font-medium">{shortId(currentSessionId)}</p>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Current · 0 claims</p>
            </div>
          </div>
        )}

        {sessions.map((s) => {
          const isCurrent = s.session_id === currentSessionId
          return (
            <div
              key={s.session_id}
              onClick={() => onSwitch(s.session_id)}
              className="flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer group"
              style={{
                background: isCurrent ? 'var(--brand)20' : 'transparent',
                border: isCurrent ? '1px solid var(--brand)' : '1px solid transparent',
              }}
            >
              <div>
                <p className="text-xs font-mono font-medium">{shortId(s.session_id)}</p>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {isCurrent ? 'Current · ' : ''}{s.claim_count} claim{s.claim_count !== 1 ? 's' : ''}
                </p>
              </div>
              <button
                onClick={(e) => handleDelete(e, s.session_id)}
                className="opacity-0 group-hover:opacity-60 hover:!opacity-100 text-xs px-1.5 py-0.5 rounded transition-opacity"
                style={{ color: 'var(--accent)' }}
              >
                ✕
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
