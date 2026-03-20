'use client'

import { useState, useEffect, useCallback } from 'react'
import type { ReasoningResult, Claim, Conflict } from '@/lib/api'
import { confPct } from '@/lib/utils'

interface Props {
  reasoning:  ReasoningResult | null
  claims:     Claim[]
  conflicts:  Conflict[]
  sessionId:  string
}

interface Section {
  key:   string
  title: string
  icon:  string
  text:  string
}

function buildSections(reasoning: ReasoningResult | null, claims: Claim[], conflicts: Conflict[]): Section[] {
  const active = claims.filter(c => c.status === 'active')

  const leitdiagnose = reasoning
    ? `${reasoning.leading_hypothesis} (ESS ${confPct(reasoning.evidence_support_score)}%)`
    : '—'

  const schlüsselbefunde = reasoning
    ? reasoning.supporting_evidence.map(e => `+ ${e}`).join('\n') +
      (reasoning.conflicting_evidence.length > 0
        ? '\n\n! Konflikte:\n' + reasoning.conflicting_evidence.map(e => `! ${e}`).join('\n')
        : '')
    : active.slice(0, 10).map(c => `• ${c.text}`).join('\n') || '—'

  const differential = reasoning && reasoning.alternatives.length > 0
    ? reasoning.alternatives
        .map(a => `• ${a.label} (${confPct(a.evidence_support_score)}%)`)
        .join('\n')
    : '—'

  const offeneDiagnostik = reasoning && reasoning.missing_evidence.length > 0
    ? reasoning.missing_evidence
        .map(m => `• ${m.description} [${m.test_or_type}] — benötigt für: ${m.needed_for}`)
        .join('\n')
    : '—'

  const aktiveProbleme = active
    .filter(c => ['symptom', 'finding', 'risk_factor'].includes(c.claim_type ?? ''))
    .slice(0, 15)
    .map(c => `• ${c.text}`)
    .join('\n') || '—'

  const conflictText = conflicts.length > 0
    ? conflicts.map(c => `[${c.severity.toUpperCase()}] ${c.message}`).join('\n')
    : '—'

  return [
    { key: 'leitdiagnose',   title: 'Leitdiagnose',        icon: '🎯', text: leitdiagnose      },
    { key: 'differential',   title: 'Differentialdiagnose', icon: '⚖',  text: differential      },
    { key: 'befunde',        title: 'Schlüsselbefunde',     icon: '🔬', text: schlüsselbefunde  },
    { key: 'probleme',       title: 'Aktive Probleme',      icon: '⚕',  text: aktiveProbleme   },
    { key: 'diagnostik',     title: 'Offene Diagnostik',    icon: '📋', text: offeneDiagnostik  },
    { key: 'konflikte',      title: 'Befundkonflikte',      icon: '⚠',  text: conflictText      },
    { key: 'massnahmen',     title: 'Maßnahmen / Plan',     icon: '✅', text: ''                },
    { key: 'besonderheiten', title: 'Besonderheiten',       icon: '📌', text: ''                },
  ]
}

