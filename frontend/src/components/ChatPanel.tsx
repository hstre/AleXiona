'use client'

import { useState, useRef, useEffect } from 'react'
import type { ChatMessage, Claim } from '@/lib/api'

interface Message extends ChatMessage {
  claims?: Claim[]
  loading?: boolean
}

interface Props {
  sessionId: string
  onNewClaims: () => void
  onSendMessage: (message: string, history: ChatMessage[]) => Promise<{ reply: string; claims: Claim[] }>
}

export default function ChatPanel({ sessionId, onNewClaims, onSendMessage }: Props) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: 'Welcome to AleXiona. Share any text, idea, or question — I\'ll extract the knowledge structure and build a graph from it.',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const historyForApi = (): ChatMessage[] =>
    messages
      .filter((m) => !m.loading)
      .map((m) => ({ role: m.role, content: m.content }))

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return

    setInput('')
    setLoading(true)

    const userMsg: Message = { role: 'user', content: text }
    const loadingMsg: Message = { role: 'assistant', content: '', loading: true }

    setMessages((prev) => [...prev, userMsg, loadingMsg])

    try {
      const history = historyForApi()
      const result = await onSendMessage(text, history)

      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: 'assistant',
          content: result.reply,
          claims: result.claims,
        },
      ])

      if (result.claims.length > 0) {
        onNewClaims()
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          role: 'assistant',
          content: 'Error: Could not process your request. Please check that the backend is running.',
        },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="px-4 py-3 flex items-center gap-3 border-b"
        style={{ borderColor: 'var(--border)' }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold"
          style={{ background: 'var(--brand)' }}
        >
          A
        </div>
        <div>
          <h1 className="font-semibold text-sm">AleXiona</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Session: {sessionId.slice(0, 8)}
          </p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className="max-w-[85%] rounded-2xl px-4 py-3"
              style={{
                background:
                  msg.role === 'user'
                    ? 'var(--brand)'
                    : 'var(--surface)',
                borderRadius:
                  msg.role === 'user'
                    ? '18px 18px 4px 18px'
                    : '18px 18px 18px 4px',
              }}
            >
              {msg.loading ? (
                <div className="flex gap-1 items-center py-1">
                  <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full animate-bounce" style={{ background: 'var(--text-muted)', animationDelay: '300ms' }} />
                </div>
              ) : (
                <>
                  <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                  {msg.claims && msg.claims.length > 0 && (
                    <div
                      className="mt-2 pt-2 border-t"
                      style={{ borderColor: 'rgba(255,255,255,0.1)' }}
                    >
                      <p className="text-xs mb-1.5" style={{ color: 'rgba(255,255,255,0.5)' }}>
                        {msg.claims.length} claim{msg.claims.length !== 1 ? 's' : ''} extracted
                      </p>
                      <div className="space-y-1">
                        {msg.claims.map((c, j) => (
                          <div
                            key={j}
                            className="text-xs rounded-lg px-2 py-1"
                            style={{ background: 'rgba(255,255,255,0.08)' }}
                          >
                            {c.text}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t" style={{ borderColor: 'var(--border)' }}>
        <div
          className="flex gap-2 items-end rounded-2xl p-2"
          style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
        >
          <textarea
            ref={inputRef}
            className="flex-1 bg-transparent text-sm resize-none outline-none px-2 py-1"
            placeholder="Enter text, ideas, or ask a question..."
            style={{ color: 'var(--text)', minHeight: '36px', maxHeight: '120px' }}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            onClick={send}
            disabled={!input.trim() || loading}
            className="w-9 h-9 rounded-xl flex items-center justify-center transition-all"
            style={{
              background: input.trim() && !loading ? 'var(--brand)' : 'var(--border)',
              color: 'white',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <p className="text-center text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
