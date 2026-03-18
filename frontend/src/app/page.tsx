'use client'

import { useState, useEffect, useCallback } from 'react'
import { v4 as uuidv4 } from 'uuid'
import ChatPanel from '@/components/ChatPanel'
import GraphView from '@/components/GraphView'
import SessionSidebar from '@/components/SessionSidebar'
import { sendMessage, getGraph } from '@/lib/api'
import type { ChatMessage, GraphData, Claim } from '@/lib/api'

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] })
  const [graphLoading, setGraphLoading] = useState(false)
  const [activePanel, setActivePanel] = useState<'chat' | 'graph'>('chat')
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Resolve session only on client to avoid SSR mismatch
  useEffect(() => {
    const stored = localStorage.getItem('alexiona_session')
    const id = stored || uuidv4()
    if (!stored) localStorage.setItem('alexiona_session', id)
    setSessionId(id)
  }, [])

  const refreshGraph = useCallback(async () => {
    if (!sessionId) return
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
    if (sessionId) refreshGraph()
  }, [sessionId, refreshGraph])

  const handleSendMessage = async (
    message: string,
    history: ChatMessage[]
  ): Promise<{ reply: string; claims: Claim[] }> => {
    if (!sessionId) throw new Error('Session not initialized')
    const result = await sendMessage(message, sessionId, history)
    return { reply: result.reply, claims: result.claims }
  }

  const switchSession = (id: string) => {
    localStorage.setItem('alexiona_session', id)
    setSessionId(id)
    setGraphData({ nodes: [], edges: [] })
    setSidebarOpen(false)
  }

  const newSession = () => {
    const id = uuidv4()
    localStorage.setItem('alexiona_session', id)
    setSessionId(id)
    setGraphData({ nodes: [], edges: [] })
    setSidebarOpen(false)
  }

  if (!sessionId) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ background: 'var(--bg)' }}>
        <div className="w-6 h-6 rounded-full border-2 border-t-transparent animate-spin" style={{ borderColor: 'var(--brand)' }} />
      </div>
    )
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--bg)' }}>
      {/* Top nav */}
      <nav
        className="flex items-center justify-between px-4 py-2 border-b shrink-0 z-10"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
      >
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="w-7 h-7 flex flex-col justify-center gap-1 mr-1 opacity-70 hover:opacity-100"
          >
            <span className="block w-4 h-px" style={{ background: 'var(--text)' }} />
            <span className="block w-4 h-px" style={{ background: 'var(--text)' }} />
            <span className="block w-3 h-px" style={{ background: 'var(--text)' }} />
          </button>
          <span className="text-lg font-bold tracking-tight" style={{ color: 'var(--brand-light)' }}>
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
          >
            {graphLoading ? '↻' : '↺'} Refresh
          </button>
          <button
            onClick={newSession}
            className="text-xs px-2 py-1 rounded-lg transition-opacity hover:opacity-70"
            style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}
          >
            + New
          </button>
        </div>
      </nav>

      <div className="flex flex-1 overflow-hidden relative">
        {/* Session Sidebar */}
        {sidebarOpen && (
          <>
            <div
              className="absolute inset-0 z-20 md:hidden"
              style={{ background: 'rgba(0,0,0,0.5)' }}
              onClick={() => setSidebarOpen(false)}
            />
            <div
              className="absolute left-0 top-0 bottom-0 z-30 md:relative md:z-auto w-64 border-r shrink-0 overflow-y-auto"
              style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
            >
              <SessionSidebar
                currentSessionId={sessionId}
                onSwitch={switchSession}
                onNew={newSession}
              />
            </div>
          </>
        )}

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
            key={sessionId}
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
                  {graphData.nodes.filter(n => n.type === 'Claim').length} claims ·{' '}
                  {graphData.nodes.filter(n => n.type === 'Entity').length} entities ·{' '}
                  {graphData.edges.length} relations
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
