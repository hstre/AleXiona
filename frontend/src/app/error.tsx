'use client'

import { useEffect } from 'react'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    try {
      localStorage.setItem('_alexiona_last_error', JSON.stringify({
        message: error?.message ?? 'unknown',
        stack:   error?.stack?.slice(0, 800) ?? '',
        digest:  error?.digest ?? '',
        time:    new Date().toISOString(),
      }))
    } catch {}
  }, [error])

  const clearSession = () => {
    try { localStorage.removeItem('alexiona_session') } catch {}
    window.location.reload()
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', minHeight: '100vh', padding: 24, gap: 16,
      fontFamily: 'system-ui, sans-serif', background: '#f8fafc',
    }}>
      <div style={{ fontSize: 32 }}>⚠</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: '#111' }}>
        AleXiona – Laufzeitfehler
      </div>
      <div style={{
        background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8,
        padding: '12px 16px', color: '#991b1b', fontSize: 13,
        maxWidth: 500, width: '100%', wordBreak: 'break-word',
      }}>
        <div><strong>Fehler:</strong> {error?.message || 'Unbekannt'}</div>
        {error?.stack && (
          <pre style={{ fontSize: 10, marginTop: 8, whiteSpace: 'pre-wrap', opacity: 0.7 }}>
            {error.stack.slice(0, 600)}
          </pre>
        )}
        {error?.digest && (
          <div style={{ marginTop: 4, fontSize: 11, opacity: 0.6 }}>digest: {error.digest}</div>
        )}
      </div>
      <div style={{ fontSize: 12, color: '#6b7280', textAlign: 'center', maxWidth: 360 }}>
        Bitte mache einen Screenshot dieser Seite.
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
        <button onClick={reset} style={{
          padding: '8px 18px', borderRadius: 8, border: 'none', cursor: 'pointer',
          background: '#2563eb', color: '#fff', fontSize: 14, fontWeight: 600,
        }}>
          Erneut versuchen
        </button>
        <button onClick={clearSession} style={{
          padding: '8px 18px', borderRadius: 8, border: '1px solid #d1d5db',
          cursor: 'pointer', background: '#fff', color: '#374151', fontSize: 14,
        }}>
          Neue Session starten
        </button>
      </div>
    </div>
  )
}
