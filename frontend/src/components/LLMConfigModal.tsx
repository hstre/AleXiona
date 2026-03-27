'use client'

import { useState, useEffect, useRef } from 'react'
import { getLLMConfig, saveLLMConfig, testLLMConfig } from '@/lib/api'
import type { LLMTestResult } from '@/lib/api'

interface Props {
  onClose: () => void
}

const PROVIDERS = [
  { value: 'openai',            label: 'OpenAI',             placeholder: 'sk-...',         hasBaseUrl: false, requiresKey: true  },
  { value: 'groq',              label: 'Groq',               placeholder: 'gsk_...',        hasBaseUrl: false, requiresKey: true  },
  { value: 'mistral',           label: 'Mistral',            placeholder: 'API key',        hasBaseUrl: false, requiresKey: true  },
  { value: 'anthropic',         label: 'Anthropic',          placeholder: 'sk-ant-...',     hasBaseUrl: false, requiresKey: true  },
  { value: 'ollama',            label: 'Ollama (local)',     placeholder: '(nicht nötig)',  hasBaseUrl: true,  requiresKey: false },
  { value: 'openai_compatible', label: 'OpenAI Compatible',  placeholder: 'API key',        hasBaseUrl: true,  requiresKey: false },
]

const DEFAULT_MODELS: Record<string, string> = {
  openai:            'gpt-4o',
  groq:              'llama-3.3-70b-versatile',
  mistral:           'mistral-large-latest',
  anthropic:         'claude-sonnet-4-5',
  ollama:            'llama3.2',
  openai_compatible: '',
}

const DEFAULT_BASE_URLS: Record<string, string> = {
  ollama:            'http://localhost:11434/v1',
  openai_compatible: '',
}

