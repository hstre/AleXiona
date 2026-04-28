import { describe, it, expect } from 'vitest'
import { buildLayout } from '../GraphView'
import type { GraphLayout } from '../GraphView'


describe('buildLayout', () => {
  // ── Layout names ────────────────────────────────────────────────────────────

  it('returns name "cose" for cose layout', () => {
    expect(buildLayout('cose').name).toBe('cose')
  })

  it('returns name "breadthfirst" for breadthfirst layout', () => {
    expect(buildLayout('breadthfirst').name).toBe('breadthfirst')
  })

  it('returns name "concentric" for concentric layout', () => {
    expect(buildLayout('concentric').name).toBe('concentric')
  })

  it('returns name "grid" for grid layout', () => {
    expect(buildLayout('grid').name).toBe('grid')
  })


  // ── Animation ───────────────────────────────────────────────────────────────
  // animate: false prevents requestAnimationFrame callbacks that crash on iOS Safari

  it('all layouts have animate: false', () => {
    const layouts: GraphLayout[] = ['cose', 'breadthfirst', 'concentric', 'grid']
    for (const l of layouts) {
      expect(buildLayout(l).animate).toBe(false)
    }
  })


  // ── Layout-specific properties ───────────────────────────────────────────────

  it('cose layout has nodeRepulsion property', () => {
    expect(buildLayout('cose')).toHaveProperty('nodeRepulsion')
  })

  it('cose layout has idealEdgeLength property', () => {
    expect(buildLayout('cose')).toHaveProperty('idealEdgeLength')
  })

  it('breadthfirst layout has directed: true', () => {
    expect(buildLayout('breadthfirst').directed).toBe(true)
  })

  it('breadthfirst layout has spacingFactor > 1', () => {
    expect(buildLayout('breadthfirst').spacingFactor).toBeGreaterThan(1)
  })

  it('concentric layout has a concentric function', () => {
    expect(typeof buildLayout('concentric').concentric).toBe('function')
  })

  it('concentric layout has a levelWidth function', () => {
    expect(typeof buildLayout('concentric').levelWidth).toBe('function')
  })

  it('grid layout has avoidOverlap: true', () => {
    expect(buildLayout('grid').avoidOverlap).toBe(true)
  })


  // ── Concentric function behaviour ─────────────────────────────────────────

  it('concentric fn returns ESS for Claim nodes', () => {
    const { concentric } = buildLayout('concentric')
    const mockClaim = { data: (k: string) => k === 'type' ? 'Claim' : k === 'evidence_support_score' ? 0.85 : undefined }
    expect(concentric(mockClaim)).toBe(0.85)
  })

  it('concentric fn returns 0.5 as default ESS when missing', () => {
    const { concentric } = buildLayout('concentric')
    const mockClaim = { data: (k: string) => k === 'type' ? 'Claim' : undefined }
    expect(concentric(mockClaim)).toBe(0.5)
  })

  it('concentric fn returns 0 for Entity nodes', () => {
    const { concentric } = buildLayout('concentric')
    const mockEntity = { data: (k: string) => k === 'type' ? 'Entity' : undefined }
    expect(concentric(mockEntity)).toBe(0)
  })


  // ── Padding ──────────────────────────────────────────────────────────────────

  it('all layouts have padding > 0', () => {
    const layouts: GraphLayout[] = ['cose', 'breadthfirst', 'concentric', 'grid']
    for (const l of layouts) {
      expect(buildLayout(l).padding).toBeGreaterThan(0)
    }
  })
})
