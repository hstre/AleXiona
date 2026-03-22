'use client'

import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  error: Error | null
}

/**
 * React Error Boundary — catches rendering errors and shows a safe fallback
 * instead of a blank white screen.  In a medical context it is critical that
 * the user sees a clear error message rather than nothing at all.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Log to console; in production this could forward to a monitoring service
    console.error('[ErrorBoundary] Rendering error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div
          style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', height: '100vh', padding: '2rem',
            fontFamily: 'sans-serif', background: '#fef2f2', color: '#991b1b',
          }}
        >
          <h2 style={{ marginBottom: '0.5rem', fontSize: '1.25rem', fontWeight: 600 }}>
            Ein Fehler ist aufgetreten
          </h2>
          <p style={{ marginBottom: '1rem', fontSize: '0.875rem', color: '#7f1d1d', maxWidth: 480, textAlign: 'center' }}>
            Die Anwendung konnte nicht gerendert werden. Bitte laden Sie die Seite neu.
            Wenn das Problem weiterhin besteht, wenden Sie sich an den Support.
          </p>
          <pre style={{ fontSize: '0.75rem', background: '#fff', padding: '0.75rem 1rem',
            borderRadius: '0.375rem', border: '1px solid #fca5a5', maxWidth: 600,
            overflow: 'auto', color: '#374151' }}>
            {this.state.error.message}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: '1.5rem', padding: '0.5rem 1.5rem', background: '#dc2626',
              color: '#fff', border: 'none', borderRadius: '0.375rem', cursor: 'pointer',
              fontSize: '0.875rem' }}
          >
            Erneut versuchen
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
