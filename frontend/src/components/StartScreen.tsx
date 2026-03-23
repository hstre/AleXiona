'use client'

import { useState } from 'react'

// ── Logo SVG ──────────────────────────────────────────────────────────────────
function LogoIcon({ size = 96 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <linearGradient id="lg1" x1="10" y1="10" x2="90" y2="90" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#00c8e0" />
          <stop offset="100%" stopColor="#1a7ab3" />
        </linearGradient>
        <linearGradient id="lg2" x1="20" y1="80" x2="80" y2="20" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0e8a8a" />
          <stop offset="100%" stopColor="#2d9fd8" />
        </linearGradient>
      </defs>
      {/* Curved arms */}
      <path d="M18 18 Q50 32 82 18" stroke="url(#lg1)" strokeWidth="4.5" strokeLinecap="round" fill="none" />
      <path d="M18 82 Q50 68 82 82" stroke="url(#lg2)" strokeWidth="4.5" strokeLinecap="round" fill="none" />
      <path d="M18 18 Q32 50 18 82" stroke="url(#lg1)" strokeWidth="4.5" strokeLinecap="round" fill="none" />
      <path d="M82 18 Q68 50 82 82" stroke="url(#lg2)" strokeWidth="4.5" strokeLinecap="round" fill="none" />
      {/* Arrow top-right */}
      <path d="M66 14 L84 14 L84 32" stroke="url(#lg1)" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M84 14 L58 40" stroke="url(#lg1)" strokeWidth="4" strokeLinecap="round" fill="none" />
      {/* Corner dots */}
      <circle cx="18" cy="18" r="5" fill="url(#lg1)" />
      <circle cx="18" cy="82" r="5" fill="url(#lg2)" />
      <circle cx="82" cy="82" r="5" fill="url(#lg2)" />
      {/* Centre cross */}
      <rect x="44" y="37" width="12" height="26" rx="3" fill="url(#lg1)" />
      <rect x="37" y="44" width="26" height="12" rx="3" fill="url(#lg1)" />
    </svg>
  )
}

// ── Scenario cards ────────────────────────────────────────────────────────────
const SCENARIOS = [
  { id: 'cap',    label: 'CAP',    long: 'Community-Acquired Pneumonia',  icon: '🫁' },
  { id: 'pe',     label: 'PE',     long: 'Pulmonary Embolism',            icon: '🫀' },
  { id: 'ards',   label: 'ARDS',   long: 'ARDS + Sepsis',                 icon: '💉' },
  { id: 'nstemi', label: 'NSTEMI', long: 'Non-ST Elevation MI',           icon: '📈' },
] as const

export type StartMode =
  | { kind: 'new' }
  | { kind: 'resume'; sessionId: string }
  | { kind: 'demo'; scenario: typeof SCENARIOS[number]['id']; lang: 'en' | 'de' }

interface Props {
  existingSessionId: string | null
  onStart: (mode: StartMode) => void
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export default function StartScreen({ existingSessionId, onStart }: Props) {
  const [scenario, setScenario] = useState<typeof SCENARIOS[number]['id']>('cap')
  const [lang,     setLang]     = useState<'en' | 'de'>('de')

  // Only show "resume" if the stored value is a valid UUID — prevents showing
  // the button when localStorage contains corrupted or spoofed data.
  const resumableId = existingSessionId && UUID_RE.test(existingSessionId)
    ? existingSessionId
    : null

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12 relative overflow-hidden"
      style={{ background: 'linear-gradient(145deg, #e8f4fc 0%, #eef2f7 50%, #e4f0f4 100%)' }}>

      {/* Subtle background blobs */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', top: '-8rem', right: '-8rem',
          width: '32rem', height: '32rem', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(26,122,179,0.08) 0%, transparent 70%)',
        }} />
        <div style={{
          position: 'absolute', bottom: '-6rem', left: '-6rem',
          width: '28rem', height: '28rem', borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(14,138,138,0.07) 0%, transparent 70%)',
        }} />
      </div>

      {/* Logo + wordmark */}
      <div className="flex flex-col items-center mb-10 relative">
        <LogoIcon size={88} />
        <h1 style={{
          fontSize: '3rem', fontWeight: 800, letterSpacing: '-0.03em',
          marginTop: '0.75rem', marginBottom: 0,
          background: 'linear-gradient(135deg, #1a2b3c 0%, #1a7ab3 60%, #0e8a8a 100%)',
          WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
        }}>
          AleXiona
        </h1>
        <p style={{ color: '#6b7fa3', fontSize: '1rem', fontWeight: 500, marginTop: '0.25rem', letterSpacing: '0.01em' }}>
          AI Clinical Evidence Graph
        </p>
      </div>

      {/* Card */}
      <div style={{
        background: '#fff', borderRadius: '1.25rem', padding: '2rem 2.25rem',
        boxShadow: '0 4px 32px rgba(26,122,179,0.10), 0 1px 4px rgba(0,0,0,0.06)',
        width: '100%', maxWidth: '420px',
      }}>

        {/* ── Resume ── */}
        {resumableId && (
          <>
            <button
              onClick={() => onStart({ kind: 'resume', sessionId: resumableId! })}
              style={{
                width: '100%', padding: '0.9rem 1.25rem',
                background: 'linear-gradient(135deg, #1a7ab3, #0e8a8a)',
                color: '#fff', border: 'none', borderRadius: '0.75rem',
                fontSize: '0.95rem', fontWeight: 700, cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                boxShadow: '0 3px 12px rgba(26,122,179,0.30)',
              }}>
              <span>▶</span>
              <span>Sitzung fortsetzen</span>
              <span style={{ opacity: 0.65, fontWeight: 400, fontSize: '0.8rem' }}>
                #{resumableId!.slice(0, 8)}
              </span>
            </button>
            <div style={{ textAlign: 'center', margin: '1rem 0 0.75rem', color: '#9aaac4', fontSize: '0.8rem' }}>
              — oder —
            </div>
          </>
        )}

        {/* ── New session ── */}
        {!resumableId && (
          <button
            onClick={() => onStart({ kind: 'new' })}
            style={{
              width: '100%', padding: '0.9rem 1.25rem', marginBottom: '1.25rem',
              background: 'linear-gradient(135deg, #1a7ab3, #0e8a8a)',
              color: '#fff', border: 'none', borderRadius: '0.75rem',
              fontSize: '0.95rem', fontWeight: 700, cursor: 'pointer',
              boxShadow: '0 3px 12px rgba(26,122,179,0.30)',
            }}>
            Neue Sitzung starten
          </button>
        )}

        {/* ── Demo ── */}
        <div style={{
          background: '#f4f7fb', borderRadius: '0.875rem', padding: '1.1rem 1.1rem 1rem',
        }}>
          <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#6b7fa3', letterSpacing: '0.06em', marginBottom: '0.65rem' }}>
            DEMO-SZENARIO
          </div>

          {/* Scenario pills */}
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginBottom: '0.85rem' }}>
            {SCENARIOS.map(s => (
              <button key={s.id} onClick={() => setScenario(s.id)}
                title={s.long}
                style={{
                  padding: '0.3rem 0.7rem', borderRadius: '99px', fontSize: '0.8rem',
                  fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
                  border: scenario === s.id ? '2px solid #1a7ab3' : '2px solid transparent',
                  background: scenario === s.id ? '#e8f4fc' : '#ececec',
                  color: scenario === s.id ? '#1a7ab3' : '#6b7fa3',
                }}>
                {s.icon} {s.label}
              </button>
            ))}
          </div>

          {/* Scenario description */}
          <p style={{ fontSize: '0.78rem', color: '#6b7fa3', margin: '0 0 0.85rem', minHeight: '1.2em' }}>
            {SCENARIOS.find(s => s.id === scenario)?.long}
          </p>

          {/* Language toggle + Start */}
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <div style={{ display: 'flex', borderRadius: '0.5rem', overflow: 'hidden', border: '1px solid #dde3ed' }}>
              {(['de', 'en'] as const).map(l => (
                <button key={l} onClick={() => setLang(l)}
                  style={{
                    padding: '0.3rem 0.65rem', fontSize: '0.78rem', fontWeight: 600,
                    cursor: 'pointer', border: 'none',
                    background: lang === l ? '#1a7ab3' : '#fff',
                    color: lang === l ? '#fff' : '#6b7fa3',
                    transition: 'all 0.15s',
                  }}>
                  {l.toUpperCase()}
                </button>
              ))}
            </div>

            <button
              onClick={() => onStart({ kind: 'demo', scenario, lang })}
              style={{
                flex: 1, padding: '0.45rem 1rem',
                background: '#1a2b3c', color: '#fff',
                border: 'none', borderRadius: '0.5rem',
                fontSize: '0.85rem', fontWeight: 600, cursor: 'pointer',
              }}>
              Demo laden
            </button>
          </div>
        </div>

        {/* ── New session link (when resume is shown) ── */}
        {resumableId && (
          <button
            onClick={() => onStart({ kind: 'new' })}
            style={{
              width: '100%', marginTop: '1rem', padding: '0.6rem',
              background: 'none', border: 'none', cursor: 'pointer',
              color: '#9aaac4', fontSize: '0.8rem',
            }}>
            + Neue leere Sitzung starten
          </button>
        )}
      </div>

      <p style={{ marginTop: '2rem', color: '#c0cad8', fontSize: '0.75rem' }}>
        v0.1 · klinisches Forschungssystem
      </p>
    </div>
  )
}