export default function HandoverPanel({ reasoning, claims, conflicts, sessionId }: Props) {
  const [sections, setSections] = useState<Section[]>(() =>
    buildSections(reasoning, claims, conflicts)
  )
  const [saving,  setSaving]  = useState(false)
  const [copied,  setCopied]  = useState(false)

  // Re-generate when inputs change (only non-edited sections)
  useEffect(() => {
    setSections(buildSections(reasoning, claims, conflicts))
  }, [reasoning, claims, conflicts])

  const updateSection = useCallback((key: string, text: string) => {
    setSections(prev => prev.map(s => s.key === key ? { ...s, text } : s))
  }, [])

  const handleCopy = useCallback(async () => {
    const text = sections
      .map(s => `── ${s.title} ──\n${s.text || '—'}`)
      .join('\n\n')
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [sections])

  const handlePDF = useCallback(async () => {
    setSaving(true)
    try {
      const { jsPDF } = await import('jspdf')
      const doc  = new jsPDF({ unit: 'mm', format: 'a4' })
      let   y    = 18
      const lm   = 18
      const pw   = 174

      const line = (text: string, sz: number, style: 'normal' | 'bold' = 'normal', color = '#1f2937') => {
        doc.setFontSize(sz)
        doc.setFont('helvetica', style)
        doc.setTextColor(color)
        const lines = doc.splitTextToSize(text, pw)
        for (const l of lines) {
          if (y > 275) { doc.addPage(); y = 18 }
          doc.text(l, lm, y)
          y += sz * 0.45
        }
        y += 1
      }

      // Header
      doc.setFillColor(26, 122, 179)
      doc.rect(0, 0, 210, 12, 'F')
      doc.setTextColor('#ffffff')
      doc.setFontSize(11)
      doc.setFont('helvetica', 'bold')
      doc.text('AleXiona — Klinischer Übergabebericht', lm, 8)
      doc.setFontSize(8)
      doc.setFont('helvetica', 'normal')
      doc.text(`Session: ${sessionId.slice(0, 8)}   |   ${new Date().toLocaleString('de-DE')}`, 140, 8)
      y = 20

      for (const s of sections) {
        if (!s.text || s.text === '—') continue
        line(`${s.title}`, 10, 'bold')
        for (const ln of s.text.split('\n')) {
          line(ln || ' ', 9)
        }
        y += 3
      }

      // Footer
      const pg = doc.getNumberOfPages()
      for (let i = 1; i <= pg; i++) {
        doc.setPage(i)
        doc.setFontSize(7)
        doc.setFont('helvetica', 'normal')
        doc.setTextColor('#9ca3af')
        doc.text('Dieser Bericht ist ein Unterstützungswerkzeug. Alle klinischen Entscheidungen obliegen dem behandelnden Arzt.', lm, 290)
        doc.text(`Seite ${i}/${pg}`, 190, 290, { align: 'right' })
      }

      doc.save(`alexiona-übergabe-${sessionId.slice(0, 8)}.pdf`)
    } finally {
      setSaving(false)
    }
  }, [sections, sessionId])

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b shrink-0 flex items-center justify-between"
        style={{ borderColor: 'var(--border)' }}>
        <div>
          <div className="font-semibold text-sm" style={{ color: 'var(--text)' }}>Klinischer Übergabemodus</div>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            Automatisch befüllt · alle Felder editierbar
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={handleCopy}
            className="text-xs px-2.5 py-1 rounded-lg border transition-colors"
            style={{
              background: copied ? 'var(--brand-pale)' : 'var(--surface-2)',
              color: copied ? 'var(--brand)' : 'var(--text-muted)',
              borderColor: 'var(--border)',
            }}>
            {copied ? '✓ Kopiert' : '⎘ Kopieren'}
          </button>
          <button onClick={handlePDF} disabled={saving}
            className="text-xs px-2.5 py-1 rounded-lg border transition-colors disabled:opacity-50"
            style={{
              background: 'var(--brand)',
              color: 'white',
              borderColor: 'var(--brand)',
            }}>
            {saving ? '…' : '↓ PDF'}
          </button>
        </div>
      </div>

      {/* Sections */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {sections.map(s => (
          <div key={s.key}>
            <label className="flex items-center gap-1.5 text-xs font-semibold mb-1"
              style={{ color: 'var(--text)' }}>
              <span>{s.icon}</span>
              {s.title}
            </label>
            <textarea
              value={s.text}
              onChange={e => updateSection(s.key, e.target.value)}
              rows={s.text ? Math.min(10, Math.max(2, s.text.split('\n').length + 1)) : 2}
              placeholder={`${s.title} hier eingeben…`}
              className="w-full rounded-lg text-xs px-3 py-2 resize-y outline-none transition-colors"
              style={{
                background:   'var(--surface-2)',
                color:        'var(--text)',
                border:       '1px solid var(--border)',
                fontFamily:   'inherit',
                lineHeight:   1.6,
                minHeight:    '48px',
              }}
              onFocus={e => { e.target.style.borderColor = 'var(--brand)' }}
              onBlur={e =>  { e.target.style.borderColor = 'var(--border)' }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
