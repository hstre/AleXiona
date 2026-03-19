import { describe, it, expect } from 'vitest'
import { parseOffset } from '../TimeSlider'


describe('parseOffset', () => {
  // ── Valid formats ────────────────────────────────────────────────────────

  it('parses "t+0h" as 0', () => {
    expect(parseOffset('t+0h')).toBe(0)
  })

  it('parses "t+6h" as 6', () => {
    expect(parseOffset('t+6h')).toBe(6)
  })

  it('parses "t+24h" as 24', () => {
    expect(parseOffset('t+24h')).toBe(24)
  })

  it('parses "t+1.5h" as 1.5', () => {
    expect(parseOffset('t+1.5h')).toBe(1.5)
  })

  it('parses "t+0.5h" as 0.5', () => {
    expect(parseOffset('t+0.5h')).toBe(0.5)
  })

  it('parses "t+100h" as 100', () => {
    expect(parseOffset('t+100h')).toBe(100)
  })

  // ── Case insensitivity ────────────────────────────────────────────────────

  it('parses uppercase "T+6H" as 6', () => {
    expect(parseOffset('T+6H')).toBe(6)
  })

  it('parses mixed case "T+12h" as 12', () => {
    expect(parseOffset('T+12h')).toBe(12)
  })

  // ── Negative offsets ──────────────────────────────────────────────────────

  it('parses "t-2h" as 2 (absolute value extracted)', () => {
    // The regex captures the numeric part after t+/-, so t-2h → 2
    expect(parseOffset('t-2h')).toBe(2)
  })

  // ── Null / undefined / empty ──────────────────────────────────────────────

  it('returns 0 for null', () => {
    expect(parseOffset(null)).toBe(0)
  })

  it('returns 0 for undefined', () => {
    expect(parseOffset(undefined)).toBe(0)
  })

  it('returns 0 for empty string', () => {
    expect(parseOffset('')).toBe(0)
  })

  // ── Unrecognised formats ──────────────────────────────────────────────────

  it('returns 0 for a plain number string', () => {
    expect(parseOffset('6')).toBe(0)
  })

  it('returns 0 for unrelated string', () => {
    expect(parseOffset('baseline')).toBe(0)
  })

  it('returns 0 for partial match "t+h"', () => {
    // No digits between t+ and h — regex won't match
    expect(parseOffset('t+h')).toBe(0)
  })

  // ── Return type ────────────────────────────────────────────────────────────

  it('always returns a number', () => {
    const cases = ['t+6h', 't+0h', null, undefined, '', 'bad']
    for (const c of cases) {
      expect(typeof parseOffset(c as string | null | undefined)).toBe('number')
    }
  })

  it('returns a finite number', () => {
    expect(isFinite(parseOffset('t+6h'))).toBe(true)
    expect(isFinite(parseOffset(null))).toBe(true)
  })
})
