/**
 * Playwright screenshot script with API mocking
 * Captures all 7 AleXiona views with rich demo data
 */
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR   = path.join(__dirname, '..', 'docs', 'screenshots');
const BASE_URL  = 'http://localhost:3000';
const W = 1440, H = 860;

// ── Rich mock data ────────────────────────────────────────────────────────────

const SESSION_ID = 'demo-session-screenshot-001';

const MOCK_GRAPH = {
  nodes: [
    // Claim nodes
    { id:'c1', label:'Fever 38.9°C', type:'Claim', fullText:'Patient presents with fever of 38.9°C since 3 days', claimId:'c1', claim_type:'symptom', evidence_support_score:0.9, status:'active', source_type:'clinician', time_offset:'t=0', trend:'worsening' },
    { id:'c2', label:'Dyspnea on exertion', type:'Claim', fullText:'Significant dyspnea on exertion, SpO2 91%', claimId:'c2', claim_type:'symptom', evidence_support_score:0.85, status:'active', source_type:'clinician', time_offset:'t=0', trend:'worsening' },
    { id:'c3', label:'Leukocytes 16,400/µL', type:'Claim', fullText:'Elevated WBC count 16,400/µL (ref: 4–11k)', claimId:'c3', claim_type:'lab', evidence_support_score:0.95, status:'active', source_type:'lab_system', time_offset:'t+6h', trend:'stable' },
    { id:'c4', label:'CRP 142 mg/L', type:'Claim', fullText:'C-reactive protein elevated at 142 mg/L', claimId:'c4', claim_type:'lab', evidence_support_score:0.92, status:'active', source_type:'lab_system', time_offset:'t+6h', trend:'worsening' },
    { id:'c5', label:'CT: Right lower lobe infiltrate', type:'Claim', fullText:'CT chest: Consolidation right lower lobe consistent with pneumonia', claimId:'c5', claim_type:'imaging', evidence_support_score:0.99, status:'active', source_type:'imaging_model', time_offset:'t+8h', trend:'stable' },
    { id:'c6', label:'Community-acquired Pneumonia', type:'Claim', fullText:'Primary hypothesis: Community-acquired pneumonia (CAP)', claimId:'c6', claim_type:'diagnosis', evidence_support_score:0.82, status:'active', source_type:'llm', time_offset:'t+8h', trend:'stable' },
    { id:'c7', label:'Pleural effusion small right', type:'Claim', fullText:'Small right-sided pleural effusion noted on CT', claimId:'c7', claim_type:'finding', evidence_support_score:0.78, status:'active', source_type:'imaging_model', time_offset:'t+8h', trend:'stable' },
    { id:'c8', label:'Amoxicillin/Clavulanate 875mg', type:'Claim', fullText:'Started Amoxicillin/Clavulanate 875mg BID', claimId:'c8', claim_type:'therapy', evidence_support_score:0.88, status:'active', source_type:'clinician', time_offset:'t+10h', trend:'stable' },
    { id:'c9', label:'D-Dimer elevated 2.1 µg/mL', type:'Claim', fullText:'D-Dimer 2.1 µg/mL — elevated, PE cannot be excluded', claimId:'c9', claim_type:'lab', evidence_support_score:0.72, status:'active', source_type:'lab_system', time_offset:'t+6h', trend:'stable' },
    // Entity nodes
    { id:'e1', label:'Lung', type:'Entity' },
    { id:'e2', label:'Leukocytosis', type:'Entity' },
    { id:'e3', label:'Inflammation', type:'Entity' },
    { id:'e4', label:'Infection', type:'Entity' },
  ],
  edges: [
    { id:'r1', source:'c1', target:'c6', label:'SUPPORTS', type:'SUPPORTS' },
    { id:'r2', source:'c2', target:'c6', label:'SUPPORTS', type:'SUPPORTS' },
    { id:'r3', source:'c3', target:'c6', label:'SUPPORTS', type:'SUPPORTS' },
    { id:'r4', source:'c5', target:'c6', label:'CONFIRMS', type:'SUPPORTS' },
    { id:'r5', source:'c4', target:'c6', label:'SUPPORTS', type:'SUPPORTS' },
    { id:'r6', source:'c9', target:'c6', label:'CONTRADICTS', type:'CONTRADICTS' },
    { id:'r7', source:'c1', target:'e4', label:'INDICATES', type:'RELATED' },
    { id:'r8', source:'c3', target:'e2', label:'IS_A', type:'RELATED' },
    { id:'r9', source:'c5', target:'e1', label:'LOCATED_IN', type:'RELATED' },
    { id:'r10', source:'c6', target:'c8', label:'LEADS_TO', type:'RELATED' },
  ],
};

