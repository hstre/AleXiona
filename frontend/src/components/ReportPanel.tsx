'use client'

import { useState, useCallback } from 'react'
import { generateReport } from '@/lib/api'
import type { ClinicalReport, ReportSection, ReportPatientContext } from '@/lib/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PatientContext {
  name:         string
  geburtsdatum: string
  aufnahme:     string
  entlassung:   string
  station:      string
  zuweiser:     string
}

interface ReportTypeDef {
  key:         string
  title:       string
  description: string
}

const REPORT_TYPES: ReportTypeDef[] = [
  { key: 'arztbrief',    title: 'Arztbrief',      description: 'Vollständiger Arzt-/Entlassbrief mit allen klinischen Abschnitten' },
  { key: 'entlassbrief', title: 'Entlassbrief',   description: 'Kurzarztbrief — fokussiert auf Diagnosen, Therapie und Procedere' },
  { key: 'konsilbrief',  title: 'Konsiliarbrief', description: 'Antwortschreiben auf eine Konsiliarbestellung' },
  { key: 'befundbericht',title: 'Befundbericht',  description: 'Strukturierter Befundbericht (Labor, Bildgebung, EKG)' },
]

interface Props {
  sessionId: string
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function ReportPanel({ sessionId }: Props) {
  const [reportType, setReportType]   = useState<string>('arztbrief')
  const [patient, setPatient]         = useState<PatientContext>({
    name: '', geburtsdatum: '', aufnahme: '', entlassung: '', station: '', zuweiser: '',
  })
  const [showPatient, setShowPatient] = useState(false)
  const [report, setReport]           = useState<ClinicalReport | null>(null)
  const [sections, setSections]       = useState<ReportSection[]>([])
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [saving, setSaving]           = useState(false)
  const [copied, setCopied]           = useState(false)

  const handleGenerate = useCallback(async () => {
    setLoading(true)
    setError(null)
    setReport(null)
    setSections([])
    try {
      const patCtx = Object.fromEntries(
        Object.entries(patient).filter(([, v]) => v.trim() !== '')
      ) as ReportPatientContext
      const data = await generateReport(
        sessionId,
        reportType,
        Object.keys(patCtx).length > 0 ? patCtx : undefined,
      )
      setReport(data)
      setSections(data.sections)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [sessionId, reportType, patient])

  const updateSection = (key: string, text: string) => {
    setSections(prev => prev.map(s => s.key === key ? { ...s, text } : s))
  }

  const handleCopy = useCallback(async () => {
    if (!report) return
    const text = [
      `${report.title}`,
      `Erstellt: ${new Date(report.generated_at).toLocaleString('de-DE')}`,
      '',
      ...sections.map(s => `${s.title}\n${s.text}`),
      '',
      'Dieser Bericht ist ein Unterstützungswerkzeug. Alle klinischen Entscheidungen obliegen dem behandelnden Arzt.',
    ].join('\n\n')
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [report, sections])

  const handlePDF = useCallback(async () => {
    if (!report) return
    setSaving(true)
    try {
      const { jsPDF } = await import('jspdf')
      const doc  = new jsPDF({ unit: 'mm', format: 'a4' })
      let   y    = 20
      const lm   = 20
      const rm   = 190
      const pw   = rm - lm

      const nextLine = (h: number) => {
        if (y + h > 278) { doc.addPage(); y = 20 }
      }
      const writeLine = (text: string, sz: number, style: 'normal' | 'bold' = 'normal', color = '#1f2937') => {
        doc.setFontSize(sz); doc.setFont('helvetica', style); doc.setTextColor(color)
        const lines = doc.splitTextToSize(text, pw)
        for (const l of lines) {
          nextLine(sz * 0.42 + 1)
          doc.text(l, lm, y)
          y += sz * 0.42
        }
        y += 1.5
      }

      // ── Briefkopf ─────────────────────────────────────────────────────────
      doc.setFillColor(15, 55, 100)
      doc.rect(0, 0, 210, 14, 'F')
      doc.setTextColor('#ffffff')
      doc.setFontSize(11); doc.setFont('helvetica', 'bold')
      doc.text('AleXiona', lm, 9)
      doc.setFontSize(8); doc.setFont('helvetica', 'normal')
      doc.text('Klinisches Reasoning-System', lm, 12.5)
      doc.text(new Date(report.generated_at).toLocaleString('de-DE'), rm, 9, { align: 'right' })
      doc.text(`Session ${sessionId.slice(0, 8)}`, rm, 12.5, { align: 'right' })
      y = 22

      // ── Betreff ───────────────────────────────────────────────────────────
      const patName  = patient.name.trim()
      const patDOB   = patient.geburtsdatum.trim()
      const patAdm   = patient.aufnahme.trim()
      const patWard  = patient.station.trim()
      const zuweiser = patient.zuweiser.trim()

      if (zuweiser) {
        writeLine(zuweiser, 9)
        y += 2
      }
      writeLine(report.title, 13, 'bold', '#0f3764')
      if (patName)  writeLine(`Patient / Patientin: ${patName}${patDOB ? `, * ${patDOB}` : ''}`, 9)
      if (patAdm)   writeLine(`Aufnahmedatum: ${patAdm}${patWard ? `   |   Station: ${patWard}` : ''}`, 9)

      // ── Trennlinie ────────────────────────────────────────────────────────
      y += 2
      doc.setDrawColor('#0f3764')
      doc.setLineWidth(0.4)
      doc.line(lm, y, rm, y)
      y += 5

      // ── Abschnitte ────────────────────────────────────────────────────────
      for (const s of sections) {
        if (!s.text || s.text === '[nicht dokumentiert]') continue
        writeLine(s.title, 10, 'bold', '#0f3764')
        writeLine(s.text, 9)
        y += 3
      }

      // ── Disclaimer + Seitenzahlen ─────────────────────────────────────────
      const pg = doc.getNumberOfPages()
      for (let i = 1; i <= pg; i++) {
        doc.setPage(i)
        doc.setFontSize(7); doc.setFont('helvetica', 'normal'); doc.setTextColor('#9ca3af')
        doc.text(
          'Dieser Bericht wurde maschinell unterstützt erstellt und ersetzt keine ärztliche Beurteilung.',
          lm, 288
        )
        doc.text(`Seite ${i}/${pg}`, rm, 288, { align: 'right' })
      }

      const fileName = `alexiona-${reportType}-${sessionId.slice(0, 8)}.pdf`
      doc.save(fileName)
    } finally {
      setSaving(false)
    }
  }, [report, sections, patient, reportType, sessionId])

  // ── Render ─────────────────────────────────────────────────────────────────

  const btnBase = 'px-3 py-1.5 rounded-md text-sm font-medium transition-colors'
  const btnPrimary = `${btnBase} bg-brand text-white hover:opacity-90 disabled:opacity-40`
  const btnSecondary = `${btnBase} border border-border text-text-muted hover:bg-surface-hover disabled:opacity-40`

  return (
    <div className="flex flex-col h-full overflow-hidden" style={{ fontFamily: 'var(--font-sans)' }}>

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)', padding: '12px 16px' }}>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {/* Report type selector */}
          <select
            value={reportType}
            onChange={e => { setReportType(e.target.value); setReport(null); setSections([]) }}
            style={{
              background: 'var(--surface-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: '6px 10px',
              fontSize: 13,
              color: 'var(--text)',
              cursor: 'pointer',
              minWidth: 170,
            }}
          >
            {REPORT_TYPES.map(rt => (
              <option key={rt.key} value={rt.key}>{rt.title}</option>
            ))}
          </select>

          <button
            onClick={() => setShowPatient(v => !v)}
            style={{
              background: showPatient ? 'var(--brand-subtle, #e8f0fe)' : 'var(--surface-elevated)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: '6px 10px',
              fontSize: 13,
              color: 'var(--text-muted)',
              cursor: 'pointer',
            }}
          >
            {showPatient ? '▲ Patientendaten' : '▼ Patientendaten'}
          </button>

          <button
            onClick={handleGenerate}
            disabled={loading}
            className={btnPrimary}
            style={{ marginLeft: 'auto' }}
          >
            {loading ? '⏳ Wird erstellt …' : '✦ Bericht erstellen'}
          </button>

          {report && (
            <>
              <button onClick={handleCopy} disabled={saving} className={btnSecondary}>
                {copied ? '✓ Kopiert' : '⎘ Kopieren'}
              </button>
              <button onClick={handlePDF} disabled={saving} className={btnSecondary}>
                {saving ? '⏳ …' : '↓ PDF'}
              </button>
            </>
          )}
        </div>

        {/* Patient context fields */}
        {showPatient && (
          <div style={{
            marginTop: 10,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
            gap: 8,
          }}>
            {([
              ['name',         'Name'],
              ['geburtsdatum', 'Geburtsdatum'],
              ['aufnahme',     'Aufnahmedatum'],
              ['entlassung',   'Entlassungsdatum'],
              ['station',      'Station / Abteilung'],
              ['zuweiser',     'Zuweiser / An'],
            ] as [keyof PatientContext, string][]).map(([k, label]) => (
              <div key={k}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
                <input
                  type="text"
                  value={patient[k]}
                  onChange={e => setPatient(p => ({ ...p, [k]: e.target.value }))}
                  placeholder={label}
                  style={{
                    width: '100%',
                    background: 'var(--surface-elevated)',
                    border: '1px solid var(--border)',
                    borderRadius: 5,
                    padding: '5px 8px',
                    fontSize: 12,
                    color: 'var(--text)',
                  }}
                />
              </div>
            ))}
          </div>
        )}

        {/* Description */}
        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-muted)' }}>
          {REPORT_TYPES.find(r => r.key === reportType)?.description}
        </div>
      </div>

      {/* ── Content ──────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>

        {error && (
          <div style={{
            background: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: 8, padding: '10px 14px', marginBottom: 16,
            fontSize: 13, color: '#991b1b',
          }}>
            {error}
          </div>
        )}

        {loading && (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', paddingTop: 60, gap: 12, color: 'var(--text-muted)',
          }}>
            <div style={{ fontSize: 28 }}>✦</div>
            <div style={{ fontSize: 14 }}>Bericht wird aus dem Evidenzgraphen erstellt …</div>
            <div style={{ fontSize: 12 }}>Laborwerte, Diagnosen und Scores werden verarbeitet</div>
          </div>
        )}

        {!loading && !report && !error && (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', paddingTop: 60, gap: 10, color: 'var(--text-muted)',
          }}>
            <div style={{ fontSize: 36 }}>📄</div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Kein Bericht geladen</div>
            <div style={{ fontSize: 12 }}>Berichtstyp wählen und „Bericht erstellen" klicken</div>
          </div>
        )}

        {!loading && sections.length > 0 && (
          <>
            {/* Header meta */}
            <div style={{
              marginBottom: 20,
              padding: '12px 16px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 8,
            }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 4 }}>
                {report?.title}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Erstellt: {report ? new Date(report.generated_at).toLocaleString('de-DE') : '—'}
                {patient.name && ` · ${patient.name}`}
                {patient.geburtsdatum && ` · * ${patient.geburtsdatum}`}
              </div>
              <div style={{
                marginTop: 8, padding: '6px 10px',
                background: '#fefce8', border: '1px solid #fde68a',
                borderRadius: 6, fontSize: 11, color: '#92400e',
              }}>
                Dieser Bericht wurde maschinell unterstützt erstellt und ersetzt keine ärztliche Beurteilung.
                Alle Abschnitte können vor dem Speichern bearbeitet werden.
              </div>
            </div>

            {/* Editable sections */}
            {sections.map(s => (
              <div key={s.key} style={{ marginBottom: 16 }}>
                <div style={{
                  fontSize: 12, fontWeight: 700, textTransform: 'uppercase',
                  letterSpacing: '0.05em', color: '#0f3764',
                  marginBottom: 6, paddingBottom: 4,
                  borderBottom: '2px solid #0f3764',
                }}>
                  {s.title}
                </div>
                <textarea
                  value={s.text}
                  onChange={e => updateSection(s.key, e.target.value)}
                  rows={Math.max(3, s.text.split('\n').length + 1)}
                  style={{
                    width: '100%',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 6,
                    padding: '10px 12px',
                    fontSize: 13,
                    lineHeight: 1.6,
                    color: 'var(--text)',
                    resize: 'vertical',
                    fontFamily: 'Georgia, serif',
                  }}
                />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
