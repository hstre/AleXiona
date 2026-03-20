/**
 * Pure unit tests for the DataPanel claim-filter logic.
 * The predicate is reproduced here so tests remain fast and dependency-free.
 */
import { describe, it, expect } from 'vitest'
import type { Claim } from '@/lib/api'


// ── Inline the exact filter predicate from DataPanel ─────────────────────────

function matchesQuery(c: Claim, searchQuery: string): boolean {
  if (!searchQuery) return true
  const q = searchQuery.toLowerCase()
  return (
    c.text.toLowerCase().includes(q) ||
    c.claim_type.toLowerCase().includes(q) ||
    c.status.toLowerCase().includes(q) ||
    (c.source_ref ?? '').toLowerCase().includes(q) ||
    (c.source_type ?? '').toLowerCase().includes(q) ||
    (c.trend ?? '').toLowerCase().includes(q) ||
    (c.time_offset ?? '').toLowerCase().includes(q) ||
    (c.notes ?? '').toLowerCase().includes(q)
  )
}

function makeClaim(overrides: Partial<Claim> = {}): Claim {
  return {
    text:                   'Elevated troponin levels observed at admission',
    entities:               [],
    relations:              [],
    evidence_support_score: 0.8,
    claim_type:             'lab',
    source_type:            'lab_system',
    source_ref:             'LAB-001',
    derived_from:           [],
    status:                 'active',
    time_offset:            't+2h',
    trend:                  'worsening',
    notes:                  '',
    ...overrides,
  }
}


// ── Empty query ───────────────────────────────────────────────────────────────

describe('matchesQuery — empty query', () => {
  it('returns true for empty string', () => {
    expect(matchesQuery(makeClaim(), '')).toBe(true)
  })
})


// ── Text field ────────────────────────────────────────────────────────────────

describe('matchesQuery — text field', () => {
  it('matches substring in text (case-insensitive)', () => {
    expect(matchesQuery(makeClaim(), 'troponin')).toBe(true)
    expect(matchesQuery(makeClaim(), 'TROPONIN')).toBe(true)
  })

  it('does not match absent substring', () => {
    expect(matchesQuery(makeClaim(), 'aspirin')).toBe(false)
  })

  it('matches partial word in text', () => {
    expect(matchesQuery(makeClaim(), 'tropo')).toBe(true)
  })
})


// ── claim_type field ─────────────────────────────────────────────────────────

describe('matchesQuery — claim_type field', () => {
  it('matches claim type "lab"', () => {
    expect(matchesQuery(makeClaim({ claim_type: 'lab' }), 'lab')).toBe(true)
  })

  it('matches claim type "diagnosis"', () => {
    expect(matchesQuery(makeClaim({ claim_type: 'diagnosis' }), 'diagnosis')).toBe(true)
  })

  it('matches partial claim type "diag"', () => {
    expect(matchesQuery(makeClaim({ claim_type: 'diagnosis' }), 'diag')).toBe(true)
  })
})


// ── status field ──────────────────────────────────────────────────────────────

describe('matchesQuery — status field', () => {
  it('matches "active"', () => {
    expect(matchesQuery(makeClaim({ status: 'active' }), 'active')).toBe(true)
  })

  it('matches "resolved"', () => {
    expect(matchesQuery(makeClaim({ status: 'resolved' }), 'resolved')).toBe(true)
  })

  it('matches "superseded"', () => {
    expect(matchesQuery(makeClaim({ status: 'superseded' }), 'superseded')).toBe(true)
  })
})


// ── source_ref field ──────────────────────────────────────────────────────────

describe('matchesQuery — source_ref field', () => {
  it('matches source_ref', () => {
    expect(matchesQuery(makeClaim({ source_ref: 'CT-20250319' }), 'CT-20250319')).toBe(true)
  })

  it('matches partial source_ref case-insensitive', () => {
    expect(matchesQuery(makeClaim({ source_ref: 'CT-20250319' }), 'ct-2025')).toBe(true)
  })

  it('handles empty source_ref without throwing', () => {
    expect(matchesQuery(makeClaim({ source_ref: '' }), 'lab')).toBe(true) // matches claim_type
  })
})


// ── trend field ───────────────────────────────────────────────────────────────

describe('matchesQuery — trend field', () => {
  it('matches trend "worsening"', () => {
    expect(matchesQuery(makeClaim({ trend: 'worsening' }), 'worsening')).toBe(true)
  })

  it('matches trend "improving"', () => {
    expect(matchesQuery(makeClaim({ trend: 'improving' }), 'improving')).toBe(true)
  })
})


// ── time_offset field ─────────────────────────────────────────────────────────

describe('matchesQuery — time_offset field', () => {
  it('matches time_offset "t+2h"', () => {
    expect(matchesQuery(makeClaim({ time_offset: 't+2h' }), 't+2h')).toBe(true)
  })

  it('matches partial time_offset "t+"', () => {
    expect(matchesQuery(makeClaim({ time_offset: 't+6h' }), 't+')).toBe(true)
  })

  it('handles null time_offset without throwing', () => {
    expect(matchesQuery(makeClaim({ time_offset: null }), 'active')).toBe(true) // matches status
  })
})


// ── notes field ──────────────────────────────────────────────────────────────

describe('matchesQuery — notes field', () => {
  it('matches note text', () => {
    expect(matchesQuery(makeClaim({ notes: 'Follow-up echo scheduled' }), 'echo')).toBe(true)
  })

  it('matches notes case-insensitive', () => {
    expect(matchesQuery(makeClaim({ notes: 'Echo scheduled' }), 'ECHO')).toBe(true)
  })

  it('empty notes does not match arbitrary query by itself', () => {
    const claim = makeClaim({ notes: '', text: 'troponin' })
    expect(matchesQuery(claim, 'echo')).toBe(false)
  })

  it('undefined notes is handled gracefully', () => {
    const claim = makeClaim({ notes: undefined })
    expect(() => matchesQuery(claim, 'echo')).not.toThrow()
  })
})


// ── Multi-field fallthrough ───────────────────────────────────────────────────

describe('matchesQuery — multi-field', () => {
  it('returns true when only notes match (text does not)', () => {
    const claim = makeClaim({ text: 'BP 120/80', notes: 'history of hypertension' })
    expect(matchesQuery(claim, 'hypertension')).toBe(true)
  })

  it('returns false when no field matches', () => {
    const claim = makeClaim({ text: 'BP 120/80', notes: '', source_ref: 'EXAM-01' })
    expect(matchesQuery(claim, 'zzznomatch')).toBe(false)
  })
})
