'use client'

import { useRef, useState } from 'react'
import { importSession } from '@/lib/api'

interface Props {
  sessionId: string
  onClose:   () => void
  onImported: () => void
}

export default function ImportModal({ sessionId, onClose, onImported }: Props) {
  const [dragging,  setDragging]  = useState(false)
  const [fileName,  setFileName]  = useState('')
  const [preview,   setPreview]   = useState<{ claimCount: number } | null>(null)
  const [claims,    setClaims]    = useState<object[] | null>(null)
  const [importing, setImporting] = useState(false)
  const [result,    setResult]    = useState<{ imported: number; skipped: number } | null>(null)
  const [error,     setError]     = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  const parseFile = (file: File) => {
    if (!file.name.endsWith('.json')) { setError('Only .json files are supported'); return }
    setError('')
    const reader = new FileReader()
    reader.onload = e => {
      try {
        const data = JSON.parse(e.target!.result as string)
        const claimList: object[] = data.claims ?? (Array.isArray(data) ? data : null)
        if (!claimList) throw new Error('Expected JSON with a "claims" array')
        setClaims(claimList)
        setPreview({ claimCount: claimList.length })
        setFileName(file.name)
      } catch (err: any) {
        setError(err.message)
      }
    }
    reader.readAsText(file)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) parseFile(file)
  }

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) parseFile(file)
  }

  const handleImport = async () => {
    if (!claims) return
    setImporting(true)
    setError('')
    try {
      const res = await importSession(sessionId, claims)
      setResult(res)
      onImported()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.35)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}>

      <div className="w-full max-w-md rounded-2xl shadow-xl overflow-hidden"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}>

        <div className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--border)' }}>
          <div>
            <h2 className="font-semibold text-sm">Import Session</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              Load claims from a previously exported JSON snapshot
            </p>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        <div className="p-5 space-y-4">
          {!result ? (
            <>
              {/* Drop zone */}
              <div
                className="rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors"
                style={{
                  borderColor: dragging ? 'var(--brand)' : 'var(--border)',
                  background:  dragging ? 'var(--brand-pale)' : 'var(--surface-2)',
                }}
                onDragOver={e => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}>
                <input ref={fileRef} type="file" accept=".json" className="hidden"
                  onChange={handleFile} />
                <p className="text-2xl mb-2 opacity-30">↑</p>
                <p className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                  {fileName || 'Drop a JSON file or click to browse'}
                </p>
                <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                  Accepts AleXiona export snapshots (.json)
                </p>
              </div>

              {/* Preview */}
              {preview && (
                <div className="rounded-lg px-4 py-3 text-sm"
                  style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                  <span className="font-medium">{preview.claimCount}</span> claim
                  {preview.claimCount !== 1 ? 's' : ''} ready to import into current session.
                  <span className="text-xs ml-2" style={{ color: 'var(--text-muted)' }}>
                    New IDs will be assigned.
                  </span>
                </div>
              )}

              {error && (
                <p className="text-xs rounded-lg px-3 py-2"
                  style={{ background: '#fef2f2', color: '#ef4444' }}>{error}</p>
              )}
            </>
          ) : (
            <div className="text-center py-4">
              <div className="text-3xl mb-2">✓</div>
              <p className="font-medium text-sm">
                Imported {result.imported} claim{result.imported !== 1 ? 's' : ''}
              </p>
              {result.skipped > 0 && (
                <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                  {result.skipped} record{result.skipped !== 1 ? 's' : ''} skipped (malformed)
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex gap-2 px-5 pb-5">
          {!result ? (
            <>
              <button onClick={handleImport} disabled={!claims || importing}
                className="flex-1 py-2 rounded-xl text-sm font-semibold disabled:opacity-50"
                style={{ background: 'var(--brand)', color: 'white' }}>
                {importing ? 'Importing…' : 'Import'}
              </button>
              <button onClick={onClose}
                className="py-2 px-4 rounded-xl text-sm"
                style={{ background: 'var(--surface-2)', color: 'var(--text-muted)' }}>
                Cancel
              </button>
            </>
          ) : (
            <button onClick={onClose} className="flex-1 py-2 rounded-xl text-sm font-semibold"
              style={{ background: 'var(--brand)', color: 'white' }}>
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
