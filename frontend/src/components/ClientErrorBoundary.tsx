'use client'

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children:  ReactNode
  label?:    string
}

interface State {
  hasError: boolean
  message:  string
}

export default class ClientErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(err: unknown): State {
    const message = err instanceof Error ? err.message : String(err)
    return { hasError: true, message }
  }

  componentDidCatch(err: Error, info: ErrorInfo) {
    try {
      localStorage.setItem('_alexiona_last_error', JSON.stringify({
        label:   this.props.label ?? 'unknown',
        message: err.message,
        stack:   err.stack?.slice(0, 800),
        component: info.componentStack?.slice(0, 400),
        time:    new Date().toISOString(),
      }))
    } catch {}
  }

  reset = () => this.setState({ hasError: false, message: '' })

  render() {
    if (!this.state.hasError) return this.props.children
    const label = this.props.label ?? 'Komponente'
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height: '100%', gap: 12, padding: 24,
      }}>
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8,
          padding: '12px 16px', color: '#991b1b', fontSize: 13, maxWidth: 360, textAlign: 'center',
          wordBreak: 'break-word',
        }}>
          <strong>{label}</strong> konnte nicht geladen werden.
          <div style={{ fontSize: 11, opacity: 0.8, marginTop: 6 }}>{this.state.message}</div>
        </div>
        <button onClick={this.reset} style={{
          fontSize: 12, padding: '6px 14px', borderRadius: 6,
          background: 'var(--brand)', color: 'white', border: 'none', cursor: 'pointer',
        }}>
          Erneut versuchen
        </button>
      </div>
    )
  }
}
