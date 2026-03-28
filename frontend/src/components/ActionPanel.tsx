'use client'

/**
 * ActionPanel — clinical action / management tracker.
 *
 * Displays all Claims with claim_type='action' in a kanban board
 * grouped by lifecycle status:
 *
 *   active    → Empfohlen   (recommended, not yet ordered)
 *   inferred  → Beauftragt  (ordered / in progress)
 *   confirmed → Abgeschlossen (completed / resulted)
 *   refuted / withdrawn → Storniert (cancelled / not appropriate)
 *
 * Status transitions are persisted via PATCH /api/graph/claim/{id}.
 */

import { useState, useCallback } from 'react'
import { patchClaim } from '@/lib/api'
import type { Claim, ClaimStatus } from '@/lib/api'

// ── Column definitions ─────────────────────────────────────────────────────────

interface Column {
  id:      string
  label:   string
  icon:    string
  statuses: ClaimStatus[]
  color:   string
  bg:      string
  border:  string
}

const COLUMNS: Column[] = [
  {
    id:       'recommended',
    label:    'Empfohlen',
    icon:     '💡',
    statuses: ['active', 'observed', 'tentative'],
    color:    '#f59e0b',
    bg:       '#fffbeb',
    border:   '#fde68a',
  },
  {
    id:       'ordered',
    label:    'Beauftragt',
    icon:     '⏳',
    statuses: ['inferred', 'contested'],
    color:    '#3b8eea',
    bg:       '#eff6ff',
    border:   '#bfdbfe',
  },
  {
    id:       'done',
    label:    'Abgeschlossen',
    icon:     '✅',
    statuses: ['confirmed', 'resolved'],
    color:    '#10b981',
    bg:       '#f0fdf4',
    border:   '#a7f3d0',
  },
  {
    id:       'cancelled',
    label:    'Storniert',
    icon:     '🚫',
    statuses: ['refuted', 'withdrawn', 'superseded'],
    color:    '#9ca3af',
    bg:       '#f9fafb',
    border:   '#e5e7eb',
  },
]

// Map any status → which column it belongs to
const STATUS_TO_COLUMN: Partial<Record<ClaimStatus, string>> = {}
for (const col of COLUMNS) {
  for (const s of col.statuses) {
    STATUS_TO_COLUMN[s] = col.id
  }
}

// The primary status to assign when dropping onto a column
const COLUMN_TARGET_STATUS: Record<string, ClaimStatus> = {
  recommended: 'active',
  ordered:     'inferred',
  done:        'confirmed',
  cancelled:   'withdrawn',
}

// ── Source-type badge ──────────────────────────────────────────────────────────

const SOURCE_LABEL: Record<string, string> = {
  clinician:        'Arzt',
  llm:              'KI',
  guideline:        'Leitlinie',
  imaging_model:    'Bildgebung',
  lab_system:       'Labor',
  imported_document:'Import',
  patient_report:   'Patient',
}

// ── Subcomponents ─────────────────────────────────────────────────────────────

interface ActionCardProps {
  claim:      Claim
  onMove:     (claimId: string, newStatus: ClaimStatus) => void
  moving:     boolean
}

