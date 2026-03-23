import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import StartScreen, { type StartMode } from '../StartScreen'

// ── UUID validation (resume button visibility) ─────────────────────────────

describe('StartScreen — resume button', () => {
  it('shows resume button for a valid v4 UUID', () => {
    const onStart = vi.fn()
    render(
      <StartScreen
        existingSessionId="12345678-1234-4234-8234-123456789abc"
        onStart={onStart}
      />
    )
    expect(screen.getByText(/Sitzung fortsetzen/i)).toBeInTheDocument()
  })

  it('hides resume button when existingSessionId is null', () => {
    render(<StartScreen existingSessionId={null} onStart={vi.fn()} />)
    expect(screen.queryByText(/Sitzung fortsetzen/i)).not.toBeInTheDocument()
  })

  it('hides resume button for a plain string (not UUID)', () => {
    render(<StartScreen existingSessionId="not-a-uuid" onStart={vi.fn()} />)
    expect(screen.queryByText(/Sitzung fortsetzen/i)).not.toBeInTheDocument()
  })

  it('hides resume button for a UUID missing one segment', () => {
    render(
      <StartScreen
        existingSessionId="12345678-1234-4234-123456789abc"
        onStart={vi.fn()}
      />
    )
    expect(screen.queryByText(/Sitzung fortsetzen/i)).not.toBeInTheDocument()
  })

  it('hides resume button for an empty string', () => {
    render(<StartScreen existingSessionId="" onStart={vi.fn()} />)
    expect(screen.queryByText(/Sitzung fortsetzen/i)).not.toBeInTheDocument()
  })

  it('accepts uppercase UUID (case-insensitive regex)', () => {
    render(
      <StartScreen
        existingSessionId="12345678-1234-4234-8234-123456789ABC"
        onStart={vi.fn()}
      />
    )
    expect(screen.getByText(/Sitzung fortsetzen/i)).toBeInTheDocument()
  })
})

// ── onStart callbacks ──────────────────────────────────────────────────────

describe('StartScreen — onStart callbacks', () => {
  it('calls onStart with kind=new when "Neue leere Sitzung" is clicked', () => {
    const onStart = vi.fn()
    // When there IS a resumableId, a secondary "neue Sitzung" link appears
    render(
      <StartScreen
        existingSessionId="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        onStart={onStart}
      />
    )
    fireEvent.click(screen.getByText(/Neue leere Sitzung starten/i))
    expect(onStart).toHaveBeenCalledWith({ kind: 'new' })
  })

  it('calls onStart with kind=new when no existing session', () => {
    const onStart = vi.fn()
    render(<StartScreen existingSessionId={null} onStart={onStart} />)
    fireEvent.click(screen.getByText(/Neue Sitzung starten/i))
    expect(onStart).toHaveBeenCalledWith({ kind: 'new' })
  })

  it('calls onStart with kind=resume and the correct sessionId', () => {
    const onStart = vi.fn()
    const sid = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
    render(<StartScreen existingSessionId={sid} onStart={onStart} />)
    fireEvent.click(screen.getByText(/Sitzung fortsetzen/i))
    expect(onStart).toHaveBeenCalledWith({ kind: 'resume', sessionId: sid })
  })

  it('calls onStart with kind=demo including scenario and lang', () => {
    const onStart = vi.fn()
    render(<StartScreen existingSessionId={null} onStart={onStart} />)
    // Default scenario is 'cap', default lang is 'de'
    fireEvent.click(screen.getByText(/Demo laden/i))
    const call = onStart.mock.calls[0][0] as StartMode
    expect(call.kind).toBe('demo')
    if (call.kind === 'demo') {
      expect(call.scenario).toBe('cap')
      expect(call.lang).toBe('de')
    }
  })

  it('passes the selected scenario when changed before loading demo', () => {
    const onStart = vi.fn()
    render(<StartScreen existingSessionId={null} onStart={onStart} />)
    // Switch scenario to 'pe'
    fireEvent.click(screen.getByTitle(/Pulmonary Embolism/i))
    fireEvent.click(screen.getByText(/Demo laden/i))
    const call = onStart.mock.calls[0][0] as StartMode
    if (call.kind === 'demo') {
      expect(call.scenario).toBe('pe')
    }
  })

  it('switches lang to EN when EN button is clicked', () => {
    const onStart = vi.fn()
    render(<StartScreen existingSessionId={null} onStart={onStart} />)
    fireEvent.click(screen.getByText('EN'))
    fireEvent.click(screen.getByText(/Demo laden/i))
    const call = onStart.mock.calls[0][0] as StartMode
    if (call.kind === 'demo') {
      expect(call.lang).toBe('en')
    }
  })
})