export default function LLMConfigModal({ onClose }: Props) {
  const [provider,    setProvider]    = useState('openai')
  const [apiKey,      setApiKey]      = useState('')
  const [model,       setModel]       = useState('')
  const [baseUrl,     setBaseUrl]     = useState('')
  const [keySet,      setKeySet]      = useState(false)
  const [loading,     setLoading]     = useState(true)
  const [saving,      setSaving]      = useState(false)
  const [testing,     setTesting]     = useState(false)
  const [testSeconds, setTestSeconds] = useState(0)
  const [testResult,  setTestResult]  = useState<LLMTestResult | null>(null)
  const [saveMsg,     setSaveMsg]     = useState<{ ok: boolean; text: string } | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load current config on open
  useEffect(() => {
    getLLMConfig()
      .then(cfg => {
        setProvider(cfg.provider)
        setModel(cfg.model)
        setKeySet(cfg.api_key_set)
        setBaseUrl(DEFAULT_BASE_URLS[cfg.provider] ?? '')
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Elapsed-time counter while test is running
  useEffect(() => {
    if (testing) {
      setTestSeconds(0)
      timerRef.current = setInterval(() => setTestSeconds(s => s + 1), 1000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [testing])

  const handleProviderChange = (p: string) => {
    setProvider(p)
    setModel('')
    setBaseUrl(DEFAULT_BASE_URLS[p] ?? '')
    setTestResult(null)
    setSaveMsg(null)
    setValidationError(null)
  }

  const validate = (): string | null => {
    const meta = PROVIDERS.find(p => p.value === provider)!
    if (meta.requiresKey && !keySet && !apiKey.trim()) {
      return `${meta.label} benötigt einen API-Schlüssel.`
    }
    if (provider === 'openai_compatible' && !baseUrl.trim()) {
      return 'OpenAI Compatible benötigt eine Base URL.'
    }
    return null
  }

  const handleSave = async () => {
    const err = validate()
    if (err) { setValidationError(err); return }
    setValidationError(null)
    setSaving(true)
    setSaveMsg(null)
    setTestResult(null)
    try {
      const cfg = await saveLLMConfig({
        provider,
        api_key:  apiKey,
        model:    model  || undefined,
        base_url: baseUrl || undefined,
      })
      setKeySet(cfg.api_key_set)
      setApiKey('')   // clear field — don't keep key in DOM
      setSaveMsg({ ok: true, text: 'Gespeichert.' })
    } catch (e: unknown) {
      setSaveMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    setSaveMsg(null)
    try {
      const result = await testLLMConfig()
      setTestResult(result)
    } catch (e: unknown) {
      setTestResult({ ok: false, error: e instanceof Error ? e.message : String(e) })
    } finally {
      setTesting(false)
    }
  }

  const meta       = PROVIDERS.find(p => p.value === provider)!
  const modelHint  = DEFAULT_MODELS[provider] ?? ''

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--surface-2)',
    border: '1px solid var(--border)', borderRadius: 6,
    padding: '7px 10px', fontSize: 13, color: 'var(--text)',
    outline: 'none',
  }
  const labelStyle: React.CSSProperties = {
    fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, display: 'block',
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.4)' }}
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden"
        style={{ background: 'var(--surface)', border: '1px solid var(--border)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b"
          style={{ borderColor: 'var(--border)' }}>
          <div>
            <h2 className="font-semibold text-sm">KI-Konfiguration</h2>
            <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              LLM-Anbieter und API-Schlüssel
            </p>
          </div>
          <button onClick={onClose} style={{ color: 'var(--text-muted)', fontSize: 18, lineHeight: 1 }}>✕</button>
        </div>

        <div className="p-5 space-y-4">
          {loading ? (
            <p className="text-sm text-center py-4" style={{ color: 'var(--text-muted)' }}>Lade …</p>
          ) : (
            <>
              {/* Provider */}
              <div>
                <label style={labelStyle}>Anbieter</label>
                <div className="grid grid-cols-3 gap-1.5">
                  {PROVIDERS.map(p => (
                    <button
                      key={p.value}
                      onClick={() => handleProviderChange(p.value)}
                      className="text-xs px-2 py-1.5 rounded-lg font-medium transition-all text-left"
                      style={{
                        background:  provider === p.value ? 'var(--brand)'      : 'var(--surface-2)',
                        color:       provider === p.value ? 'white'             : 'var(--text-muted)',
                        border:      `1px solid ${provider === p.value ? 'var(--brand)' : 'var(--border)'}`,
                      }}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* API Key */}
              <div>
                <label style={labelStyle}>
                  API-Schlüssel
                  {meta.requiresKey && !keySet && (
                    <span className="ml-1" style={{ color: '#ef4444' }}>*</span>
                  )}
                  {keySet && (
                    <span className="ml-2 px-1.5 py-0.5 rounded text-xs"
                      style={{ background: '#f0fdf4', color: '#16a34a' }}>
                      ● gesetzt
                    </span>
                  )}
                </label>
                <input
                  type="password"
                  style={inputStyle}
                  placeholder={keySet ? 'Leer lassen um beizubehalten' : meta.placeholder}
                  value={apiKey}
                  onChange={e => { setApiKey(e.target.value); setValidationError(null) }}
                  autoComplete="new-password"
                />
              </div>

              {/* Model */}
              <div>
                <label style={labelStyle}>Modell <span style={{ opacity: 0.5 }}>(optional)</span></label>
                <input
                  type="text"
                  style={inputStyle}
                  placeholder={modelHint || 'Modellname'}
                  value={model}
                  onChange={e => setModel(e.target.value)}
                />
              </div>

              {/* Base URL — only for ollama / openai_compatible */}
              {meta.hasBaseUrl && (
                <div>
                  <label style={labelStyle}>
                    Base URL
                    {provider === 'openai_compatible' && (
                      <span className="ml-1" style={{ color: '#ef4444' }}>*</span>
                    )}
                  </label>
                  <input
                    type="text"
                    style={{
                      ...inputStyle,
                      borderColor: validationError && provider === 'openai_compatible' && !baseUrl.trim()
                        ? '#ef4444' : 'var(--border)',
                    }}
                    placeholder={DEFAULT_BASE_URLS[provider] || 'https://…/v1'}
                    value={baseUrl}
                    onChange={e => { setBaseUrl(e.target.value); setValidationError(null) }}
                  />
                </div>
              )}

              {/* Validation error */}
              {validationError && (
                <div className="rounded-lg px-3 py-2 text-xs"
                  style={{ background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca' }}>
                  {validationError}
                </div>
              )}

              {/* Test result / testing indicator */}
              {testing && (
                <div className="rounded-lg px-3 py-2 text-xs"
                  style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
                  Verbindung wird geprüft …{testSeconds >= 3 ? ` (${testSeconds}s)` : ''}
                </div>
              )}
              {!testing && testResult && (
                <div className="rounded-lg px-3 py-2 text-xs"
                  style={{
                    background: testResult.ok ? '#f0fdf4' : '#fef2f2',
                    color:      testResult.ok ? '#15803d' : '#b91c1c',
                    border:     `1px solid ${testResult.ok ? '#bbf7d0' : '#fecaca'}`,
                  }}>
                  {testResult.ok
                    ? `✓ Verbindung OK — ${testResult.latency_ms} ms`
                    : `✗ Fehler: ${testResult.error}`}
                </div>
              )}

              {/* Save message */}
              {saveMsg && (
                <div className="rounded-lg px-3 py-2 text-xs"
                  style={{
                    background: saveMsg.ok ? '#f0fdf4' : '#fef2f2',
                    color:      saveMsg.ok ? '#15803d' : '#b91c1c',
                  }}>
                  {saveMsg.text}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        {!loading && (
          <div className="flex gap-2 px-5 pb-5">
            <button
              onClick={handleSave}
              disabled={saving || testing}
              className="flex-1 py-2 rounded-xl text-sm font-semibold disabled:opacity-40"
              style={{ background: 'var(--brand)', color: 'white' }}
            >
              {saving ? 'Speichert …' : 'Speichern'}
            </button>
            <button
              onClick={handleTest}
              disabled={testing || saving}
              className="py-2 px-4 rounded-xl text-sm font-medium disabled:opacity-40"
              style={{ background: 'var(--surface-2)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}
            >
              {testing ? `${testSeconds}s …` : 'Verbindung testen'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
