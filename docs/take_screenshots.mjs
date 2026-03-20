/**
 * AleXiona – automated screenshot generator for README illustrations.
 *
 * Usage:
 *   node docs/take_screenshots.mjs
 *
 * Requires: the Next.js dev-server is running on localhost:3000
 *           (or set SCREENSHOT_URL=http://… to override)
 *
 * All API calls are intercepted and return rich mock data so no
 * real backend is needed.
 */

import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.join(__dirname, 'screenshots')
const BASE = process.env.SCREENSHOT_URL ?? 'http://localhost:3000'

// ── Mock data ────────────────────────────────────────────────────────────────

const SESSION = 'demo-0000-0000-0000'

const GRAPH = {
  nodes: [
    { id: 'e1', label: 'Dyspnoe bei Belastung',         type: 'Claim', claimId: 'e1', claim_type: 'symptom',   source_type: 'clinician', evidence_support_score: 0.92, status: 'active',  time_offset: 't+0h',  trend: 'worsening', fullText: 'Dyspnoe bei Belastung', derived_from: [] },
    { id: 'e2', label: 'Tachykardie 118/min',           type: 'Claim', claimId: 'e2', claim_type: 'finding',   source_type: 'clinician', evidence_support_score: 0.88, status: 'active',  time_offset: 't+0h',  trend: 'stable',   fullText: 'Tachykardie 118/min', derived_from: [] },
    { id: 'e3', label: 'D-Dimer 4.2 µg/ml (erhöht)',    type: 'Claim', claimId: 'e3', claim_type: 'lab',       source_type: 'lab_system',evidence_support_score: 0.95, status: 'active',  time_offset: 't+2h',  trend: 'stable',   fullText: 'D-Dimer 4.2 µg/ml (erhöht)', derived_from: [] },
    { id: 'e4', label: 'CT-Angio: Segmentaler Embolus', type: 'Claim', claimId: 'e4', claim_type: 'imaging',   source_type: 'imaging_model', evidence_support_score: 0.97, status: 'active', time_offset: 't+4h', trend: 'stable', fullText: 'CT-Angio: Segmentaler Embolus re. Unterlappenarterie', derived_from: ['e3'] },
    { id: 'e5', label: 'Lungenembolie (Leitdiagnose)',  type: 'Claim', claimId: 'e5', claim_type: 'hypothesis', source_type: 'llm',      evidence_support_score: 0.91, status: 'active',  time_offset: 't+4h',  trend: 'stable',   fullText: 'Lungenembolie als führende Arbeitsdiagnose', derived_from: ['e1','e2','e3','e4'] },
    { id: 'e6', label: 'Antikoagulation mit Heparin',   type: 'Claim', claimId: 'e6', claim_type: 'therapy',   source_type: 'clinician', evidence_support_score: 0.84, status: 'active',  time_offset: 't+5h',  trend: 'unknown',  fullText: 'Antikoagulation mit Heparin i.v.', derived_from: [] },
    { id: 'e7', label: 'Herzinsuffizienz (Alternativ)', type: 'Claim', claimId: 'e7', claim_type: 'hypothesis', source_type: 'llm',      evidence_support_score: 0.32, status: 'active',  time_offset: 't+4h',  trend: 'unknown',  fullText: 'Herzinsuffizienz als Differentialdiagnose', derived_from: [] },
    { id: 'e8', label: 'Keine Beinvenenthrombose',      type: 'Claim', claimId: 'e8', claim_type: 'finding',   source_type: 'clinician', evidence_support_score: 0.78, status: 'active',  time_offset: 't+3h',  trend: 'stable',   fullText: 'Sonographie: keine Beinvenenthrombose nachweisbar', derived_from: [] },
    // entities
    { id: 'n1', label: 'Lunge',     type: 'Entity' },
    { id: 'n2', label: 'D-Dimer',   type: 'Entity' },
    { id: 'n3', label: 'Heparin',   type: 'Entity' },
  ],
  edges: [
    { id: 're1', source: 'e4', target: 'e3', label: 'derives_from' },
    { id: 're2', source: 'e5', target: 'e1', label: 'derives_from' },
    { id: 're3', source: 'e5', target: 'e2', label: 'derives_from' },
    { id: 're4', source: 'e5', target: 'e3', label: 'derives_from' },
    { id: 're5', source: 'e5', target: 'e4', label: 'derives_from' },
    { id: 're6', source: 'e8', target: 'e1', label: 'possible_related' },
    { id: 'me1', source: 'e1', target: 'n1', label: 'mentions' },
    { id: 'me2', source: 'e3', target: 'n2', label: 'mentions' },
    { id: 'me3', source: 'e6', target: 'n3', label: 'mentions' },
  ],
}

