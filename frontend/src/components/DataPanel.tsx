'use client'

import { useState, useRef } from 'react'
import type { Claim, ChatMessage, ClaimStatus } from '@/lib/api'
import { updateClaimStatus } from '@/lib/api'
import { confColor, confPct, getTypeMeta, STATUS_META, TREND_META } from '@/lib/utils'

interface Props {
  sessionId:      string
  onSendMessage:  (msg: string, history: ChatMessage[]) => Promise<{ reply: string; claims: Claim[] }>
  onNewClaims:    () => void
  allClaims:      Claim[]
}

export default function DataPanel({ sessionId, onSendMessage, onNewClaims, allClaims }: Props) {
  const [input,   setInput]   = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [filter,  setFilter]  = useState<'all' | 'active' | 'superseded'>('all')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setLoading(true)
    try {
      const result = await onSendMessage(text, history)
      setHistory(prev => [
        ...prev,
        { role: 'user',      content: text },
        { role: 'assistant', content: result.reply },
      ])
      if (result.claims.length > 0) onNewClaims()
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const handleStatusToggle = async (claim: Claim & { claimId?: string }, newStatus: ClaimStatus) => {
    if (!claim.claimId) return
    await updateClaimStatus(claim.claimId, newStatus)
    onNewClaims()
  }

  const visible = allClaims.filter(c =>
    filter === 'all' ? true : c.status === filter
  )

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-semibold text-sm">Evidence Nodes</span>
          <span className="text-xs px-2 py-0.5 rounded-full font-medium"
            style={{ background: 'var(--brand-pale)', color: 'var(--brand)' }}>
            {allClaims.length}
          </span>
        </div>
        {/* Filter */}
        <div className="flex gap-1">
          {(['all', 'active', 'superseded'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)}
              className="text-xs px-2 py-0.5 rounded-md capitalize transition-colors"
              style={{
                background: filter === f ? 'var(--brand)' : 'var(--surface-2)',
                color:      filter === f ? 'white' : 'var(--text-muted)',
              }}>
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* Claims list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {visible.length === 0 && (
          <div className="text-center py-8">
            <div className="text-3xl mb-2 opacity-20">◈</div>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {allClaims.length === 0
                ? 'Enter text below to extract evidence nodes'
                : 'No claims match this filter'}
            </p>
          </div>
        )}

        {visible.map((claim, i) => {
          const meta   = getTypeMeta(claim.claim_type)
          const pct    = confPct(claim.evidence_support_score)
          const color  = confColor(claim.evidence_support_score)
          const trend  = TREND_META[claim.trend ?? 'unknown']
          const status = STATUS_META[claim.status ?? 'active']
          const dimmed = claim.status === 'superseded' || claim.status === 'resolved'

          return (
            <div key={i}
              className="rounded-xl p-3 border-l-4 transition-opacity"
              style={{
                background:    'var(--surface)',
                borderLeftColor: meta.border,
                boxShadow:     'var(--shadow-sm)',
                opacity:       dimmed ? 0.6 : 1,
              }}
            >
              {/* Top row: type tag + confidence + trend */}
              <div className="flex items-center gap-1.5 mb-2">
                <span className="text-xs font-medium px-1.5 py-0.5 rounded-md"
                  style={{ background: meta.bg, color: meta.text }}>
                  {meta.icon} {meta.label}
                </span>
                {claim.time_offset && (
                  <span className="text-xs px-1.5 py-0.5 rounded-md"
                    style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                    {claim.time_offset}
                  </span>
                )}
                <div className="ml-auto flex items-center gap-1.5">
                  <span className="text-xs font-bold" style={{ color: trend.color }}>
                    {trend.icon}
                  </span>
                  <span className="text-xs font-bold tabular-nums" style={{ color }}>
                    {pct}%
                  </span>
                </div>
              </div>

              {/* Claim text */}
              <p className="text-xs leading-relaxed mb-2" style={{ color: 'var(--text)' }}>
                {claim.text}
              </p>

              {/* Entities */}
              {claim.entities.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-2">
                  {claim.entities.map((e, j) => (
                    <span key={j} className="text-xs px-1.5 py-0.5 rounded-md"
                      style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                      {e}
                    </span>
                  ))}
                </div>
              )}

              {/* Provenance row */}
              <div className="flex items-center justify-between">
                <span className="text-xs" style={{ color: 'var(--text-light)' }}>
                  {claim.source_type}{claim.source_ref ? ` · ${claim.source_ref}` : ''}
                </span>
                <span className="text-xs" style={{ color: status.color }}>
                  {status.label}
                </span>
              </div>

              {/* Confidence bar */}
              <div className="mt-2 h-1 rounded-full overflow-hidden"
                style={{ background: 'var(--border-light)' }}>
                <div className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: color }} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Input */}
      <div className="p-3 border-t" style={{ borderColor: 'var(--border)' }}>
        <div className="rounded-xl overflow-hidden shadow-sm"
          style={{
            border: `1px solid ${loading ? 'var(--brand)' : 'var(--border)'}`,
            background: 'var(--surface)', transition: 'border-color 0.15s',
          }}>
          <textarea
            ref={textareaRef}
            className="w-full px-3 pt-3 pb-1 text-sm resize-none outline-none bg-transparent"
            style={{ color: 'var(--text)', minHeight: '60px', maxHeight: '120px' }}
            placeholder="Enter clinical text, findings, or ask a question…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            rows={2}
          />
          <div className="flex items-center justify-between px-3 pb-2">
            <span className="text-xs" style={{ color: 'var(--text-light)' }}>
              Enter to analyse · Shift+Enter newline
            </span>
            <button onClick={send} disabled={!input.trim() || loading}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-all"
              style={{
                background: input.trim() && !loading ? 'var(--brand)' : 'var(--border)',
                color:      input.trim() && !loading ? 'white' : 'var(--text-muted)',
              }}>
              {loading
                ? <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
                : <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <line x1="22" y1="2" x2="11" y2="13" />
                    <polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>}
              Analyse
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