const MOCK_REASONING = {
  leading_hypothesis: 'Community-acquired Pneumonia (CAP)',
  evidence_support_score: 0.82,
  supporting_evidence: [
    'Fever 38.9°C with 3-day duration supports infectious etiology',
    'CT chest confirms right lower lobe consolidation pattern',
    'Elevated WBC 16,400/µL and CRP 142 mg/L indicate systemic inflammation',
    'Dyspnea with SpO2 91% consistent with parenchymal involvement',
  ],
  conflicting_evidence: [
    'Elevated D-Dimer (2.1 µg/mL) raises concern for concurrent PE',
    'Unilateral effusion may suggest parapneumonic or alternative diagnosis',
  ],
  missing_evidence: [
    { test_or_type:'Troponin', description:'Elevated troponin would suggest cardiac involvement or PE-related strain', needed_for:'Differentiating CAP from PE or cardiac origin', differentiates_between:['Community-acquired Pneumonia', 'Pulmonary Embolism'] },
    { test_or_type:'Blood cultures', description:'Not yet resulted — needed before antibiotic de-escalation', needed_for:'Pathogen identification and antibiogram', differentiates_between:['Community-acquired Pneumonia', 'Heart Failure decompensation'] },
  ],
  focus_points: [
    'Differential diagnosis: CAP vs. Pulmonary Embolism',
    'Consider CT-PA if D-Dimer remains elevated',
    'Monitor SpO2 — escalate if <90% on room air',
  ],
  alternatives: [
    { label:'Pulmonary Embolism', evidence_support_score:0.18, supporting_claim_ids:['c9','c2'] },
    { label:'Heart Failure decompensation', evidence_support_score:0.09, supporting_claim_ids:['c2','c7'] },
    { label:'Lung Abscess', evidence_support_score:0.06, supporting_claim_ids:['c5','c3'] },
  ],
};

const MOCK_CONFLICTS = [
  {
    id:'cf1', type:'competing_hypothesis', severity:'warning',
    message:'Elevated D-Dimer conflicts with CAP as sole diagnosis — PE must be excluded',
    affected_claim_ids:['c9','c6'],
  },
];

// ── API route mock handlers ───────────────────────────────────────────────────

async function setupMocks(page) {
  await page.route('**/graph/**', async route => {
    await route.fulfill({ json: MOCK_GRAPH });
  });
  await page.route('**/reasoning/**', async route => {
    await route.fulfill({ json: MOCK_REASONING });
  });
  await page.route('**/conflicts/**', async route => {
    await route.fulfill({ json: MOCK_CONFLICTS });
  });
  await page.route('**/seed_demo/**', async route => {
    await route.fulfill({ json: { status: 'ok' } });
  });
  // Block streaming endpoint — return SSE with done event
  await page.route('**/chat/**', async route => {
    const body = `data: ${JSON.stringify({ type:'done', reply:'Demo mode — backend offline.', reasoning: MOCK_REASONING, conflicts: MOCK_CONFLICTS })}\n\ndata: [DONE]\n\n`;
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
      body,
    });
  });
}

// ── Helper: inject state via window globals ───────────────────────────────────