const REASONING = {
  leading_hypothesis:     'Lungenembolie (segmentale Ast-Embolie rechts)',
  evidence_support_score: 0.91,
  supporting_evidence:    ['D-Dimer 4.2 µg/ml (erhöht)', 'CT-Angio: Segmentaler Embolus re. Unterlappenarterie', 'Tachykardie 118/min', 'Dyspnoe bei Belastung'],
  conflicting_evidence:   ['Keine Beinvenenthrombose in Sonographie'],
  missing_evidence:       [{ description: 'Echo zum Ausschluss RV-Strain', needed_for: 'Schweregradabschätzung Lungenembolie', test_or_type: 'Echokardiographie' }],
  alternatives:           [{ label: 'Herzinsuffizienz', evidence_support_score: 0.32, supporting_claim_ids: [] }],
  focus_points:           ['Rechtsherzbelastung evaluieren', 'Antikoagulation-Monitoring'],
}

const CONFLICTS = [
  { id: 'c1', severity: 'warning', message: 'Therapiebeginn ohne explizite Indikations-Claim (Antikoagulation → Lungenembolie-Hypothese)', affected_claim_ids: ['e5','e6'], rule: 'therapy_without_indication' },
]

const HYPOTHESIS_COUNTERFACTUAL = {
  hypothesis: 'Lungenembolie (segmentale Ast-Embolie rechts)',
  required_changes: [
    'CT-Angio müsste keinen Embolus zeigen (aktuell: segmentaler Befund re. Unterlappenarterie)',
    'D-Dimer müsste normwertig sein (aktuell: 4.2 µg/ml — 4× oberhalb Grenzwert)',
    'Tachykardie müsste fehlen oder anderweitig erklärt sein',
  ],
  critical_evidence: [
    'CT-Angio: Segmentaler Embolus re. Unterlappenarterie (Quelle: Bildgebungs-KI, sehr hohe Evidenz)',
    'D-Dimer 4.2 µg/ml erhöht (Quelle: Laborsystem, Gewicht ×1.5)',
  ],
  alternative_if_false: 'Herzinsuffizienz würde zur führenden Hypothese (Score 0.32 → 0.58)',
  reasoning_trace: 'Der bildgebende Nachweis ist das entscheidende Kriterium. Ohne CT-Befund und erhöhten D-Dimer verliert die Lungenembolie-Diagnose ihren objektiven Rückhalt — die klinischen Zeichen (Dyspnoe, Tachykardie) wären dann mit Herzinsuffizienz vereinbar.',
}

// ── Helpers ──────────────────────────────────────────────────────────────────

// The frontend calls http://localhost:8000 (NEXT_PUBLIC_API_URL default)
const API = 'http://localhost:8000'

