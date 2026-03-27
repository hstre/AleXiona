'use client'

import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { v4 as uuidv4 } from 'uuid'
import DataPanel          from '@/components/DataPanel'
import GraphView          from '@/components/GraphView'
import type { GraphLayout } from '@/components/GraphView'
import ReviewPanel        from '@/components/ReviewPanel'
import AddNodeModal       from '@/components/AddNodeModal'
import EntityDedupModal   from '@/components/EntityDedupModal'
import ImportModal        from '@/components/ImportModal'
import TimeSlider, { parseOffset } from '@/components/TimeSlider'
import TimelinePanel      from '@/components/TimelinePanel'
import StatsPanel        from '@/components/StatsPanel'
import EvidenceMatrix    from '@/components/EvidenceMatrix'
import CounterfactualPanel from '@/components/CounterfactualPanel'
import HandoverPanel     from '@/components/HandoverPanel'
import ReportPanel         from '@/components/ReportPanel'
import OrchestratorPanel  from '@/components/OrchestratorPanel'
import { getGraph, seedDemo, exportSession, explainConflict } from '@/lib/api'
import type { GraphData, Claim, ClaimType, ReasoningResult, Conflict, GraphNode, DemoScenario } from '@/lib/api'
import { SESSION_KEY, shortId, confPct, essLabel, CONFLICT_SEVERITY_META, CLAIM_TYPE_META } from '@/lib/utils'
import StartScreen, { type StartMode } from '@/components/StartScreen'
import LLMConfigModal from '@/components/LLMConfigModal'

