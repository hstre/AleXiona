'use client'

import { useState } from 'react'
import type { ClaimType, SourceType, ClaimTrend, ClaimStatus, ManualClaim } from '@/lib/api'
import { addManualClaim } from '@/lib/api'
import { getTypeMeta, CLAIM_TYPE_META } from '@/lib/utils'

interface Props {
  sessionId: string
  onClose:   () => void
  onCreated: () => void
}

const CLAIM_TYPES = Object.keys(CLAIM_TYPE_META) as ClaimType[]

export default function AddNodeModal({ sessionId, onClose, onCreated }: Props) {
  const [text,   setText]   = useState('')
  const [type,   setType]   = useState<ClaimType>('finding')
  const [source, setSource] = useState<SourceType>('clinician')
  const [ref,    setRef]    = useState('')
  const [offset, setOffset] = useState('')
  const [trend,  setTrend]  = useState<ClaimTrend>('unknown')
  const [score,  setScore]  = useState(0.8)
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState('')

  const handleSubmit = async () => {
    if (!text.trim()) { setError('Text is required'); return }
    setSaving(true)
    setError('')
    try {
      const claim: ManualClaim = {
        text: text.trim(),
        claim_type:             type,
        source_type:            source,
        source_ref:             ref.trim(),
        evidence_support_score: score,
        time_offset:            offset.trim() || '',
        trend,
        status:                 'active',
      }
      await addManualClaim(sessionId, claim)
      onCreated()
      onClose()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const meta = getTypeMeta(type)

  const labelCls = "block text-xs font-medium mb-1"
  const inputCls = "w-full rounded-lg px-3 py-2 text-sm outline-none border transition-colors"
  const inputStyle = { background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text)' }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.35)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>

      <div className="w-full max-w-md rounded-2xl shadow-xl overflow-hidden"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--border)' }}>
          <div>
            <h2 className="font-semibold">Add Evidence Node</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              Manually enter a claim or finding
            </p>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Claim type selector */}
          <div>
            <label className={labelCls} style={{ color: 'var(--text-muted)' }}>Claim Type</label>
            <div className="flex flex-wrap gap-1.5">
              {CLAIM_TYPES.map(t => {
                const m = getTypeMeta(t)
                return (
                  <button key={t} onClick={() => setType(t)}
                    className="text-xs px-2 py-1 rounded-lg font-medium transition-all"
                    style={{
                      background: type === t ? m.bg : 'var(--surface-2)',
                      color:      type === t ? m.text : 'var(--text-muted)',
                      border:     `1px solid ${type === t ? m.border : 'transparent'}`,
                    }}>
                    {m.icon} {m.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Text */}
          <div>
            <label className={labelCls} style={{ color: 'var(--text-muted)' }}>Claim Text *</label>
            <textarea
              className={inputCls} style={inputStyle}
              placeholder={`Describe the ${meta.label.toLowerCase()}…`}
              value={text} onChange={e => setText(e.target.value)}
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            {/* Source type */}
            <div>
              <label className={labelCls} style={{ color: 'var(--text-muted)' }}>Source</label>
              <select className={inputCls} style={inputStyle}
                value={source} onChange={e => setSource(e.target.value as SourceType)}>
                {(['clinician','llm','guideline','imaging_model','lab_system','imported_document'] as SourceType[])
                  .map(s => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
              </select>
            </div>

            {/* Source ref */}
            <div>
              <label className={labelCls} style={{ color: 'var(--text-muted)' }}>Source ref</label>
              <input type="text" className={inputCls} style={inputStyle}
                placeholder="e.g. CT-20250319" value={ref} onChange={e => setRef(e.target.value)} />
            </div>

            {/* Time offset */}
            <div>
              <label className={labelCls} style={{ color: 'var(--text-muted)' }}>Time offset</label>
              <input type="text" className={inputCls} style={inputStyle}
                placeholder="e.g. t+6h" value={offset} onChange={e => setOffset(e.target.value)} />
            </div>

            {/* Trend */}
            <div>
              <label className={labelCls} style={{ color: 'var(--text-muted)' }}>Trend</label>
              <select className={inputCls} style={inputStyle}
                value={trend} onChange={e => setTrend(e.target.value as ClaimTrend)}>
                {(['improving','worsening','stable','unknown'] as ClaimTrend[])
                  .map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
          </div>

          {/* Evidence support score */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className={labelCls} style={{ color: 'var(--text-muted)', marginBottom: 0 }}>
                Evidence Support Score
              </label>
              <span className="text-xs font-bold"
                style={{ color: score >= 0.75 ? '#22c55e' : score >= 0.5 ? '#f59e0b' : '#ef4444' }}>
                {Math.round(score * 100)}%
              </span>
            </div>
            <input type="range" min="0" max="1" step="0.05"
              className="w-full" value={score}
              onChange={e => setScore(parseFloat(e.target.value))} />
          </div>

          {error && (
            <p className="text-xs rounded-lg px-3 py-2"
              style={{ background: '#fef2f2', color: '#ef4444' }}>{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-5 pb-5">
          <button onClick={handleSubmit} disabled={saving || !text.trim()}
            className="flex-1 py-2 rounded-xl text-sm font-semibold disabled:opacity-50"
            style={{ background: 'var(--brand)', color: 'white' }}>
            {saving ? 'Adding…' : 'Add Node'}
          </button>
          <button onClick={onClose}
            className="py-2 px-4 rounded-xl text-sm"
            style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