async function mockRoutes(page) {
  // Register BROAD fallbacks first (Playwright LIFO: last registered = first matched)
  // so specific routes registered LAST will take priority.

  await page.route(`${API}/api/**`, r => r.fulfill({ json: [] }))
  await page.route(`${API}/api/graph/**`, r => r.fulfill({ json: { nodes: [], edges: [] } }))

  // session bootstrap
  await page.route(`${API}/api/sessions`, r =>
    r.fulfill({ json: [{ id: SESSION, created_at: new Date().toISOString(), claim_count: GRAPH.nodes.filter(n=>n.type==='Claim').length }] }))

  // chat stream — returns rich mock reasoning + conflicts
  const doneEvent = JSON.stringify({
    type:       'done',
    reply:      'Analyse abgeschlossen.',
    claims:     [],
    session_id: SESSION,
    reasoning:  REASONING,
    conflicts:  CONFLICTS,
  })
  await page.route(`${API}/api/chat**`, r =>
    r.fulfill({ status: 200, contentType: 'text/event-stream',
      body: `data: ${doneEvent}\n\n` }))

  // evidence-node counterfactual (broad — registered first so specific takes priority)
  await page.route(`${API}/api/graph/${SESSION}/counterfactual/**`, r =>
    r.fulfill({ json: {
      excluded_claim_text: 'D-Dimer 4.2 µg/ml (erhöht)',
      changed_evidence:    ['D-Dimer 4.2 µg/ml (erhöht)'],
      shifts: [
        { hypothesis: 'Lungenembolie',    score_before: 0.91, score_after: 0.64 },
        { hypothesis: 'Herzinsuffizienz', score_before: 0.32, score_after: 0.51 },
      ],
      reasoning_trace: 'Ohne den erhöhten D-Dimer-Wert verliert die Lungenembolie-Hypothese ihren stärksten laborchemischen Pfeiler. Die bildgebende Evidenz bleibt, jedoch sinkt die Gesamtunterstützung deutlich.',
    }}))

  // conflicts
  await page.route(`${API}/api/graph/${SESSION}/conflicts`, r =>
    r.fulfill({ json: CONFLICTS }))

  // reasoning
  await page.route(`${API}/api/graph/${SESSION}/reasoning`, r =>
    r.fulfill({ json: REASONING }))

  // graph data (most specific — registered LAST so it wins)
  await page.route(`${API}/api/graph/${SESSION}`, r =>
    r.fulfill({ json: GRAPH }))

  // hypothesis counterfactual — MUST be registered last (after broad counterfactual/**)
  // so it wins in Playwright's LIFO route matching
  await page.route(`${API}/api/graph/${SESSION}/counterfactual/hypothesis`, r =>
    r.fulfill({ json: HYPOTHESIS_COUNTERFACTUAL }))
}

async function injectSession(page) {
  await page.evaluate(sid => {
    localStorage.setItem('alexiona_session', sid)
  }, SESSION)
}

async function dismissErrors(page) {
  // Close Next.js dev error overlay if present
  const closeBtn = page.locator('button[aria-label="Close"], nextjs-portal button').first()
  if (await closeBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await closeBtn.click().catch(() => {})
    await page.waitForTimeout(300)
  }
  // Also try pressing Escape
  await page.keyboard.press('Escape').catch(() => {})
  await page.waitForTimeout(200)
}

async function waitReady(page) {
  await dismissErrors(page)
  // wait until Cytoscape canvas or main content is visible
  await page.waitForSelector('canvas, [data-testid="graph-canvas"], .cy-container', {
    timeout: 15000,
  }).catch(() => {/* graph might not render without real layout — OK */})
  await page.waitForTimeout(2000)
  await dismissErrors(page)
}

async function shoot(page, name, fn) {
  if (fn) await fn()
  await dismissErrors(page)
  await page.waitForTimeout(600)
  await dismissErrors(page)
  const file = path.join(OUT, `${name}.png`)
  await page.screenshot({ path: file, fullPage: false })
  console.log(`  ✓ ${name}.png`)
}

// ── Main ─────────────────────────────────────────────────────────────────────

