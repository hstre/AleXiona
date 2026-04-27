'use client'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  const clearSession = () => {
    try { localStorage.removeItem('alexiona_session') } catch {}
    window.location.reload()
  }

  return (
    <html lang="de">
      <body style={{ margin: 0, fontFamily: 'system-ui, sans-serif', background: '#f8fafc' }}>
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '100vh', padding: 24, gap: 16,
        }}>
          <div style={{ fontSize: 32, marginBottom: 4 }}>⚠</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#111' }}>
            AleXiona konnte nicht geladen werden
          </div>
          <div style={{
            background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8,
            padding: '12px 16px', color: '#991b1b', fontSize: 13,
            maxWidth: 480, width: '100%', wordBreak: 'break-word',
          }}>
            <strong>Fehler:</strong> {error?.message || 'Unbekannter Fehler'}
            {error?.digest && (
              <div style={{ marginTop: 4, fontSize: 11, opacity: 0.7 }}>
                digest: {error.digest}
              </div>
            )}
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
          <div style={{ fontSize: 11, color: '#9ca3af', textAlign: 'center', maxWidth: 360 }}>
            Bitte mache einen Screenshot dieser Seite um den Fehler zu melden.
          </div>
        </div>
      </body>
    </html>
  )
}
