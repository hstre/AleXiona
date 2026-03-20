'use client'

import { useState, useRef, useEffect } from 'react'
import type { Claim, ChatMessage, ClaimStatus, ReasoningResult, Conflict } from '@/lib/api'
import { patchClaim, streamMessage } from '@/lib/api'
import { getTypeMeta, STATUS_META, TREND_META, essLabel, ESS_LABEL_META } from '@/lib/utils'

interface Props {
  sessionId:      string
  onNewClaims:    () => void
  onReasoning?:   (r: ReasoningResult) => void
  onConflicts?:   (c: Conflict[]) => void
  allClaims:      Claim[]
}

export default function DataPanel({
  sessionId, onNewClaims, onReasoning, onConflicts, allClaims,
}: Props) {
  const [input,          setInput]          = useState('')
  const [loading,        setLoading]        = useState(false)
  const [streamingReply, setStreamingReply] = useState('')
  const [history,        setHistory]        = useState<ChatMessage[]>([])
  const [filter,         setFilter]         = useState<'all' | 'active' | 'superseded'>('all')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const replyRef    = useRef<HTMLDivElement>(null)

  // Auto-scroll streaming reply
  useEffect(() => {
    if (replyRef.current) replyRef.current.scrollTop = replyRef.current.scrollHeight
  }, [streamingReply])

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setLoading(true)
    setStreamingReply('')

    const userMsg: ChatMessage = { role: 'user', content: text }

    try {
      let finalReply = ''

      for await (const event of streamMessage(text, sessionId, history)) {
        if (event.type === 'token') {
          finalReply += event.content
          setStreamingReply(finalReply)

        } else if (event.type === 'claims') {
          if (event.claims.length > 0) onNewClaims()

        } else if (event.type === 'done') {
          finalReply = event.reply
          setStreamingReply('')
          if (event.reasoning) onReasoning?.(event.reasoning)
          if (event.conflicts?.length) onConflicts?.(event.conflicts)
          onNewClaims()
          setHistory(prev => [
            ...prev,
            userMsg,
            { role: 'assistant', content: finalReply },
          ])

        } else if (event.type === 'error') {
          console.error('Stream error:', event.message)
          setStreamingReply('')
        }
      }
    } catch (err) {
      console.error('sendMessage failed:', err)
      setStreamingReply('')
    } finally {
      setLoading(false)
    }
  }

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  const handleStatusToggle = async (claim: Claim & { claimId?: string }, newStatus: ClaimStatus) => {
    if (!claim.claimId) return
    await patchClaim(claim.claimId, { status: newStatus })
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
          const meta    = getTypeMeta(claim.claim_type)
          const level   = essLabel(claim.evidence_support_score)
          const essMeta = ESS_LABEL_META[level]
          const trend   = TREND_META[claim.trend ?? 'unknown']
          const status  = STATUS_META[claim.status ?? 'active']
          const dimmed  = claim.status === 'superseded' || claim.status === 'resolved'

          return (
            <div key={i}
              className="rounded-xl p-3 border-l-4 transition-opacity"
              style={{
                background:      'var(--surface)',
                borderLeftColor: meta.border,
                boxShadow:       'var(--shadow-sm)',
                opacity:         dimmed ? 0.6 : 1,
              }}>

              {/* Row 1: type + time + ess label */}
              <div className="flex items-center gap-1.5 mb-2 flex-wrap">
                <span className="text-xs font-medium px-1.5 py-0.5 rounded-md"
                  style={{ background: meta.bg, color: meta.text }}>
                  {meta.icon} {meta.label}
                </span>
                {claim.time_offset && (
                  <span className="text-xs px-1.5 py-0.5 rounded-md font-mono"
                    style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                    {claim.time_offset}
                  </span>
                )}
                <div className="ml-auto flex items-center gap-1.5">
                  <span className="text-xs" style={{ color: trend.color }} title={`Trend: ${claim.trend ?? 'unknown'}`}>
                    {trend.icon} {claim.trend ?? 'unknown'}
                  </span>
                  <span className="text-xs font-medium px-1.5 py-0.5 rounded-md"
                    title="Internal evidence support score — not a diagnostic probability"
                    style={{ background: essMeta.bg, color: essMeta.text }}>
                    {level} evidence
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
              <div className="flex items-center justify-between text-xs mb-1">
                <span style={{ color: 'var(--text-light)' }}>
                  {claim.source_type}{claim.source_ref ? ` · ${claim.source_ref}` : ''}
                </span>
                <span style={{ color: status.color }}>{status.label}</span>
              </div>

              {/* created_at + derived_from */}
              {(claim.created_at || (claim.derived_from?.length ?? 0) > 0) && (
                <div className="mt-1.5 pt-1.5 border-t space-y-1"
                  style={{ borderColor: 'var(--border)' }}>
                  {claim.created_at && (
                    <p className="text-xs" style={{ color: 'var(--text-light)' }}>
                      {new Date(claim.created_at).toLocaleString()}
                    </p>
                  )}
                  {(claim.derived_from?.length ?? 0) > 0 && (
                    <div className="flex flex-wrap gap-1 items-center">
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>possible rel.:</span>
                      {claim.derived_from!.map((id, j) => (
                        <span key={j} className="text-xs px-1 py-0.5 rounded font-mono"
                          style={{ background: '#f5f3ff', color: '#7c3aed' }}>
                          {id.slice(0, 8)}…
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Streaming reply area */}
      {(loading || streamingReply) && (
        <div className="mx-3 mb-2 rounded-xl overflow-hidden border"
          style={{ borderColor: 'var(--border)', background: 'var(--surface-2)' }}>
          <div className="px-3 py-1.5 border-b flex items-center gap-2"
            style={{ borderColor: 'var(--border)' }}>
            <span className="w-1.5 h-1.5 rounded-full animate-pulse"
              style={{ background: loading ? 'var(--brand)' : '#22c55e' }} />
            <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
              {loading && !streamingReply ? 'Extracting claims…' : 'AleXiona'}
            </span>
          </div>
          {streamingReply && (
            <div ref={replyRef}
              className="px-3 py-2 text-xs leading-relaxed overflow-y-auto"
              style={{ color: 'var(--text)', maxHeight: '120px' }}>
              {streamingReply}
              {loading && (
                <span className="inline-block w-0.5 h-3 ml-0.5 align-middle animate-pulse"
                  style={{ background: 'var(--brand)' }} />
              )}
            </div>
          )}
        </div>
      )}

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