function ActionCard({ claim, onMove, moving }: ActionCardProps) {
  const [expanded, setExpanded] = useState(false)

  const handleMove = useCallback((e: React.MouseEvent<HTMLButtonElement>) => {
    const target = e.currentTarget.dataset.target as ClaimStatus
    if (claim.claimId && target) onMove(claim.claimId, target)
  }, [claim.claimId, onMove])

  const srcLabel = SOURCE_LABEL[claim.source_type] ?? claim.source_type
  const essPct   = Math.round((claim.evidence_support_score ?? 0.8) * 100)
  const col      = COLUMNS.find(c => c.statuses.includes(claim.status as ClaimStatus))

  // Possible next-status buttons (other columns)
  const moveTargets = COLUMNS.filter(c => c.id !== (STATUS_TO_COLUMN[claim.status as ClaimStatus] ?? ''))

  return (
    <div
      style={{
        background: '#fff',
        border:     '1px solid var(--border)',
        borderLeft: `3px solid ${col?.color ?? '#6b7280'}`,
        borderRadius: 8,
        marginBottom: 8,
        opacity: moving ? 0.6 : 1,
        transition: 'opacity 0.15s',
      }}
    >
      {/* Header */}
      <div
        className="flex items-start gap-2 cursor-pointer px-3 pt-3 pb-2"
        onClick={() => setExpanded(v => !v)}
        role="button"
        tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && setExpanded(v => !v)}
      >
        <span style={{ fontSize: 14, marginTop: 1, flex: '0 0 auto' }}>
          {col?.icon ?? '•'}
        </span>
        <span style={{ flex: 1, fontSize: 13, fontWeight: 500, color: 'var(--text)', lineHeight: 1.4 }}>
          {claim.text}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 4 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Meta row */}
      <div className="flex items-center gap-1.5 px-3 pb-2 flex-wrap">
        <span style={{
          fontSize: 10, padding: '1px 6px', borderRadius: 10,
          background: '#f1f5f9', color: '#475569',
        }}>
          {srcLabel}
        </span>
        {claim.time_offset && (
          <span style={{
            fontSize: 10, padding: '1px 6px', borderRadius: 10,
            background: '#f1f5f9', color: '#475569',
          }}>
            {claim.time_offset}
          </span>
        )}
        <span style={{
          fontSize: 10, padding: '1px 6px', borderRadius: 10,
          background: essPct >= 75 ? '#f0fdf4' : essPct >= 50 ? '#fffbeb' : '#fef2f2',
          color:      essPct >= 75 ? '#14532d' : essPct >= 50 ? '#78350f' : '#7f1d1d',
        }}>
          ESS {essPct}%
        </span>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div style={{ padding: '0 12px 12px', borderTop: '1px solid var(--border)' }}>
          {claim.notes && (
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, marginBottom: 6 }}>
              {claim.notes}
            </p>
          )}

          {/* Move-to buttons */}
          <div className="flex flex-wrap gap-1.5 mt-2">
            {moveTargets.map(col => (
              <button
                key={col.id}
                data-target={COLUMN_TARGET_STATUS[col.id]}
                onClick={handleMove}
                disabled={moving}
                style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 10,
                  background: col.bg, color: col.color,
                  border: `1px solid ${col.border}`,
                  cursor: moving ? 'not-allowed' : 'pointer',
                }}
              >
                → {col.icon} {col.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface ActionPanelProps {
  claims:     Claim[]
  onRefresh:  () => void
}

export default function ActionPanel({ claims, onRefresh }: ActionPanelProps) {
  const [moving, setMoving] = useState<string | null>(null)
  const [error,  setError]  = useState<string | null>(null)

  const actionClaims = claims.filter(c => c.claim_type === 'action')

  const handleMove = useCallback(async (claimId: string, newStatus: ClaimStatus) => {
    setMoving(claimId)
    setError(null)
    try {
      await patchClaim(claimId, { status: newStatus })
      onRefresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Status-Update fehlgeschlagen')
    } finally {
      setMoving(null)
    }
  }, [onRefresh])

  if (actionClaims.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center flex-col gap-3"
        style={{ color: 'var(--text-muted)', padding: 40 }}>
        <span style={{ fontSize: 36 }}>✅</span>
        <p style={{ fontSize: 14, textAlign: 'center', maxWidth: 280 }}>
          Noch keine Maßnahmen dokumentiert.<br />
          Füge einen Claim mit Typ <strong>Action</strong> hinzu,
          um ihn hier zu verwalten.
        </p>
      </div>
    )
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '12px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div>
          <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>
            Maßnahmen-Tracker
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
            {actionClaims.length} Maßnahme{actionClaims.length !== 1 ? 'n' : ''}
          </span>
        </div>
        <button
          onClick={onRefresh}
          style={{
            fontSize: 11, padding: '4px 10px', borderRadius: 6,
            background: 'var(--surface)', border: '1px solid var(--border)',
            color: 'var(--text-muted)', cursor: 'pointer',
          }}
        >
          ↺ Aktualisieren
        </button>
      </div>

      {error && (
        <div style={{
          background: '#fef2f2', color: '#7f1d1d', fontSize: 12,
          padding: '8px 16px', borderBottom: '1px solid #fecaca',
        }}>
          {error}
        </div>
      )}

      {/* Kanban columns */}
      <div style={{
        flex: 1, display: 'grid',
        gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 0,
        overflow: 'hidden',
      }}>
        {COLUMNS.map((col, idx) => {
          const cards = actionClaims.filter(
            c => STATUS_TO_COLUMN[c.status as ClaimStatus] === col.id
          )
          return (
            <div key={col.id} style={{
              display: 'flex', flexDirection: 'column', overflow: 'hidden',
              borderRight: idx < COLUMNS.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              {/* Column header */}
              <div style={{
                padding: '10px 12px 8px',
                borderBottom: `2px solid ${col.color}`,
                background: col.bg,
                flexShrink: 0,
              }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: col.color }}>
                  {col.icon} {col.label}
                </span>
                <span style={{
                  marginLeft: 6, fontSize: 11,
                  background: col.border, color: col.color,
                  borderRadius: 10, padding: '1px 6px',
                }}>
                  {cards.length}
                </span>
              </div>

              {/* Cards */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '10px 10px 0' }}>
                {cards.length === 0 ? (
                  <div style={{
                    fontSize: 11, color: 'var(--text-muted)',
                    textAlign: 'center', padding: '16px 8px',
                    border: '1px dashed var(--border)', borderRadius: 6,
                  }}>
                    Leer
                  </div>
                ) : (
                  cards.map(c => (
                    <ActionCard
                      key={c.claimId}
                      claim={c}
                      onMove={handleMove}
                      moving={moving === c.claimId}
                    />
                  ))
                )}
                <div style={{ height: 10 }} />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
