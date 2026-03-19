'use client'

import { useState, useRef } from 'react'
import type { Claim, ChatMessage } from '@/lib/api'
import { confColor, confPct } from '@/lib/utils'

const TAG_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  Symptom:     { bg: '#fff3e0', text: '#e65100', border: '#ff9800' },
  Finding:     { bg: '#e8f5e9', text: '#1b5e20', border: '#4caf50' },
  Evidence:    { bg: '#e3f2fd', text: '#0d47a1', border: '#2196f3' },
  Hypothesis:  { bg: '#f3e5f5', text: '#4a148c', border: '#9c27b0' },
  Observation: { bg: '#e0f2f1', text: '#004d40', border: '#009688' },
  Fact:        { bg: '#e8eaf6', text: '#1a237e', border: '#3f51b5' },
  Claim:       { bg: '#fce4ec', text: '#880e4f', border: '#e91e63' },
}

const TAG_ICONS: Record<string, string> = {
  Symptom: '⚕',
  Finding: '🔬',
  Evidence: '📋',
  Hypothesis: '💡',
  Observation: '👁',
  Fact: '📌',
  Claim: '◈',
}

interface Props {
  sessionId: string
  onSendMessage: (msg: string, history: ChatMessage[]) => Promise<{ reply: string; claims: Claim[] }>
  onNewClaims: () => void
  allClaims: Claim[]
}

export default function DataPanel({ sessionId, onSendMessage, onNewClaims, allClaims }: Props) {
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<ChatMessage[]>([])
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
        { role: 'user', content: text },
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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b flex items-center justify-between"
        style={{ borderColor: 'var(--border)' }}>
        <span className="font-semibold text-sm" style={{ color: 'var(--text)' }}>Evidence Nodes</span>
        <span className="text-xs px-2 py-0.5 rounded-full font-medium"
          style={{ background: 'var(--brand-pale)', color: 'var(--brand)' }}>
          {allClaims.length}
        </span>
      </div>

      {/* Claims list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {allClaims.length === 0 && (
          <div className="text-center py-8">
            <div className="text-3xl mb-2">◈</div>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Enter text below to extract evidence nodes
            </p>
          </div>
        )}

        {allClaims.map((claim, i) => {
          const tag = claim.tag || 'Claim'
          const colors = TAG_COLORS[tag] || TAG_COLORS.Claim
          const icon = TAG_ICONS[tag] || '◈'
          const pct = confPct(claim.confidence)

          return (
            <div key={i}
              className="rounded-xl p-3 shadow-sm border-l-4"
              style={{
                background: 'var(--surface)',
                borderLeftColor: colors.border,
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm">{icon}</span>
                  <span className="text-xs font-medium px-1.5 py-0.5 rounded-md"
                    style={{ background: colors.bg, color: colors.text }}>
                    {tag}
                  </span>
                </div>
                <span className="text-xs font-bold tabular-nums shrink-0"
                  style={{ color: confColor(claim.confidence) }}>
                  {pct}%
                </span>
              </div>

              <p className="text-xs leading-relaxed" style={{ color: 'var(--text)' }}>
                {claim.text}
              </p>

              {claim.entities.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {claim.entities.map((e, j) => (
                    <span key={j} className="text-xs px-1.5 py-0.5 rounded-md"
                      style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                      {e}
                    </span>
                  ))}
                </div>
              )}

              {/* Confidence bar */}
              <div className="mt-2 h-1 rounded-full overflow-hidden"
                style={{ background: 'var(--border-light)' }}>
                <div className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: confColor(claim.confidence) }} />
              </div>
            </div>
          )
        })}
      </div>

      {/* Input */}
      <div className="p-3 border-t" style={{ borderColor: 'var(--border)' }}>
        <div className="rounded-xl overflow-hidden shadow-sm"
          style={{ border: `1px solid ${loading ? 'var(--brand)' : 'var(--border)'}`,
                   background: 'var(--surface)', transition: 'border-color 0.15s' }}>
          <textarea
            ref={textareaRef}
            className="w-full px-3 pt-3 pb-1 text-sm resize-none outline-none bg-transparent"
            style={{ color: 'var(--text)', minHeight: '60px', maxHeight: '120px' }}
            placeholder="Enter text, evidence, or ask a question..."
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            rows={2}
          />
          <div className="flex items-center justify-between px-3 pb-2">
            <span className="text-xs" style={{ color: 'var(--text-light)' }}>
              Enter to analyse
            </span>
            <button
              onClick={send}
              disabled={!input.trim() || loading}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-all"
              style={{
                background: input.trim() && !loading ? 'var(--brand)' : 'var(--border)',
                color: input.trim() && !loading ? 'white' : 'var(--text-muted)',
              }}
            >
              {loading ? (
                <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              )}
              Analyse
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