async function injectAppState(page) {
  // Set localStorage session
  await page.evaluate((sid) => {
    localStorage.setItem('alexiona_session', sid);
  }, SESSION_ID);

  // Patch fetch so /graph/ returns mock data even if not caught by route
  await page.evaluate((graph) => {
    const orig = window.fetch;
    window.__mockGraph = graph;
    window.fetch = async function(url, ...args) {
      if (typeof url === 'string' && url.includes('/graph/')) {
        return new Response(JSON.stringify(graph), { status:200, headers:{'content-type':'application/json'} });
      }
      return orig(url, ...args);
    };
  }, MOCK_GRAPH);
}

// ── Screenshot helper ─────────────────────────────────────────────────────────

async function shot(page, filename) {
  await page.waitForTimeout(900);
  await page.screenshot({
    path: path.join(OUT_DIR, filename),
    type: 'png',
    animations: 'disabled',
  });
  console.log(`✓  ${filename}`);
}

// ── Main ─────────────────────────────────────────────────────────────────────

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx     = await browser.newContext({
    viewport: { width: W, height: H },
    deviceScaleFactor: 2,
    colorScheme: 'light',
  });
  const page = await ctx.newPage();

  // Register API mocks before navigation
  await setupMocks(page);

  // Navigate
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2000);

  // Inject mocked state into window / React state via re-fetching
  await injectAppState(page);
  await page.waitForTimeout(1500);

  // Click "Refresh" to load the mocked graph
  const refreshBtn = page.locator('button[title="Refresh"]');
  if (await refreshBtn.isVisible({ timeout: 2000 }).catch(() => false)) {
    await refreshBtn.click();
    await page.waitForTimeout(2000);
  }

  // ── Send a chat message so the mocked streaming endpoint returns reasoning ──
  // This populates the reasoning state needed by the Matrix and ReviewPanel
  const textarea = page.locator('textarea').first();
  if (await textarea.isVisible({ timeout: 2000 }).catch(() => false)) {
    await textarea.fill('Patient has fever, dyspnea, elevated WBC and right lobe infiltrate on CT.');
    await page.waitForTimeout(300);
    // Press Enter to send
    await textarea.press('Enter');
    // Wait for the streaming mock to respond and reasoning state to be set
    await page.waitForTimeout(2500);
  }

  // ── 01: Graph view ──────────────────────────────────────────────────────
  const graphTab = page.locator('button', { hasText: '◈ Graph' });
  if (await graphTab.isVisible({ timeout: 2000 }).catch(() => false)) await graphTab.click();
  await shot(page, '01_graph_view.png');

  // ── 02: Conflict banner (same view, banner should be visible) ──────────
  await shot(page, '02_conflict_banner.png');

  // ── 03: Evidence matrix ─────────────────────────────────────────────────
  const matBtn = page.locator('button', { hasText: '⊞ Matrix' });
  if (await matBtn.isVisible({ timeout: 2000 }).catch(() => false)) await matBtn.click();
  await shot(page, '03_evidence_matrix.png');

  // ── 04: Counterfactual ──────────────────────────────────────────────────
  const cfBtn = page.locator('button', { hasText: '💡 What-If?' });
  if (await cfBtn.isVisible({ timeout: 2000 }).catch(() => false)) await cfBtn.click();
  await shot(page, '04_counterfactual.png');

  // ── 05: Handover ────────────────────────────────────────────────────────
  const hBtn = page.locator('button', { hasText: '📋 Übergabe' });
  if (await hBtn.isVisible({ timeout: 2000 }).catch(() => false)) await hBtn.click();
  await shot(page, '05_handover.png');

  // ── 06: Timeline ────────────────────────────────────────────────────────
  const tlBtn = page.locator('button', { hasText: '⏱ Timeline' });
  if (await tlBtn.isVisible({ timeout: 2000 }).catch(() => false)) await tlBtn.click();
  await shot(page, '06_timeline.png');

  // ── 07: Reasoning panel (back to graph) ─────────────────────────────────
  const gTab = page.locator('button', { hasText: '◈ Graph' });
  if (await gTab.isVisible({ timeout: 2000 }).catch(() => false)) await gTab.click();
  await shot(page, '07_reasoning_panel.png');

  await browser.close();
  console.log('\n✅  All screenshots saved to docs/screenshots/');
})();
