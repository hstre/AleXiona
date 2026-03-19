import { describe, it, expect } from 'vitest'
import {
  shortId, confColor, confPct,
  getTypeMeta, CLAIM_TYPE_META,
  STATUS_META, TREND_META, CONFLICT_SEVERITY_META,
  SESSION_KEY,
} from '../utils'
import type { ClaimType, ClaimStatus, ClaimTrend, ConflictSeverity } from '../api'


// ── shortId ───────────────────────────────────────────────────────────────────

describe('shortId', () => {
  it('returns first 8 characters', () => {
    expect(shortId('abcdefghijklmnop')).toBe('abcdefgh')
  })

  it('returns full string if shorter than 8', () => {
    expect(shortId('abc')).toBe('abc')
  })

  it('handles empty string', () => {
    expect(shortId('')).toBe('')
  })

  it('handles exactly 8 characters', () => {
    expect(shortId('12345678')).toBe('12345678')
  })
})


// ── confColor ─────────────────────────────────────────────────────────────────

describe('confColor', () => {
  it('returns green for >= 0.75', () => {
    expect(confColor(0.75)).toBe('#22c55e')
    expect(confColor(1.0)).toBe('#22c55e')
    expect(confColor(0.8)).toBe('#22c55e')
  })

  it('returns amber for >= 0.5 and < 0.75', () => {
    expect(confColor(0.5)).toBe('#f59e0b')
    expect(confColor(0.74)).toBe('#f59e0b')
    expect(confColor(0.6)).toBe('#f59e0b')
  })

  it('returns red for < 0.5', () => {
    expect(confColor(0.49)).toBe('#ef4444')
    expect(confColor(0.0)).toBe('#ef4444')
    expect(confColor(0.1)).toBe('#ef4444')
  })

  it('boundary at exactly 0.75 is green', () => {
    expect(confColor(0.75)).toBe('#22c55e')
  })

  it('boundary at exactly 0.5 is amber', () => {
    expect(confColor(0.5)).toBe('#f59e0b')
  })
})


// ── confPct ───────────────────────────────────────────────────────────────────

describe('confPct', () => {
  it('converts 0.7 to 70', () => {
    expect(confPct(0.7)).toBe(70)
  })

  it('converts 1.0 to 100', () => {
    expect(confPct(1.0)).toBe(100)
  })

  it('converts 0.0 to 0', () => {
    expect(confPct(0.0)).toBe(0)
  })

  it('rounds 0.555 to 56', () => {
    expect(confPct(0.555)).toBe(56)  // Math.round(55.5) = 56
  })

  it('rounds 0.333 to 33', () => {
    expect(confPct(0.333)).toBe(33)
  })

  it('returns integer', () => {
    expect(Number.isInteger(confPct(0.7))).toBe(true)
  })
})


// ── CLAIM_TYPE_META ───────────────────────────────────────────────────────────

describe('CLAIM_TYPE_META', () => {
  const TYPES: ClaimType[] = [
    'symptom', 'finding', 'lab', 'imaging', 'hypothesis',
    'diagnosis', 'therapy', 'risk_factor', 'guideline',
  ]

  it('has an entry for all 9 claim types', () => {
    expect(Object.keys(CLAIM_TYPE_META)).toHaveLength(9)
    for (const t of TYPES) {
      expect(CLAIM_TYPE_META[t]).toBeDefined()
    }
  })

  it('each entry has required fields', () => {
    for (const t of TYPES) {
      const meta = CLAIM_TYPE_META[t]
      expect(meta).toHaveProperty('label')
      expect(meta).toHaveProperty('icon')
      expect(meta).toHaveProperty('color')
      expect(meta).toHaveProperty('bg')
      expect(meta).toHaveProperty('text')
      expect(meta).toHaveProperty('border')
    }
  })

  it('each color is a valid hex string', () => {
    const hexRe = /^#[0-9a-f]{6}$/i
    for (const t of TYPES) {
      expect(CLAIM_TYPE_META[t].color).toMatch(hexRe)
    }
  })

  it('diagnosis and hypothesis have distinct colors', () => {
    expect(CLAIM_TYPE_META.diagnosis.color).not.toBe(CLAIM_TYPE_META.hypothesis.color)
  })
})


// ── getTypeMeta ───────────────────────────────────────────────────────────────

describe('getTypeMeta', () => {
  it('returns correct meta for a known type', () => {
    expect(getTypeMeta('lab')).toBe(CLAIM_TYPE_META.lab)
  })

  it('falls back to finding for unknown type', () => {
    expect(getTypeMeta('unknown_type')).toBe(CLAIM_TYPE_META.finding)
  })

  it('falls back to finding for undefined', () => {
    expect(getTypeMeta(undefined)).toBe(CLAIM_TYPE_META.finding)
  })

  it('falls back to finding for empty string', () => {
    expect(getTypeMeta('')).toBe(CLAIM_TYPE_META.finding)
  })

  it('works for all known types', () => {
    const types: ClaimType[] = [
      'symptom', 'finding', 'lab', 'imaging', 'hypothesis',
      'diagnosis', 'therapy', 'risk_factor', 'guideline',
    ]
    for (const t of types) {
      expect(getTypeMeta(t)).toBe(CLAIM_TYPE_META[t])
    }
  })
})


// ── STATUS_META ───────────────────────────────────────────────────────────────

describe('STATUS_META', () => {
  const statuses: ClaimStatus[] = ['active', 'resolved', 'superseded']

  it('has entries for all statuses', () => {
    for (const s of statuses) {
      expect(STATUS_META[s]).toBeDefined()
    }
  })

  it('each entry has label and color', () => {
    for (const s of statuses) {
      expect(STATUS_META[s]).toHaveProperty('label')
      expect(STATUS_META[s]).toHaveProperty('color')
    }
  })
})


// ── TREND_META ────────────────────────────────────────────────────────────────

describe('TREND_META', () => {
  const trends: ClaimTrend[] = ['improving', 'worsening', 'stable', 'unknown']

  it('has entries for all trends', () => {
    for (const t of trends) {
      expect(TREND_META[t]).toBeDefined()
    }
  })

  it('improving is green', () => {
    expect(TREND_META.improving.color).toBe('#22c55e')
  })

  it('worsening is red', () => {
    expect(TREND_META.worsening.color).toBe('#ef4444')
  })
})


// ── CONFLICT_SEVERITY_META ────────────────────────────────────────────────────

describe('CONFLICT_SEVERITY_META', () => {
  const severities: ConflictSeverity[] = ['error', 'warning', 'info']

  it('has entries for all severities', () => {
    for (const s of severities) {
      expect(CONFLICT_SEVERITY_META[s]).toBeDefined()
    }
  })

  it('each entry has bg, border, text, icon', () => {
    for (const s of severities) {
      const meta = CONFLICT_SEVERITY_META[s]
      expect(meta).toHaveProperty('bg')
      expect(meta).toHaveProperty('border')
      expect(meta).toHaveProperty('text')
      expect(meta).toHaveProperty('icon')
    }
  })
})


// ── Constants ─────────────────────────────────────────────────────────────────

describe('SESSION_KEY', () => {
  it('is a non-empty string', () => {
    expect(typeof SESSION_KEY).toBe('string')
    expect(SESSION_KEY.length).toBeGreaterThan(0)
  })
})
