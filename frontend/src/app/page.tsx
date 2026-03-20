'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { v4 as uuidv4 } from 'uuid'
import DataPanel      from '@/components/DataPanel'
import GraphView      from '@/components/GraphView'
import ReviewPanel    from '@/components/ReviewPanel'
import AddNodeModal   from '@/components/AddNodeModal'
import TimeSlider, { parseOffset } from '@/components/TimeSlider'
import TimelinePanel  from '@/components/TimelinePanel'
import { getGraph, seedDemo } from '@/lib/api'
import type { GraphData, Claim, ClaimType, ReasoningResult, Conflict, GraphNode } from '@/lib/api'
import { SESSION_KEY, shortId, confPct, CONFLICT_SEVERITY_META, CLAIM_TYPE_META } from '@/lib/utils'

export default function Home() {
  const [sessionId,   setSessionId]   = useState<string | null>(null)
  const [graphData,   setGraphData]   = useState<GraphData>({ nodes: [], edges: [] })
  const [reasoning,   setReasoning]   = useState<ReasoningResult | null>(null)
  const [conflicts,   setConflicts]   = useState<Conflict[]>([])
  const [graphLoading,       setGraphLoading]       = useState(false)
  const [activePanel,        setActivePanel]        = useState<'data' | 'graph' | 'review'>('graph')
  const [showConflictBanner, setShowConflictBanner] = useState(true)
  const [showAddNode,        setShowAddNode]        = useState(false)
  const [searchQuery,        setSearchQuery]        = useState('')
  const [showSearch,         setShowSearch]         = useState(false)
  const [timeHours,          setTimeHours]          = useState<number>(999)
  const [seeding,            setSeeding]            = useState(false)
  const [typeFilter,         setTypeFilter]         = useState<Set<ClaimType>>(new Set())
  const [focusClaimIds,      setFocusClaimIds]      = useState<string[]>([])
  const [centerView,         setCenterView]         = useState<'graph' | 'timeline'>('graph')

  // ── Session ───────────────────────────────────────────────────────────────
  useEffect(() => {
    const stored = localStorage.getItem(SESSION_KEY)
    const id     = stored || uuidv4()
    if (!stored) localStorage.setItem(SESSION_KEY, id)
    setSessionId(id)
  }, [])

  // ── Graph ─────────────────────────────────────────────────────────────────
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

  // ── Derived: claims from graph nodes ─────────────────────────────────────
  const allClaims = useMemo<Claim[]>(() =>
    graphData.nodes
      .filter(n => n.type === 'Claim')
      .map(n => ({
        text:                   n.fullText || n.label,
        evidence_support_score: n.evidence_support_score ?? 0.8,
        claim_type:             n.claim_type  ?? 'finding',
        source_type:            n.source_type ?? 'llm',
        source_ref:             n.source_ref  ?? '',
        derived_from:           n.derived_from ?? [],
        status:                 n.status      ?? 'active',
        time_offset:            n.time_offset ?? null,
        trend:                  n.trend       ?? 'unknown',
        entities:               [],
        relations:              [],
      })),
    [graphData.nodes]
  )

  // ── Build a node-id → node map for edge lookups ───────────────────────────
  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNode>()
    graphData.nodes.forEach(n => m.set(n.id, n))
    return m
  }, [graphData.nodes])

  // ── Time-filtered + search-filtered + type-filtered graph ────────────────
  const filteredGraph = useMemo<GraphData>(() => {
    const claimNodes = graphData.nodes.filter(n => n.type === 'Claim')
    const maxH       = Math.max(0, ...claimNodes.map(n => parseOffset(n.time_offset)))
    const effectiveH = timeHours >= maxH ? Infinity : timeHours

    // Pass 1: visible Claim node IDs
    const visibleClaimIds = new Set<string>()
    graphData.nodes.forEach(n => {
      if (n.type !== 'Claim') return
      if (parseOffset(n.time_offset) > effectiveH) return
      if (typeFilter.size > 0 && n.claim_type && !typeFilter.has(n.claim_type)) return
      if (searchQuery) {
        const q = searchQuery.toLowerCase()
        if (!n.fullText?.toLowerCase().includes(q) && !n.label.toLowerCase().includes(q)) return
      }
      visibleClaimIds.add(n.id)
    })

    // Pass 2: add Entity nodes connected to visible Claim nodes
    const visibleNodeIds = new Set<string>(visibleClaimIds)
    graphData.edges.forEach(e => {
      const srcVisible = visibleNodeIds.has(e.source)
      const tgtVisible = visibleNodeIds.has(e.target)
      if (srcVisible) {
        const tgt = nodeById.get(e.target)
        if (tgt?.type === 'Entity') visibleNodeIds.add(e.target)
      }
      if (tgtVisible) {
        const src = nodeById.get(e.source)
        if (src?.type === 'Entity') visibleNodeIds.add(e.source)
      }
    })

    const nodes = graphData.nodes.filter(n => visibleNodeIds.has(n.id))
    const edges = graphData.edges.filter(
      e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    )
    return { nodes, edges }
  }, [graphData, timeHours, searchQuery, typeFilter, nodeById])

  // ── Conflict node IDs ─────────────────────────────────────────────────────
  const conflictNodeIds = useMemo(() => {
    const ids = new Set<string>()
    conflicts.forEach(c => c.affected_claim_ids.forEach(id => ids.add(id)))
    return ids
  }, [conflicts])

  // ── Time slider max ───────────────────────────────────────────────────────
  const claimNodes    = graphData.nodes.filter(n => n.type === 'Claim') as GraphNode[]
  const maxTimeOffset = Math.max(0, ...claimNodes.map(n => parseOffset(n.time_offset)))
  useEffect(() => { setTimeHours(maxTimeOffset) }, [maxTimeOffset])

  // ── Type filter toggle ────────────────────────────────────────────────────
  const toggleTypeFilter = (ct: ClaimType) => {
    setTypeFilter(prev => {
      const next = new Set(prev)
      if (next.has(ct)) next.delete(ct)
      else next.add(ct)
      return next
    })
  }

  // ── Demo seed ─────────────────────────────────────────────────────────────
  const handleSeedDemo = async () => {
    if (!sessionId) return
    setSeeding(true)
    try {
      const result = await seedDemo(sessionId)
      if (result.seeded) await refreshGraph()
      else alert(result.reason ?? 'Session already has data')
    } catch (e: any) {
      alert('Seed failed: ' + e.message)
    } finally {
      setSeeding(false)
    }
  }

  // ── Report ────────────────────────────────────────────────────────────────
  const handleGenerateReport = () => {
    if (!reasoning) return
    const lines = [
      'AleXiona Clinical Reasoning Report',
      `Session: ${sessionId}`,
      `Date: ${new Date().toLocaleString()}`,
      '',
      'LEADING HYPOTHESIS',
      reasoning.leading_hypothesis,
      `Evidence Support Score: ${confPct(reasoning.evidence_support_score)}%`,
      '',
      'SUPPORTING EVIDENCE',
      ...reasoning.supporting_evidence.map(e => `  + ${e}`),
      '',
      'CONFLICTING EVIDENCE',
      ...reasoning.conflicting_evidence.map(e => `  ! ${e}`),
      '',
      'MISSING EVIDENCE',
      ...reasoning.missing_evidence.map(m =>
        `  - ${m.test_or_type}: ${m.description} [clarifies: ${m.needed_for}]`),
      '',
      'ALTERNATIVE HYPOTHESES',
      ...reasoning.alternatives.map(a => `  - ${a.label} (${confPct(a.evidence_support_score)}%)`),
      '',
      'CONFLICTS DETECTED',
      ...conflicts.map(c => `  [${c.severity.toUpperCase()}] ${c.message}`),
      '',
      `EVIDENCE NODES (${allClaims.length})`,
      ...allClaims.map(c =>
        `  [${c.claim_type.toUpperCase()} · ${confPct(c.evidence_support_score)}% · ${c.status}] ${c.text}`),
      '',
      '---',
      'This report is a reasoning aid. All conclusions require clinician verification.',
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url
    a.download = `alexiona-report-${shortId(sessionId ?? '')}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const newSession = () => {
    if (!confirm('Start a new session?')) return
    const id = uuidv4()
    localStorage.setItem(SESSION_KEY, id)
    setSessionId(id)
    setGraphData({ nodes: [], edges: [] })
    setReasoning(null)
    setConflicts([])
    setTypeFilter(new Set())
    setFocusClaimIds([])
  }

  if (!sessionId) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ background: 'var(--bg)' }}>
        <div className="w-5 h-5 rounded-full border-2 border-t-transparent animate-spin"
          style={{ borderColor: 'var(--brand)' }} />
      </div>
    )
  }

  const claimCount  = allClaims.length
  const entityCount = graphData.nodes.filter(n => n.type === 'Entity').length
  const topConflict = conflicts.find(c => c.severity === 'error')
    ?? conflicts.find(c => c.severity === 'warning')
    ?? conflicts[0]

  const CLAIM_TYPES = Object.keys(CLAIM_TYPE_META) as ClaimType[]

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--bg)' }}>

      {/* ── Add Node Modal ────────────────────────────────────────────────── */}
      {showAddNode && (
        <AddNodeModal
          sessionId={sessionId}
          onClose={() => setShowAddNode(false)}
          onCreated={refreshGraph}
          allClaims={allClaims}
        />
      )}

      {/* ── Conflict Banner ───────────────────────────────────────────────── */}
      {showConflictBanner && conflicts.length > 0 && topConflict && (() => {
        const meta = CONFLICT_SEVERITY_META[topConflict.severity]
        return (
          <button
            className="flex items-center justify-between px-4 py-2 shrink-0 w-full text-left"
            style={{ background: meta.bg, borderBottom: `1px solid ${meta.border}` }}
            onClick={() => {
              // Focus affected nodes in graph and switch to graph tab
              setFocusClaimIds([...topConflict.affected_claim_ids])
              setActivePanel('graph')
            }}>
            <div className="flex items-center gap-2 min-w-0">
              <span className="shrink-0">{meta.icon}</span>
              <span className="text-xs font-medium truncate" style={{ color: meta.text }}>
                {conflicts.length > 1 ? `${conflicts.length} conflicts — ` : ''}{topConflict.message}
              </span>
              <span className="text-xs shrink-0 opacity-60" style={{ color: meta.text }}>
                (click to focus)
              </span>
            </div>
            <span className="text-xs ml-3 shrink-0" style={{ color: meta.text }}
              onClick={e => { e.stopPropagation(); setShowConflictBanner(false) }}>
              ✕
            </span>
          </button>
        )
      })()}

      {/* ── Top Nav ───────────────────────────────────────────────────────── */}
      <nav className="flex items-center justify-between px-4 py-2.5 border-b shrink-0"
        style={{ background: 'var(--surface)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L4 7v10l8 5 8-5V7L12 2z" stroke="var(--brand)" strokeWidth="1.5" fill="var(--brand-pale)" />
              <path d="M12 2v20M4 7l8 5 8-5" stroke="var(--brand)" strokeWidth="1.5" />
            </svg>
            <span className="text-base font-bold tracking-tight">
              Ale<span style={{ color: 'var(--brand)' }}>X</span>iona
            </span>
          </div>
          <div className="hidden sm:block border-l pl-3" style={{ borderColor: 'var(--border)' }}>
            <span className="text-sm" style={{ color: 'var(--text-muted)' }}>AI Clinical Evidence Graph</span>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-4 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span><strong style={{ color: 'var(--text)' }}>{claimCount}</strong> claims</span>
          <span><strong style={{ color: 'var(--text)' }}>{entityCount}</strong> entities</span>
          {conflicts.length > 0 && (
            <span className="flex items-center gap-1"
              style={{ color: conflicts.some(c => c.severity === 'error') ? '#ef4444' : '#f59e0b' }}>
              ⚠ {conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="flex md:hidden rounded-lg overflow-hidden text-xs border"
          style={{ borderColor: 'var(--border)' }}>
          {(['data', 'graph', 'review'] as const).map(p => (
            <button key={p} onClick={() => setActivePanel(p)}
              className="px-2.5 py-1.5 capitalize"
              style={{
                background: activePanel === p ? 'var(--brand)' : 'var(--surface)',
                color:      activePanel === p ? 'white' : 'var(--text-muted)',
              }}>
              {p}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          {claimCount === 0 && (
            <button onClick={handleSeedDemo} disabled={seeding}
              className="hidden sm:flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-all disabled:opacity-50"
              style={{ background: 'var(--brand-pale)', color: 'var(--brand)', border: '1px solid var(--brand)' }}>
              {seeding ? '…' : '▶ Load Demo'}
            </button>
          )}
          <button onClick={() => setShowSearch(v => !v)}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors"
            style={{
              background: showSearch ? 'var(--brand-pale)' : 'transparent',
              color: showSearch ? 'var(--brand)' : 'var(--text-muted)',
            }}
            title="Search graph">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          </button>
          <button onClick={() => setShowAddNode(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70"
            style={{ background: 'var(--brand)', color: 'white' }}
            title="Add evidence node">
            +
          </button>
          <button onClick={refreshGraph} disabled={graphLoading}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70 disabled:opacity-40"
            title="Refresh">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)"
              strokeWidth="2" className={graphLoading ? 'animate-spin' : ''}>
              <path d="M23 4v6h-6M1 20v-6h6" />
              <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
            </svg>
          </button>
          <button onClick={newSession}
            className="hidden sm:flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg border hover:bg-gray-50"
            style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            + New
          </button>
          <div className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white"
            style={{ background: 'var(--brand)' }}>
            {shortId(sessionId).slice(0, 1).toUpperCase()}
          </div>
        </div>
      </nav>

      {/* ── Search bar ────────────────────────────────────────────────────── */}
      {showSearch && (
        <div className="px-4 py-2 border-b shrink-0 flex items-center gap-2"
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2">
            <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            autoFocus
            type="text"
            placeholder="Search claims and entities…"
            className="flex-1 outline-none text-sm bg-transparent"
            style={{ color: 'var(--text)' }}
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} style={{ color: 'var(--text-muted)' }}>✕</button>
          )}
          {searchQuery && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {filteredGraph.nodes.filter(n => n.type === 'Claim').length} results
            </span>
          )}
        </div>
      )}

      {/* ── Main 3-column layout ──────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* LEFT: Evidence Nodes */}
        <div className={`border-r shrink-0 md:flex flex-col overflow-hidden
            ${activePanel === 'data' ? 'flex flex-1' : 'hidden'} md:w-72`}
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
          <DataPanel
            key={sessionId}
            sessionId={sessionId}
            onNewClaims={refreshGraph}
            onReasoning={r => setReasoning(r)}
            onConflicts={c => { setConflicts(c); setShowConflictBanner(true) }}
            allClaims={allClaims}
          />
        </div>

        {/* CENTER: Graph */}
        <div className={`flex-col flex-1 overflow-hidden md:flex
            ${activePanel === 'graph' ? 'flex' : 'hidden'}`}>

          {/* Graph sub-header */}
          <div className="border-b shrink-0"
            style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
            <div className="px-4 py-2 flex items-center justify-between">
              {/* Graph / Timeline toggle */}
              <div className="flex rounded-lg overflow-hidden border text-xs"
                style={{ borderColor: 'var(--border)' }}>
                {(['graph', 'timeline'] as const).map(v => (
                  <button key={v} onClick={() => setCenterView(v)}
                    className="px-3 py-1 capitalize"
                    style={{
                      background: centerView === v ? 'var(--brand)' : 'var(--surface)',
                      color:      centerView === v ? 'white' : 'var(--text-muted)',
                    }}>
                    {v === 'graph' ? '◈ Graph' : '⏱ Timeline'}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                {centerView === 'graph' && typeFilter.size > 0 && (
                  <button onClick={() => setTypeFilter(new Set())}
                    className="text-xs px-2 py-0.5 rounded-full"
                    style={{ background: 'var(--brand-pale)', color: 'var(--brand)' }}>
                    ✕ Clear filter
                  </button>
                )}
                {searchQuery && (
                  <span className="text-xs px-2 py-0.5 rounded-full"
                    style={{ background: 'var(--brand-pale)', color: 'var(--brand)' }}>
                    Search active
                  </span>
                )}
                {graphLoading && (
                  <span className="text-xs animate-pulse" style={{ color: 'var(--brand)' }}>Updating…</span>
                )}
              </div>
            </div>

            {/* Type filter chips — only in graph mode */}
            {centerView === 'graph' && (
              <div className="px-4 pb-2 flex items-center gap-1.5 overflow-x-auto">
                {CLAIM_TYPES.map(ct => {
                  const meta   = CLAIM_TYPE_META[ct]
                  const active = typeFilter.has(ct)
                  return (
                    <button key={ct} onClick={() => toggleTypeFilter(ct)}
                      className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs shrink-0 transition-colors"
                      style={{
                        background: active ? meta.color : 'var(--surface-2)',
                        color:      active ? 'white'   : 'var(--text-muted)',
                        border:     `1px solid ${active ? meta.color : 'var(--border)'}`,
                      }}>
                      <span>{meta.icon}</span>
                      <span>{meta.label}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Graph canvas */}
          <div className={`flex-1 overflow-hidden ${centerView === 'graph' ? 'flex' : 'hidden'} flex-col`}>
            <div className="flex-1 overflow-hidden">
              <GraphView
                data={filteredGraph}
                onRefresh={refreshGraph}
                conflictNodeIds={conflictNodeIds}
                sessionId={sessionId}
                focusClaimIds={focusClaimIds}
              />
            </div>
            {/* Time slider — inside graph mode only */}
            {maxTimeOffset > 0 && (
              <div className="px-4 py-2 border-t shrink-0"
                style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
                <TimeSlider
                  claimNodes={claimNodes}
                  currentHours={Math.min(timeHours, maxTimeOffset)}
                  onChange={setTimeHours}
                />
              </div>
            )}
          </div>

          {/* Timeline view */}
          {centerView === 'timeline' && (
            <div className="flex-1 overflow-hidden">
              <TimelinePanel
                claimNodes={claimNodes}
                onFocusClaim={id => {
                  setFocusClaimIds([id])
                  setCenterView('graph')
                }}
              />
            </div>
          )}
        </div>

        {/* RIGHT: Clinical Reasoning */}
        <div className={`border-l shrink-0 md:flex flex-col overflow-hidden
            ${activePanel === 'review' ? 'flex flex-1' : 'hidden'} md:w-72`}
          style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
          <ReviewPanel
            reasoning={reasoning}
            loading={false}
            onGenerateReport={handleGenerateReport}
            onClear={() => setReasoning(null)}
          />
        </div>

      </div>
    </div>
  )
}
