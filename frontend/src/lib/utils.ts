export const SESSION_KEY = 'alexiona_session'
export const SHORT_ID_LEN = 8

export const shortId = (id: string) => id.slice(0, SHORT_ID_LEN)

/** Returns a CSS color for a 0–1 confidence value. */
export const confColor = (c: number): string =>
  c >= 0.75 ? '#22c55e' : c >= 0.5 ? '#f59e0b' : '#ef4444'

/** Returns a percentage string for a 0–1 confidence value. */
export const confPct = (c: number): number => Math.round(c * 100)