;(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: [
      '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
      '--disable-web-security', '--font-render-hinting=none',
    ],
  })
  const ctx     = await browser.newContext({ viewport: { width: 1400, height: 860 } })
  const page    = await ctx.newPage()

  // Block external font/analytics requests that stall in offline environments
  await page.route('https://fonts.googleapis.com/**', r => r.abort())
  await page.route('https://fonts.gstatic.com/**', r => r.abort())
  await page.route('https://*.google-analytics.com/**', r => r.abort())

  await mockRoutes(page)

  // Set session in localStorage BEFORE page JS runs so the app picks it up on first load
  await ctx.addInitScript(sid => { localStorage.setItem('alexiona_session', sid) }, SESSION)

  console.log('Opening app…')
  await page.goto(BASE, { waitUntil: 'commit', timeout: 30000 })
  await page.waitForTimeout(4000)

  // Trigger a chat message so the app receives reasoning + conflicts
  const chatInput = page.locator('textarea').first()
  if (await chatInput.isVisible({ timeout: 3000 }).catch(() => false)) {
    await chatInput.fill('Analysiere den Fall')
    await chatInput.press('Enter')
    await page.waitForTimeout(2000)
    await dismissErrors(page)
  }

  console.log('Taking screenshots…')

  // 1. Graph view (default)
  await shoot(page, '01_graph_view')

  // 2. Activate conflict banner by clicking conflicts link
  await shoot(page, '02_conflict_banner', async () => {
    // the conflict banner should already be visible from mock data
  })

  // 3. Evidence-Impact Matrix
  await shoot(page, '03_evidence_matrix', async () => {
    const btn = page.locator('button', { hasText: 'Matrix' })
    if (await btn.count() > 0) await btn.click()
    await page.waitForTimeout(600)
  })

  // 4. Counterfactual panel
  await shoot(page, '04_counterfactual', async () => {
    const btn = page.locator('button', { hasText: 'What-If?' })
    if (await btn.count() > 0) await btn.click()
    await page.waitForTimeout(600)
    // click first claim
    const first = page.locator('button').filter({ hasText: 'D-Dimer' }).first()
    if (await first.count() > 0) await first.click()
    await page.waitForTimeout(1200)
  })

  // 5. Handover panel
  await shoot(page, '05_handover', async () => {
    const btn = page.locator('button', { hasText: 'Übergabe' })
    if (await btn.count() > 0) await btn.click()
    await page.waitForTimeout(600)
  })

  // 6. Timeline view
  await shoot(page, '06_timeline', async () => {
    const btn = page.locator('button', { hasText: 'Timeline' })
    if (await btn.count() > 0) await btn.click()
    await page.waitForTimeout(600)
  })

  // 7. Right panel — reasoning (graph tab via center toggle)
  await shoot(page, '07_reasoning_panel', async () => {
    // use the center-nav Graph button (desktop only, visible at 1400px)
    const btn = page.locator('button').filter({ hasText: '◈ Graph' }).first()
    if (await btn.count() > 0) await btn.click()
    await page.waitForTimeout(400)
  })

  // 8. Hypothesis counterfactual expanded ("What would refute this?")
  await shoot(page, '08_hypothesis_counterfactual', async () => {
    // Make sure we're on the Graph tab so ReviewPanel is visible
    const graphBtn = page.locator('button').filter({ hasText: '◈ Graph' }).first()
    if (await graphBtn.count() > 0) await graphBtn.click()
    await page.waitForTimeout(800)
    // Click "What would refute this?" button in the ReviewPanel
    const refuteBtn = page.locator('button').filter({ hasText: /refute/i }).first()
    const visible = await refuteBtn.isVisible({ timeout: 4000 }).catch(() => false)
    if (visible) {
      await refuteBtn.click()
      // wait for mock API response + render
      await page.waitForTimeout(2500)
    }
  })

  await browser.close()
  console.log('\nDone! Screenshots saved to docs/screenshots/')
})()