export default function Home() {
  const [appStarted,  setAppStarted]  = useState(false)
  const [sessionId,   setSessionId]   = useState<string | null>(null)
  const [graphData,   setGraphData]   = useState<GraphData>({ nodes: [], edges: [] })
  const [reasoning,   setReasoning]   = useState<ReasoningResult | null>(null)
  const [conflicts,   setConflicts]   = useState<Conflict[]>([])
  const [dismissedConflicts, setDismissedConflicts] = useState<Set<string>>(new Set())
  const [conflictIdx,        setConflictIdx]        = useState(0)
  const [graphLoading,       setGraphLoading]       = useState(false)
  const [graphError,         setGraphError]         = useState<string | null>(null)
  const [activePanel,        setActivePanel]        = useState<'data' | 'graph' | 'review'>('graph')
  const [showConflictBanner, setShowConflictBanner] = useState(true)
  const [conflictExplanation,  setConflictExplanation]  = useState('')
  const [conflictExplaining,   setConflictExplaining]   = useState(false)
  const [showAddNode,        setShowAddNode]        = useState(false)
  const [showDedup,          setShowDedup]          = useState(false)
  const [showImport,         setShowImport]         = useState(false)
  const [searchQuery,        setSearchQuery]        = useState('')
  const [debouncedSearch,    setDebouncedSearch]    = useState('')
  const [showSearch,         setShowSearch]         = useState(false)
  const [timeHours,          setTimeHours]          = useState<number>(999)
  const [seeding,            setSeeding]            = useState(false)
  const [typeFilter,         setTypeFilter]         = useState<Set<ClaimType>>(new Set())
  const [focusClaimIds,      setFocusClaimIds]      = useState<string[]>([])
  const [centerView,         setCenterView]         = useState<'orchestrator' | 'graph' | 'timeline' | 'matrix' | 'counterfactual' | 'handover' | 'report'>('orchestrator')
  const [graphLayout,        setGraphLayout]        = useState<GraphLayout>('cose')
  const [fitTrigger,         setFitTrigger]         = useState(0)
  const [showShortcuts,      setShowShortcuts]      = useState(false)
  const [showStats,          setShowStats]          = useState(false)
  const [showLLMConfig,      setShowLLMConfig]      = useState(false)
  const [demoLang,           setDemoLang]           = useState<'en' | 'de'>('en')
  const [demoScenario,       setDemoScenario]       = useState<'cap' | 'pe' | 'ards' | 'nstemi'>('cap')
  const searchInputRef = useRef<HTMLInputElement>(null)

  // ── Session ───────────────────────────────────────────────────────────────
  // Read existing session id from storage after mount (avoids SSR mismatch)
  const [existingSessionId, setExistingSessionId] = useState<string | null>(null)
  useEffect(() => { setExistingSessionId(localStorage.getItem(SESSION_KEY)) }, [])

  const handleStart = useCallback(async (mode: StartMode) => {
    if (mode.kind === 'new') {
      const id = uuidv4()
      localStorage.setItem(SESSION_KEY, id)
      setSessionId(id)
      setGraphData({ nodes: [], edges: [] })
    } else if (mode.kind === 'resume') {
      setSessionId(mode.sessionId)
    } else if (mode.kind === 'demo') {
      const id = uuidv4()
      localStorage.setItem(SESSION_KEY, id)
      setSessionId(id)
      setGraphData({ nodes: [], edges: [] })
      setDemoScenario(mode.scenario)
      setDemoLang(mode.lang)
      setAppStarted(true)
      // Auto-seed immediately using local vars (state not yet flushed)
      setSeeding(true)
      seedDemo(id, mode.lang, mode.scenario)
        .then(async result => {
          if (result.seeded) {
            const data = await getGraph(id)
            setGraphData(data)
          }
        })
        .catch(() => {})
        .finally(() => setSeeding(false))
      return
    }
    setAppStarted(true)
  }, [])

  // ── Graph ─────────────────────────────────────────────────────────────────
  const refreshGraph = useCallback(async () => {
    if (!sessionId) return
    setGraphLoading(true)
    try {
      const data = await getGraph(sessionId)
      setGraphData(data)
      setGraphError(null)
    } catch (err) {
      console.error(err)
      setGraphError(err instanceof Error ? err.message : 'Failed to load graph data')
    } finally {
      setGraphLoading(false)
    }
  }, [sessionId])

  useEffect(() => { if (sessionId) refreshGraph() }, [sessionId, refreshGraph])

  // ── Debounce search query ─────────────────────────────────────────────────
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchQuery), 300)
    return () => clearTimeout(t)
  }, [searchQuery])

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
        related_to:             n.related_to ?? [],
        status:                 n.status      ?? 'active',
        time_offset:            n.time_offset ?? null,
        trend:                  n.trend       ?? 'unknown',
        entities:               [],
        relations:              [],
        claimId:                n.claimId,
        created_at:             n.created_at,
        notes:                  n.notes ?? '',
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
      if (debouncedSearch) {
        const q = debouncedSearch.toLowerCase()
        const match =
          n.fullText?.toLowerCase().includes(q) ||
          n.label.toLowerCase().includes(q) ||
          n.claim_type?.toLowerCase().includes(q) ||
          n.status?.toLowerCase().includes(q) ||
          n.source_ref?.toLowerCase().includes(q) ||
          n.source_type?.toLowerCase().includes(q) ||
          n.trend?.toLowerCase().includes(q) ||
          n.time_offset?.toLowerCase().includes(q)
        if (!match) return
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
  }, [graphData, timeHours, debouncedSearch, typeFilter, nodeById])

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

  // ── Conflict sorting/filtering — declared early so handleExplainConflict can reference shownConflict ──
  const sortedConflicts = useMemo(() => [
    ...conflicts.filter(c => c.severity === 'error'),
    ...conflicts.filter(c => c.severity === 'warning'),
    ...conflicts.filter(c => c.severity === 'info'),
  ], [conflicts])

  const activeConflicts = useMemo(
    () => sortedConflicts.filter(c => !dismissedConflicts.has(c.id)),
    [sortedConflicts, dismissedConflicts],
  )

  const safeIdx       = activeConflicts.length === 0 ? 0 : conflictIdx % activeConflicts.length
  const shownConflict = activeConflicts[safeIdx] ?? null

  // Keep idx in bounds; reset when conflict list changes
  useEffect(() => { setConflictIdx(0) }, [conflicts])

  // Clear explanation when the shown conflict changes
  useEffect(() => { setConflictExplanation(''); setConflictExplaining(false) }, [shownConflict?.id])

  // ── Explain conflict (extracted for keyboard shortcut) ────────────────────
  const handleExplainConflict = useCallback(async () => {
    if (!sessionId || !shownConflict || conflictExplaining) return
    setConflictExplaining(true)
    setConflictExplanation('')
    try {
      const text = await explainConflict(sessionId, shownConflict)
      setConflictExplanation(text)
    } catch { /* LLM may be unavailable */ }
    finally { setConflictExplaining(false) }
  }, [sessionId, shownConflict, conflictExplaining])

  // ── Keyboard shortcuts ────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement).isContentEditable) return
      switch (e.key) {
        case '/':
          e.preventDefault()
          setShowSearch(true)
          setTimeout(() => searchInputRef.current?.focus(), 50)
          break
        case 'Escape':
          setShowAddNode(false); setShowDedup(false); setShowImport(false)
          setShowSearch(false); setSearchQuery('')
          break
        case 'j':
          setConflictIdx(i => activeConflicts.length > 0 ? (i + 1) % activeConflicts.length : i)
          break
        case 'k':
          setConflictIdx(i => activeConflicts.length > 0 ? (i - 1 + activeConflicts.length) % activeConflicts.length : i)
          break
        case 'e':
          handleExplainConflict()
          break
        case 'f':
          setFitTrigger(t => t + 1)
          break
        case 'n':
          setShowAddNode(true)
          break
        case '?':
          setShowShortcuts(v => !v)
          break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [activeConflicts.length, handleExplainConflict])

  // ── Demo seed ─────────────────────────────────────────────────────────────
  const handleSeedDemo = async () => {
    if (!sessionId) return
    setSeeding(true)
    try {
      const result = await seedDemo(sessionId, demoLang, demoScenario)
      if (result.seeded) await refreshGraph()
      else alert(result.reason ?? 'Session already has data')
    } catch (e: any) {
      alert('Seed failed: ' + e.message)
    } finally {
      setSeeding(false)
    }
  }

  // ── Export ────────────────────────────────────────────────────────────────
  const handleExport = async () => {
    if (!sessionId) return
    try {
      const data = await exportSession(sessionId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `alexiona-session-${sessionId.slice(0, 8)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: any) {
      alert('Export failed: ' + e.message)
    }
  }

  // ── Report (PDF) ──────────────────────────────────────────────────────────
  const handleGenerateReport = async () => {
    if (!reasoning) return
    const { jsPDF } = await import('jspdf')
    const doc  = new jsPDF({ unit: 'mm', format: 'a4' })
    const W    = 190  // usable width
    const ml   = 10   // left margin
    let   y    = 15

    const line = (text: string, size = 10, style: 'normal' | 'bold' = 'normal', color = '#111111') => {
      doc.setFontSize(size)
      doc.setFont('helvetica', style)
      doc.setTextColor(color)
      const lines = doc.splitTextToSize(text, W)
      lines.forEach((l: string) => {
        if (y > 275) { doc.addPage(); y = 15 }
        doc.text(l, ml, y)
        y += size * 0.45
      })
      y += 1
    }

    const section = (title: string) => {
      y += 3
      if (y > 270) { doc.addPage(); y = 15 }
      doc.setDrawColor('#e5e7eb')
      doc.setLineWidth(0.3)
      doc.line(ml, y, ml + W, y)
      y += 4
      line(title, 11, 'bold', '#1d4ed8')
      y += 1
    }

    // Header
    line('AleXiona – Clinical Reasoning Report', 16, 'bold', '#111827')
    line(`Session: ${sessionId}   |   ${new Date().toLocaleString()}`, 8, 'normal', '#6b7280')
    line('This report is a reasoning aid. All conclusions require clinician verification.', 8, 'normal', '#ef4444')
    y += 2

    section('Leading Hypothesis')
    line(reasoning.leading_hypothesis, 11, 'bold')
    line(`Evidence support: ${essLabel(reasoning.evidence_support_score)} (internal score, not a probability)`, 10)

    if (reasoning.supporting_evidence.length > 0) {
      section('Supporting Evidence')
      reasoning.supporting_evidence.forEach(e => line(`+ ${e}`, 9))
    }

    if (reasoning.conflicting_evidence.length > 0) {
      section('Conflicting Evidence')
      reasoning.conflicting_evidence.forEach(e => line(`! ${e}`, 9))
    }

    if (reasoning.missing_evidence.length > 0) {
      section('Missing Evidence')
      reasoning.missing_evidence.forEach(m =>
        line(`- ${m.test_or_type}: ${m.description}  [clarifies: ${m.needed_for}]`, 9))
    }

    if (reasoning.alternatives.length > 0) {
      section('Alternative Hypotheses')
      reasoning.alternatives.forEach(a =>
        line(`- ${a.label}  [${essLabel(a.evidence_support_score)} support]`, 9))
    }

    if (conflicts.length > 0) {
      section('Conflicts Detected')
      conflicts.forEach(c =>
        line(`[${c.severity.toUpperCase()}] ${c.message}`, 9))
    }

    section(`Evidence Nodes (${allClaims.length})`)
    allClaims.forEach(c =>
      line(`[${c.claim_type?.toUpperCase() ?? 'UNKNOWN'} · ${essLabel(c.evidence_support_score)} support · ${c.status}]  ${c.text}`, 9))

    doc.save(`alexiona-report-${shortId(sessionId ?? '')}.pdf`)
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

  const CLAIM_TYPES = Object.keys(CLAIM_TYPE_META) as ClaimType[]

  // ── Start screen ────────────────────────────────────────────────────────
  if (!appStarted) {
    return <StartScreen existingSessionId={existingSessionId} onStart={handleStart} />
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: 'var(--bg)' }}>

      {/* ── Global error banner ───────────────────────────────────────────── */}
      {graphError && (
        <div className="px-4 py-2 text-xs flex items-center gap-2 shrink-0"
          style={{ background: '#fef2f2', color: '#dc2626', borderBottom: '1px solid #fca5a5' }}>
          <span className="flex-1">⚠ {graphError}</span>
          <button onClick={() => setGraphError(null)} className="font-bold" aria-label="dismiss">×</button>
        </div>
      )}

      {/* ── Add Node Modal ────────────────────────────────────────────────── */}
      {showAddNode && (
        <AddNodeModal
          sessionId={sessionId}
          onClose={() => setShowAddNode(false)}
          onCreated={refreshGraph}
          allClaims={allClaims}
        />
      )}

      {/* ── Entity Dedup Modal ────────────────────────────────────────────── */}
      {showDedup && (
        <EntityDedupModal
          sessionId={sessionId!}
          onClose={() => setShowDedup(false)}
          onMerged={refreshGraph}
        />
      )}

      {/* ── Import Modal ──────────────────────────────────────────────────── */}
      {showImport && (
        <ImportModal
          sessionId={sessionId!}
          onClose={() => setShowImport(false)}
          onImported={refreshGraph}
        />
      )}

      {/* ── LLM Config Modal ─────────────────────────────────────────────── */}
      {showLLMConfig && (
        <LLMConfigModal onClose={() => setShowLLMConfig(false)} />
      )}

      {/* ── Keyboard Shortcuts Overlay ───────────────────────────────────── */}
      {showShortcuts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: 'rgba(0,0,0,0.4)' }}
          onClick={() => setShowShortcuts(false)}>
          <div className="rounded-2xl shadow-2xl p-6 w-80"
            style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
            onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <span className="font-semibold text-sm">Keyboard Shortcuts</span>
              <button onClick={() => setShowShortcuts(false)} style={{ color: 'var(--text-muted)' }}>✕</button>
            </div>
            <div className="space-y-2 text-xs">
              {([
                ['/', 'Open search'],
                ['Esc', 'Close modals / search'],
                ['j / k', 'Next / prev conflict'],
                ['e', 'Explain current conflict'],
                ['f', 'Fit graph to screen'],
                ['n', 'New evidence node'],
                ['?', 'Toggle this panel'],
              ] as [string, string][]).map(([key, desc]) => (
                <div key={key} className="flex items-center justify-between">
                  <code className="px-1.5 py-0.5 rounded text-xs font-mono"
                    style={{ background: 'var(--surface-2)', color: 'var(--text)' }}>{key}</code>
                  <span style={{ color: 'var(--text-muted)' }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Conflict Banner ───────────────────────────────────────────────── */}
      {showConflictBanner && activeConflicts.length > 0 && shownConflict && (() => {
        const meta  = CONFLICT_SEVERITY_META[shownConflict.severity]
        const total = activeConflicts.length
        const num   = safeIdx + 1
        return (
          <div className="flex items-center gap-2 px-3 py-1.5 shrink-0"
            style={{ background: meta.bg, borderBottom: `1px solid ${meta.border}` }}>

            {/* Severity icon */}
            <span className="shrink-0 text-sm">{meta.icon}</span>

            {/* Navigation — only when multiple active conflicts */}
            {total > 1 && (
              <div className="flex items-center gap-0.5 shrink-0">
                <button
                  className="w-5 h-5 rounded flex items-center justify-center hover:opacity-70"
                  style={{ color: meta.text, background: meta.border + '55' }}
                  onClick={() => setConflictIdx(i => (i - 1 + total) % total)}
                  title="Previous conflict">‹</button>
                <span className="text-xs font-mono px-1" style={{ color: meta.text }}>
                  {num}/{total}
                </span>
                <button
                  className="w-5 h-5 rounded flex items-center justify-center hover:opacity-70"
                  style={{ color: meta.text, background: meta.border + '55' }}
                  onClick={() => setConflictIdx(i => (i + 1) % total)}
                  title="Next conflict">›</button>
              </div>
            )}

            {/* Message — clickable → focus nodes */}
            <button className="flex-1 text-left text-xs font-medium truncate hover:underline"
              style={{ color: meta.text }}
              onClick={() => {
                setFocusClaimIds([...shownConflict.affected_claim_ids])
                setActivePanel('graph')
              }}>
              {shownConflict.message}
              <span className="ml-1 opacity-50 font-normal">(click to focus)</span>
            </button>

            {/* Explain this conflict */}
            {sessionId && (
              <button
                className="shrink-0 text-xs px-2 py-0.5 rounded hover:opacity-70 disabled:opacity-40"
                style={{ color: meta.text, background: meta.border + '55' }}
                disabled={conflictExplaining}
                onClick={handleExplainConflict}
                title="Get LLM explanation for this conflict">
                {conflictExplaining ? '…' : '✦ Explain'}
              </button>
            )}

            {/* Dismiss this conflict */}
            <button
              className="shrink-0 text-xs px-2 py-0.5 rounded hover:opacity-70"
              style={{ color: meta.text, background: meta.border + '55' }}
              onClick={() => setDismissedConflicts(prev => new Set(Array.from(prev).concat(shownConflict.id)))}
              title="Dismiss this conflict">
              Dismiss
            </button>

            {/* Close banner */}
            <button
              className="shrink-0 w-5 h-5 flex items-center justify-center rounded hover:opacity-70"
              style={{ color: meta.text }}
              onClick={() => setShowConflictBanner(false)}
              title="Hide conflict bar">✕</button>
          </div>
        )
      })()}

      {/* ── Conflict explanation panel ─────────────────────────────────────── */}
      {showConflictBanner && conflictExplanation && (() => {
        const meta = CONFLICT_SEVERITY_META[shownConflict?.severity ?? 'info']
        return (
          <div className="px-4 py-2 text-xs shrink-0 flex items-start gap-2"
            style={{ background: meta.bg + 'cc', borderBottom: `1px solid ${meta.border}` }}>
            <span className="shrink-0 opacity-60 mt-0.5">✦</span>
            <p style={{ color: meta.text, lineHeight: 1.6 }}>{conflictExplanation}</p>
            <button className="shrink-0 opacity-50 hover:opacity-80 ml-auto"
              style={{ color: meta.text }}
              onClick={() => setConflictExplanation('')}>✕</button>
          </div>
        )
      })()}

      {/* ── Top Nav ───────────────────────────────────────────────────────── */}
      <nav className="top-nav flex items-center justify-between px-4 py-2.5 shrink-0">

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
              style={{ background: 'linear-gradient(135deg, var(--brand) 0%, var(--teal) 100%)' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.8">
                <path d="M12 2L4 7v10l8 5 8-5V7L12 2z" />
                <path d="M12 2v20M4 7l8 5 8-5" />
              </svg>
            </div>
            <span className="text-base font-bold tracking-tight" style={{ letterSpacing: '-0.02em' }}>
              Ale<span className="gradient-text">X</span>iona
            </span>
          </div>
          <div className="hidden sm:block border-l pl-3 ml-1" style={{ borderColor: 'var(--border)' }}>
            <span className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>AI Clinical Evidence Graph</span>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-4 text-xs" style={{ color: 'var(--text-muted)' }}>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg" style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <span className="font-semibold tabular-nums" style={{ color: 'var(--brand-light)' }}>{claimCount}</span>
            <span style={{ color: 'var(--text-light)' }}>claims</span>
          </div>
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg" style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
            <span className="font-semibold tabular-nums" style={{ color: 'var(--teal)' }}>{entityCount}</span>
            <span style={{ color: 'var(--text-light)' }}>entities</span>
          </div>
          {conflicts.length > 0 && (
            <button className="flex items-center gap-1 hover:opacity-70"
              style={{ color: conflicts.some(c => c.severity === 'error') ? '#ef4444' : '#f59e0b' }}
              onClick={() => { setShowConflictBanner(true); setDismissedConflicts(new Set()) }}
              title={dismissedConflicts.size > 0 ? 'Some conflicts dismissed — click to restore' : undefined}>
              ⚠ {activeConflicts.length}/{conflicts.length} conflict{conflicts.length !== 1 ? 's' : ''}
              {dismissedConflicts.size > 0 && <span className="opacity-50">({dismissedConflicts.size} dismissed)</span>}
            </button>
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
            <div className="hidden sm:flex items-center rounded-lg overflow-hidden border"
              style={{ borderColor: 'var(--brand)' }}>
              <button onClick={handleSeedDemo} disabled={seeding}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 font-medium transition-all disabled:opacity-50"
                style={{ background: 'var(--brand-pale)', color: 'var(--brand)' }}>
                {seeding ? '…' : '▶ Demo'}
              </button>
              {/* Scenario selector */}
              <div className="flex border-l" style={{ borderColor: 'var(--brand)' }}>
                {([
                  ['cap',    'CAP'],
                  ['pe',     'PE'],
                  ['ards',   'ARDS'],
                  ['nstemi', 'NSTEMI'],
                ] as [DemoScenario, string][]).map(([s, label]) => (
                  <button key={s} onClick={() => setDemoScenario(s)}
                    className="text-xs px-2 py-1.5 font-medium"
                    title={{ cap: 'Community-Acquired Pneumonia', pe: 'Pulmonary Embolism', ards: 'ARDS + Septic Shock', nstemi: 'Non-ST Elevation MI' }[s]}
                    style={{
                      background: demoScenario === s ? 'var(--brand)' : 'var(--brand-pale)',
                      color:      demoScenario === s ? 'white'        : 'var(--brand)',
                    }}>
                    {label}
                  </button>
                ))}
              </div>
              {/* Language selector */}
              <div className="flex border-l" style={{ borderColor: 'var(--brand)' }}>
                {(['en', 'de'] as const).map(l => (
                  <button key={l} onClick={() => setDemoLang(l)}
                    className="text-xs px-2 py-1.5 font-medium uppercase"
                    style={{
                      background: demoLang === l ? 'var(--teal)' : 'var(--teal-pale)',
                      color:      demoLang === l ? 'white'       : 'var(--teal)',
                    }}>
                    {l}
                  </button>
                ))}
              </div>
            </div>
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
          {/* Export */}
          <button onClick={handleExport}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70"
            style={{ background: 'transparent', color: 'var(--text-muted)' }}
            title="Export session as JSON">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
          </button>
          {/* Import */}
          <button onClick={() => setShowImport(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70"
            style={{ background: 'transparent', color: 'var(--text-muted)' }}
            title="Import session from JSON">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
              <polyline points="17 8 12 3 7 8"/>
              <line x1="12" y1="3" x2="12" y2="15"/>
            </svg>
          </button>
          {/* Entity dedup */}
          <button onClick={() => setShowDedup(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70"
            style={{ background: 'transparent', color: 'var(--text-muted)' }}
            title="Deduplicate entities">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="8" cy="8" r="4"/><circle cx="16" cy="16" r="4"/>
              <line x1="12" y1="8" x2="16" y2="8"/><line x1="8" y1="12" x2="8" y2="16"/>
            </svg>
          </button>
          <button onClick={() => setShowAddNode(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70"
            style={{ background: 'var(--brand)', color: 'white' }}
            title="Add evidence node">
            +
          </button>
          <button onClick={() => setShowLLMConfig(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70"
            style={{ background: 'transparent', color: 'var(--text-muted)' }}
            title="KI-Konfiguration">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
          </button>
          <button onClick={() => setShowShortcuts(v => !v)}
            className="w-8 h-8 rounded-lg flex items-center justify-center hover:opacity-70 text-xs"
            style={{ background: 'transparent', color: 'var(--text-muted)' }}
            title="Keyboard shortcuts (?)">
            ?
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
            ref={searchInputRef}
            autoFocus
            type="text"
            placeholder="Search claims and entities… (/ to focus)"
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
            searchQuery={debouncedSearch}
          />
        </div>

        {/* CENTER: Graph */}
        <div className={`flex-col flex-1 overflow-hidden md:flex
            ${activePanel === 'graph' ? 'flex' : 'hidden'}`}>

          {/* Graph sub-header */}
          <div className="border-b shrink-0"
            style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border-light)' }}>
            <div className="px-4 py-2 flex items-center justify-between">
              {/* Graph / Timeline toggle */}
              <div className="flex rounded-lg overflow-hidden text-xs p-0.5"
                style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                {([
                  ['orchestrator',    '◎ Zustand'],
                  ['graph',           '◈ Graph'],
                  ['timeline',        '⏱ Timeline'],
                  ['matrix',          '⊞ Matrix'],
                  ['counterfactual',  '💡 What-If?'],
                  ['handover',        '📋 Übergabe'],
                  ['report',          '📝 Bericht'],
                ] as [typeof centerView, string][]).map(([v, label]) => (
                  <button key={v} onClick={() => setCenterView(v)}
                    className="px-2.5 py-1 rounded-md transition-all"
                    style={{
                      background: centerView === v ? 'var(--brand)' : 'transparent',
                      color:      centerView === v ? 'white' : 'var(--text-muted)',
                      boxShadow:  centerView === v ? '0 1px 4px rgba(59,142,234,0.4)' : 'none',
                    }}>
                    {label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                {/* Layout picker */}
                {centerView === 'graph' && (
                  <div className="flex rounded-lg overflow-hidden text-xs p-0.5"
                    style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>
                    {([
                      ['cose',         '⊛', 'Force'],
                      ['breadthfirst', '⊤', 'Tree'],
                      ['concentric',   '◎', 'Ring'],
                      ['grid',         '⊞', 'Grid'],
                    ] as [GraphLayout, string, string][]).map(([name, icon, label]) => (
                      <button key={name} onClick={() => setGraphLayout(name)}
                        className="px-2 py-1 rounded-md flex items-center gap-0.5 transition-all"
                        title={`${label} layout`}
                        style={{
                          background: graphLayout === name ? 'var(--surface-3)' : 'transparent',
                          color:      graphLayout === name ? 'var(--text)'      : 'var(--text-muted)',
                        }}>
                        <span>{icon}</span>
                        <span className="hidden lg:inline">{label}</span>
                      </button>
                    ))}
                  </div>
                )}
                {centerView === 'graph' && (
                  <button onClick={() => setShowStats(v => !v)}
                    className="text-xs px-2 py-1 rounded-lg border"
                    style={{
                      background: showStats ? 'var(--brand-pale)' : 'var(--surface)',
                      color:      showStats ? 'var(--brand)'      : 'var(--text-muted)',
                      borderColor: showStats ? 'var(--brand)'     : 'var(--border)',
                    }}
                    title="Toggle stats panel">
                    ◈ Stats
                  </button>
                )}
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

            {/* Stats panel — only in graph mode, toggled */}
            {centerView === 'graph' && showStats && (
              <StatsPanel data={filteredGraph} />
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
                layout={graphLayout}
                fitTrigger={fitTrigger}
              />
            </div>
            {/* Time slider — inside graph mode only */}
            {maxTimeOffset > 0 && (
              <div className="px-4 py-2 border-t shrink-0"
                style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border-light)' }}>
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

          {/* Evidence-Impact-Matrix */}
          {centerView === 'matrix' && (
            <div className="flex-1 overflow-auto">
              {reasoning ? (
                <EvidenceMatrix reasoning={reasoning} claims={allClaims} />
              ) : (
                <div className="flex flex-col items-center justify-center h-full gap-2"
                  style={{ color: 'var(--text-muted)' }}>
                  <span className="text-3xl">⊞</span>
                  <p className="text-sm">Sende zuerst eine Nachricht, um die Reasoning-Daten zu laden.</p>
                </div>
              )}
            </div>
          )}

          {/* Counterfactual Panel */}
          {centerView === 'counterfactual' && sessionId && (
            <div className="flex-1 overflow-hidden">
              <CounterfactualPanel claims={allClaims} sessionId={sessionId} />
            </div>
          )}

          {/* Clinical Handover / Übergabe */}
          {centerView === 'handover' && sessionId && (
            <div className="flex-1 overflow-hidden">
              <HandoverPanel
                reasoning={reasoning}
                claims={allClaims}
                conflicts={conflicts}
                sessionId={sessionId}
              />
            </div>
          )}

          {/* Clinical Reports — Arztbrief, Entlassbrief, Konsilbrief, Befundbericht */}
          {centerView === 'report' && sessionId && (
            <div className="flex-1 overflow-hidden">
              <ReportPanel sessionId={sessionId} />
            </div>
          )}

          {/* Clinical Orchestrator — single unified clinical state */}
          {centerView === 'orchestrator' && sessionId && (
            <div className="flex-1 overflow-hidden">
              <OrchestratorPanel sessionId={sessionId} />
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
            sessionId={sessionId}
            onGenerateReport={handleGenerateReport}
            onClear={() => setReasoning(null)}
          />
        </div>

      </div>
    </div>
  )
}
