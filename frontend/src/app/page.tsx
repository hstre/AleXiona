'use client'

import { useState, useEffect, useCallback } from 'react'
import { v4 as uuidv4 } from 'uuid'
import ChatPanel from '@/components/ChatPanel'
import GraphView from '@/components/GraphView'
import { sendMessage, getGraph } from '@/lib/api'
import type { ChatMessage, GraphData, Claim } from '@/lib/api'

export default function Home() {
  const [sessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('alexiona_session')
      if (stored) return stored
      const id = uuidv4()
      localStorage.setItem('alexiona_session', id)
      return id
    }
    return uuidv4()
  })

  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] })
  const [graphLoading, setGraphLoading] = useState(false)
  const [activePanel, setActivePanel] = useState<'chat' | 'graph'>('chat')

  const refreshGraph = useCallback(async () => {
    setGraphLoading(true)
    try {
      const data = await getGraph(sessionId)
      setGraphData(data)
    } catch (err) {
      console.error('Failed to load graph:', err)
    } finally {
      setGraphLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    refreshGraph()
  }, [refreshGraph])

  const handleSendMessage = async (
    message: string,
    history: ChatMessage[]
  ): Promise<{ reply: string; claims: Claim[] }> => {
    const result = await sendMessage(message, sessionId, history)
    return { reply: result.reply, claims: result.claims }
  }

  const newSession = () => {
    if (confirm('Start a new session? Current graph will be preserved but chat will reset.')) {
      const id = uuidv4()
      localStorage.setItem('alexiona_session', id)
      window.location.reload()
    }
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--bg)' }}>
      {/* Top nav */}
      <nav
        className="flex items-center justify-between px-4 py-2 border-b shrink-0"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <span
            className="text-lg font-bold tracking-tight"
            style={{ color: 'var(--brand-light)' }}
          >
            Ale<span style={{ color: 'var(--accent)' }}>X</span>iona
          </span>
          <span
            className="text-xs px-1.5 py-0.5 rounded"
            style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
          >
            v0
          </span>
        </div>

        {/* Mobile tab switcher */}
        <div
          className="flex md:hidden rounded-lg overflow-hidden text-sm"
          style={{ background: 'var(--surface-2)' }}
        >
          <button
            className="px-3 py-1.5 transition-colors"
            style={{
              background: activePanel === 'chat' ? 'var(--brand)' : 'transparent',
              color: activePanel === 'chat' ? 'white' : 'var(--text-muted)',
            }}
            onClick={() => setActivePanel('chat')}
          >
            Chat
          </button>
          <button
            className="px-3 py-1.5 transition-colors"
            style={{
              background: activePanel === 'graph' ? 'var(--brand)' : 'transparent',
              color: activePanel === 'graph' ? 'white' : 'var(--text-muted)',
            }}
            onClick={() => setActivePanel('graph')}
          >
            Graph {graphData.nodes.length > 0 && `(${graphData.nodes.length})`}
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refreshGraph}
            disabled={graphLoading}
            className="text-xs px-2 py-1 rounded-lg transition-opacity hover:opacity-70 disabled:opacity-40"
            style={{ color: 'var(--text-muted)' }}
            title="Refresh graph"
          >
            {graphLoading ? '↻' : '↺'} Refresh
          </button>
          <button
            onClick={newSession}
            className="text-xs px-2 py-1 rounded-lg transition-opacity hover:opacity-70"
            style={{ color: 'var(--text-muted)' }}
          >
            New Session
          </button>
        </div>
      </nav>

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden">
        {/* Chat Panel */}
        <div
          className={`
            flex-col border-r
            md:flex md:w-[420px] md:shrink-0
            ${activePanel === 'chat' ? 'flex flex-1' : 'hidden'}
          `}
          style={{ borderColor: 'var(--border)', background: 'var(--surface)' }}
        >
          <ChatPanel
            sessionId={sessionId}
            onNewClaims={refreshGraph}
            onSendMessage={handleSendMessage}
          />
        </div>

        {/* Graph Panel */}
        <div
          className={`
            flex-col flex-1 relative
            md:flex
            ${activePanel === 'graph' ? 'flex' : 'hidden'}
          `}
          style={{ background: 'var(--bg)' }}
        >
          {/* Graph header */}
          <div
            className="px-4 py-2 border-b flex items-center justify-between shrink-0"
            style={{ borderColor: 'var(--border)' }}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                Knowledge Graph
              </span>
              {graphData.nodes.length > 0 && (
                <span
                  className="text-xs px-1.5 py-0.5 rounded-full"
                  style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
                >
                  {graphData.nodes.length} nodes · {graphData.edges.length} edges
                </span>
              )}
            </div>
            {graphLoading && (
              <span className="text-xs animate-pulse" style={{ color: 'var(--text-muted)' }}>
                Updating...
              </span>
            )}
          </div>

          <div className="flex-1 overflow-hidden">
            <GraphView data={graphData} onRefresh={refreshGraph} />
          </div>
        </div>
      </div>
    </div>
  )
}
