import type { ClaimType, ClaimStatus, ClaimTrend, ConflictSeverity } from './api'

export const SESSION_KEY = 'alexiona_session'
export const SHORT_ID_LEN = 8

export const shortId  = (id: string): string  => id.slice(0, SHORT_ID_LEN)
export const confColor = (c: number): string  =>
  c >= 0.75 ? '#22c55e' : c >= 0.5 ? '#f59e0b' : '#ef4444'
export const confPct   = (c: number): number  => Math.round(c * 100)

/** Human-readable evidence support label — never implies diagnostic probability. */
export const essLabel = (c: number): 'low' | 'moderate' | 'strong' =>
  c >= 0.75 ? 'strong' : c >= 0.5 ? 'moderate' : 'low'

export const ESS_LABEL_META: Record<'low' | 'moderate' | 'strong', { bg: string; text: string }> = {
  low:      { bg: '#fef2f2', text: '#b91c1c' },
  moderate: { bg: '#fffbeb', text: '#92400e' },
  strong:   { bg: '#f0fdf4', text: '#14532d' },
}

// ── Claim Type ───────────────────────────────────────────────────────────────

export interface TypeMeta {
  label:  string
  icon:   string
  color:  string   // node fill / border
  bg:     string   // card background
  text:   string   // card text
  border: string   // card left border
}

export const CLAIM_TYPE_META: Record<ClaimType, TypeMeta> = {
  symptom:     { label: 'Symptom',     icon: '⚕',  color: '#f59e0b', bg: '#fff8e1', text: '#92400e', border: '#f59e0b' },
  finding:     { label: 'Finding',     icon: '🔬', color: '#3b82f6', bg: '#eff6ff', text: '#1e3a8a', border: '#3b82f6' },
  lab:         { label: 'Lab',         icon: '🧪', color: '#8b5cf6', bg: '#f5f3ff', text: '#4c1d95', border: '#8b5cf6' },
  imaging:     { label: 'Imaging',     icon: '🩻', color: '#06b6d4', bg: '#ecfeff', text: '#164e63', border: '#06b6d4' },
  hypothesis:  { label: 'Hypothesis',  icon: '💡', color: '#eab308', bg: '#fefce8', text: '#713f12', border: '#eab308' },
  diagnosis:   { label: 'Diagnosis',   icon: '🎯', color: '#1a7ab3', bg: '#e8f4fc', text: '#0c3a5f', border: '#1a7ab3' },
  therapy:     { label: 'Therapy',     icon: '💊', color: '#22c55e', bg: '#f0fdf4', text: '#14532d', border: '#22c55e' },
  risk_factor: { label: 'Risk Factor', icon: '⚠',  color: '#ef4444', bg: '#fef2f2', text: '#7f1d1d', border: '#ef4444' },
  guideline:   { label: 'Guideline',   icon: '📖', color: '#6b7280', bg: '#f9fafb', text: '#374151', border: '#6b7280' },
}

export const getTypeMeta = (t?: ClaimType | string): TypeMeta =>
  CLAIM_TYPE_META[(t ?? 'finding') as ClaimType] ?? CLAIM_TYPE_META.finding

// ── Status ────────────────────────────────────────────────────────────────────

export const STATUS_META: Record<ClaimStatus, { label: string; color: string }> = {
  active:     { label: 'Active',     color: '#22c55e' },
  observed:   { label: 'Observed',   color: '#3b82f6' },
  resolved:   { label: 'Resolved',   color: '#6b7280' },
  superseded: { label: 'Superseded', color: '#f59e0b' },
}

// ── Trend ─────────────────────────────────────────────────────────────────────

export const TREND_META: Record<ClaimTrend, { icon: string; color: string }> = {
  improving: { icon: '↑', color: '#22c55e' },
  worsening: { icon: '↓', color: '#ef4444' },
  stable:    { icon: '→', color: '#6b7280' },
  unknown:   { icon: '?', color: '#9ca3af' },
}

// ── Conflict ─────────────────────────────────────────────────────────────────

export const CONFLICT_SEVERITY_META: Record<ConflictSeverity, { bg: string; border: string; text: string; icon: string }> = {
  error:   { bg: '#fef2f2', border: '#ef4444', text: '#7f1d1d', icon: '⛔' },
  warning: { bg: '#fffbeb', border: '#f59e0b', text: '#78350f', icon: '⚠' },
  info:    { bg: '#eff6ff', border: '#3b82f6', text: '#1e3a8a', icon: 'ℹ' },
}
