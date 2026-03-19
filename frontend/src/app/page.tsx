'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { v4 as uuidv4 } from 'uuid'
import DataPanel from '@/components/DataPanel'
import GraphView from '@/components/GraphView'
import ReviewPanel from '@/components/ReviewPanel'
import { sendMessage, getGraph } from '@/lib/api'
import type { ChatMessage, GraphData, Claim, AnalysisResult } from '@/lib/api'
import { SESSION_KEY, shortId, confPct } from '@/lib/utils'

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] })
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null)
  const [graphLoading, setGraphLoading] = useState(false)
  const [analysisLoading, setAnalysisLoading] = useState(false)
  // mobile panel: 'data' | 'graph' | 'review'
  const [activePanel, setActivePanel] = useState<'data' | 'graph' | 'review'>('graph')

  useEffect(() => {
    const stored = localStorage.getItem(SESSION_KEY)
    const id = stored || uuidv4()
    if (!stored) localStorage.setItem(SESSION_KEY, id)
    setSessionId(id)
  }, [])

  const refreshGraph = useCallback(async () => {
    if (!sessionId) return
    setGraphLoading(true)
    try {
      const data = await getGraph(sessionId)
      setGraphData(data)
    } catch (err) {
      console.error(err)
    } finally {
      setGraphLoading(false)
    }
  }, [sessionId])

  useEffect(() => { if (sessionId) refreshGraph() }, [sessionId, refreshGraph])

  const handleSendMessage = async (
    message: string,
    history: ChatMessage[]
  ): Promise<{ reply: string; claims: Claim[] }> => {
    if (!sessionId) throw new Error('Session not initialized')
    setAnalysisLoading(true)
    const result = await sendMessage(message, sessionId, history)
    if (result.analysis) setAnalysis(result.analysis)
    setAnalysisLoading(false)
    return { reply: result.reply, claims: result.claims }
  }

  const handleNewClaims = () => { refreshGraph() }

  const handleGenerateReport = () => {
    if (!analysis) return
    const lines = [
      `AleXiona Knowledge Graph Report`,
      `Session: ${sessionId}`,
      `Date: ${new Date().toLocaleString()}`,
      ``,
      `PRIMARY HYPOTHESIS`,
      analysis.primary_hypothesis,
      `Confidence: ${confPct(analysis.confidence)}%`,
      ``,
      `ALTERNATIVES`,
      ...analysis.alternatives.map(a => `- ${a.label} (${confPct(a.confidence)}%)`),
      ``,
      `MISSING EVIDENCE`,
      ...analysis.missing_evidence.map(m => `- ${m}`),
      ``,
      `FOCUS POINTS`,
      ...analysis.focus_points.map(f => `- ${f}`),
      ``,
      `CLAIMS (${allClaims.length})`,
      ...allClaims.map(c => `- [${c.tag} ${confPct(c.confidence)}%] ${c.text}`),
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `alexiona-report-${shortId(sessionId ?? '')}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (!sessionId) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ background: 'var(--bg)' }}>
        <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: 'var(--brand)' }} />
      </div>
    )
  }

  // Derived — stays in sync with graph on refresh, survives page reload
  const allClaims = useMemo<Claim[]>(() =>
    graphData.nodes
      .filter(n => n.type === 'Claim')
      .map(n => ({
        text: n.fullText || n.label,
        confidence: n.confidence ?? 0.8,
        tag: n.tag ?? 'Claim',
        entities: [],
        relations: [],
      })),
    [graphData.nodes]
  )

  const claimCount = allClaims.length
  const entityCount = graphData.nodes.filter(n => n.type === 'Entity').length

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--bg)' }}>
      {/* ── Top Nav ── */}
      <nav
        className="flex items-center justify-between px-4 py-2.5 border-b shrink-0"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)',
                 boxShadow: 'var(--shadow-sm)' }}
      >
        {/* Logo */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L4 7v10l8 5 8-5V7L12 2z" stroke="var(--brand)" strokeWidth="1.5" fill="var(--brand-pale)" />
              <path d="M12 2v20M4 7l8 5 8-5" stroke="var(--brand)" strokeWidth="1.5" />
            </svg>
            <span className="text-base font-bold tracking-tight" style={{ color: 'var(--text)' }}>
              Ale<span style={{ color: 'var(--brand)' }}>X</span>iona
            </span>
          </div>
          <div className="hidden sm:flex items-center gap-2 border-l pl-3"
            style={{ borderColor: 'var(--border)' }}>
            <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
              AI Evidence Graph
            </span>
          </div>
        </div>

        {/* Center stats */}
        <div className="hidden md:flex items-center gap-4 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span><strong style={{ color: 'var(--text)' }}>{claimCount}</strong> claims</span>
          <span><strong style={{ color: 'var(--text)' }}>{entityCount}</strong> entities</span>
          <span><strong style={{ color: 'var(--text)' }}>{graphData.edges.length}</strong> relations</span>
        </div>

        {/* Mobile tab switcher */}
        <div className="flex md:hidden rounded-lg overflow-hidden text-xs border"
          style={{ borderColor: 'var(--border)' }}>
          {(['data', 'graph', 'review'] as const).map(panel => (
            <button key={panel}
              onClick={() => setActivePanel(panel)}
              className="px-2.5 py-1.5 capitalize"
              style={{
                background: activePanel === panel ? 'var(--brand)' : 'var(--surface)',
                color: activePanel === panel ? 'white' : 'var(--text-muted)',
              }}>
              {panel}
            </button>
          ))}
        </div>

        {/* Right actions */}
        <div className="flex items-center gap-2">
          <button onClick={refreshGraph} disabled={graphLoading}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-gray-100 disabled:opacity-40"
            title="Refresh graph">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2"
              className={graphLoading ? 'animate-spin' : ''}>
              <path d="M23 4v6h-6M1 20v-6h6" /><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
            </svg>
          </button>
          <button
            onClick={() => {
              if (confirm('Start a new session?')) {
                const id = uuidv4()
                localStorage.setItem(SESSION_KEY, id)
                setSessionId(id)
                setGraphData({ nodes: [], edges: [] })
                setAllClaims([])
                setAnalysis(null)
              }
            }}
            className="hidden sm:flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors hover:bg-gray-50"
            style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            + New Session
          </button>
          <div className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white"
            style={{ background: 'var(--brand)' }}>
            {sessionId.slice(0, 1).toUpperCase()}
          </div>
        </div>
      </nav>

      {/* ── Main 3-column layout ── */}
      <div className="flex flex-1 overflow-hidden gap-0">
        {/* LEFT: Data Panel */}
        <div
          className={`border-r shrink-0 md:flex flex-col overflow-hidden
            ${activePanel === 'data' ? 'flex flex-1' : 'hidden'} md:w-72`}
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
        >
          <DataPanel
            key={sessionId}
            sessionId={sessionId}
            onSendMessage={handleSendMessage}
            onNewClaims={handleNewClaims}
            allClaims={allClaims}
          />
        </div>

        {/* CENTER: Graph */}
        <div
          className={`flex-col flex-1 overflow-hidden
            md:flex ${activePanel === 'graph' ? 'flex' : 'hidden'}`}
        >
          {/* Graph sub-header */}
          <div className="px-4 py-2 border-b flex items-center justify-between shrink-0"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
            <span className="text-xs font-semibold uppercase tracking-wider"
              style={{ color: 'var(--text-muted)' }}>
              Clinical Evidence Graph
            </span>
            {graphLoading && (
              <span className="text-xs animate-pulse" style={{ color: 'var(--brand)' }}>
                Updating...
              </span>
            )}
          </div>
          <div className="flex-1 overflow-hidden">
            <GraphView data={graphData} onRefresh={refreshGraph} />
          </div>
        </div>

        {/* RIGHT: Review Panel */}
        <div
          className={`border-l shrink-0 md:flex flex-col overflow-hidden
            ${activePanel === 'review' ? 'flex flex-1' : 'hidden'} md:w-72`}
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}
        >
          <ReviewPanel
            analysis={analysis}
            loading={analysisLoading}
            onGenerateReport={handleGenerateReport}
            onClear={() => setAnalysis(null)}
          />
        </div>
      </div>
    </div>
  )
}
