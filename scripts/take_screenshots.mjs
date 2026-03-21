/**
 * Playwright screenshot script with API mocking
 * Captures all AleXiona views with rich demo data — no backend required.
 */
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR   = path.join(__dirname, '..', 'docs', 'screenshots');
const BASE_URL  = 'http://localhost:3000';
const W = 1440, H = 860;

const SESSION_ID = 'demo-session-screenshot-001';

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_GRAPH = {
  nodes: [
    { id:'c1', label:'Fever 38.9°C', type:'Claim', fullText:'Patient presents with fever of 38.9°C since 3 days', claimId:'c1', claim_type:'symptom', evidence_support_score:0.9, status:'active', source_type:'clinician', time_offset:'t+0h', trend:'worsening' },
    { id:'c2', label:'Dyspnea on exertion', type:'Claim', fullText:'Significant dyspnea on exertion, SpO2 91%', claimId:'c2', claim_type:'symptom', evidence_support_score:0.85, status:'active', source_type:'clinician', time_offset:'t+0h', trend:'worsening' },
    { id:'c3', label:'Leukocytes 16,400/µL', type:'Claim', fullText:'Elevated WBC count 16,400/µL (ref: 4–11k)', claimId:'c3', claim_type:'lab', evidence_support_score:0.95, status:'active', source_type:'lab_system', time_offset:'t+6h', trend:'stable' },
    { id:'c4', label:'CRP 142 mg/L', type:'Claim', fullText:'C-reactive protein elevated at 142 mg/L', claimId:'c4', claim_type:'lab', evidence_support_score:0.92, status:'active', source_type:'lab_system', time_offset:'t+6h', trend:'worsening' },
    { id:'c5', label:'CT: Right lower lobe infiltrate', type:'Claim', fullText:'CT chest: Consolidation right lower lobe consistent with pneumonia', claimId:'c5', claim_type:'imaging', evidence_support_score:0.99, status:'active', source_type:'imaging_model', time_offset:'t+8h', trend:'stable' },
    { id:'c6', label:'Community-acquired Pneumonia', type:'Claim', fullText:'Primary hypothesis: Community-acquired pneumonia (CAP)', claimId:'c6', claim_type:'diagnosis', evidence_support_score:0.82, status:'active', source_type:'llm', time_offset:'t+8h', trend:'stable' },
    { id:'c7', label:'Pleural effusion small right', type:'Claim', fullText:'Small right-sided pleural effusion noted on CT', claimId:'c7', claim_type:'finding', evidence_support_score:0.78, status:'active', source_type:'imaging_model', time_offset:'t+8h', trend:'stable' },
    { id:'c8', label:'Amoxicillin/Clavulanate 875mg', type:'Claim', fullText:'Started Amoxicillin/Clavulanate 875mg BID', claimId:'c8', claim_type:'therapy', evidence_support_score:0.88, status:'active', source_type:'clinician', time_offset:'t+10h', trend:'stable' },
    { id:'c9', label:'D-Dimer elevated 2.1 µg/mL', type:'Claim', fullText:'D-Dimer 2.1 µg/mL — elevated, PE cannot be excluded', claimId:'c9', claim_type:'lab', evidence_support_score:0.72, status:'active', source_type:'lab_system', time_offset:'t+6h', trend:'stable' },
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
    { test_or_type:'Troponin', description:'Elevated troponin would suggest cardiac involvement or PE-related strain', needed_for:'Differentiating CAP from PE or cardiac origin', differentiates_between:['Community-acquired Pneumonia','Pulmonary Embolism'] },
    { test_or_type:'Blood cultures', description:'Not yet resulted — needed before antibiotic de-escalation', needed_for:'Pathogen identification and antibiogram', differentiates_between:['Community-acquired Pneumonia','Heart Failure decompensation'] },
  ],
  focus_points: [
    'Differential diagnosis: CAP vs. Pulmonary Embolism',
    'Consider CT-PA if D-Dimer remains elevated',
  ],
  alternatives: [
    { label:'Pulmonary Embolism', evidence_support_score:0.18, supporting_claim_ids:['c9','c2'] },
    { label:'Heart Failure decompensation', evidence_support_score:0.09, supporting_claim_ids:['c2','c7'] },
    { label:'Lung Abscess', evidence_support_score:0.06, supporting_claim_ids:['c5','c3'] },
  ],
};

const MOCK_CONFLICTS = [
  { id:'cf1', type:'competing_hypothesis', severity:'warning', message:'Elevated D-Dimer (2.1 µg/mL) — PE must be excluded before CAP diagnosis is confirmed', affected_claim_ids:['c9','c6'] },
];

const MOCK_ORCHESTRATOR = {
  session_id: SESSION_ID,
  leading_hypothesis: 'Community-acquired Pneumonia (CAP)',
  orchestrated_score: 0.73,
  status: 'confident',
  why: "'Community-acquired Pneumonia (CAP)' führt mit einem Gesamtscore von 73% (Status: confident). 4 unterstützende Befunde liefern eine Evidenzstärke von 84%. Klinische Scores bestätigen die Richtung: CURB-65=HIGH. Leitlinienkriterien zu 80% erfüllt. 1 widersprüchlicher Befund reduziert die Konfidenz.",
  key_conflicts: ['Elevated D-Dimer (2.1 µg/mL) — PE must be excluded before CAP diagnosis is confirmed'],
  missing_critical: ['blood_cultures', 'troponin', 'procalcitonin'],
  next_action: 'Diagnostik vervollständigen: Blood cultures (Blutkultur) — vor Antibiotikaeskalation erforderlich.',
  score_breakdown: { evidence:0.336, guideline:0.200, composite:0.112, temporal:0.100, conflict:-0.040 },
  alternatives: [
    { text:'Pulmonary Embolism', score:0.18, composite_score_contribution:0.0 },
    { text:'Heart Failure decompensation', score:0.09, composite_score_contribution:0.0 },
  ],
  generated_at: new Date().toISOString(),
};

const MOCK_REPORT = {
  session_id: SESSION_ID,
  report_type: 'arztbrief',
  title: 'Ärztlicher Brief',
  sections: [
    { key:'anamnese',   title:'Anamnese',          text:'Der Patient stellte sich mit seit 3 Tagen bestehendem Fieber bis 38,9 °C sowie progredienter Belastungsdyspnoe vor. Begleitend bestand eine Sauerstoffsättigung von 91 % unter Raumluft. Eine vorbestehende kardiovaskuläre Erkrankung ist nicht bekannt.' },
    { key:'befund',     title:'Klinischer Befund',  text:'Temperatur 38,9 °C, Herzfrequenz 98/min, Atemfrequenz 22/min, SpO₂ 91 % (Raumluft). Auskultatorisch abgeschwächtes Atemgeräusch rechts basal, kein Giemen.' },
    { key:'diagnostik', title:'Diagnostik',          text:'Labor: Leukozyten 16.400/µL, CRP 142 mg/L, D-Dimer 2,1 µg/mL (erhöht). CT Thorax: Konsolidierung rechter Unterlappen, vereinbar mit Pneumonie; kleiner rechtsseitiger Pleuraerguss.' },
    { key:'diagnosen',  title:'Diagnosen',            text:'Ambulant erworbene Pneumonie (CAP), rechter Unterlappen (CURB-65: 2 Punkte — intermediäres Risiko). Erhöhtes D-Dimer — Lungenembolie differenzialdiagnostisch zu bedenken.' },
    { key:'therapie',   title:'Therapie',             text:'Amoxicillin/Clavulansäure 875 mg 2×tgl. oral. Sauerstoffsubstitution bei SpO₂ < 92 %. Engmaschige Vitalzeichenkontrolle.' },
    { key:'procedere',  title:'Procedere / Empfehlungen', text:'Verlaufskontrolle CRP und Leukozyten nach 48 h. Bei persistierend erhöhtem D-Dimer CT-Pulmonalisangiographie. Blutkulturresultate abwarten vor Antibiotikaanpassung. Wiedervorstellung in 5–7 Tagen.' },
  ],
  generated_at: new Date().toISOString(),
};

const MOCK_HYPOTHESIS_CF = {
  hypothesis: 'Community-acquired Pneumonia (CAP)',
  required_changes: [
    'CT chest would need to show NO consolidation (currently: right lower lobe consolidation)',
    'CRP would need to be < 10 mg/L (currently: 142 mg/L)',
    'WBC would need to be within normal range (currently: 16,400/µL)',
    'Fever would need to be absent (currently: 38.9°C × 3 days)',
  ],
  critical_evidence: [
    'CT chest: Consolidation right lower lobe consistent with pneumonia',
    'C-reactive protein elevated at 142 mg/L — key inflammatory marker',
  ],
  alternative_if_false: 'If CAP is excluded, Pulmonary Embolism becomes the leading hypothesis given elevated D-Dimer (2.1 µg/mL) and dyspnea with SpO2 91%.',
  reasoning_trace: 'The CT consolidation is the single most decisive finding — without it, the D-Dimer elevation and dyspnea would shift probability strongly toward PE.',
};

// ── API route mocks ───────────────────────────────────────────────────────────

async function setupMocks(page) {
  // NOTE: Playwright applies the LAST registered matching route first.
  // Register catch-alls first so specific routes (registered later) take priority.

  // ── Catch-all: any session-ID URL → graph data ────────────────────────────
  await page.route(`**/${SESSION_ID}**`,           r => r.fulfill({ json: MOCK_GRAPH }));

  // ── Generic patterns (registered after catch-all → override it) ──────────
  await page.route('**/chat/**', async r => {
    const body = `data: ${JSON.stringify({ type:'done', reply:'Demo', reasoning:MOCK_REASONING, conflicts:MOCK_CONFLICTS })}\n\ndata: [DONE]\n\n`;
    await r.fulfill({ status:200, headers:{'content-type':'text/event-stream','cache-control':'no-cache'}, body });
  });
  await page.route('**/reasoning/**',              r => r.fulfill({ json: MOCK_REASONING }));
  await page.route('**/conflicts/**',              r => r.fulfill({ json: MOCK_CONFLICTS }));
  await page.route('**/counterfactual/hypothesis', r => r.fulfill({ json: MOCK_HYPOTHESIS_CF }));
  await page.route('**/report-types',              r => r.fulfill({ json: [
    { key:'arztbrief', title:'Arztbrief', description:'Vollständiger Arztbrief', sections:[
      {key:'anamnese',title:'Anamnese',required:true},{key:'befund',title:'Klinischer Befund',required:true},
      {key:'diagnostik',title:'Diagnostik',required:true},{key:'diagnosen',title:'Diagnosen',required:true},
      {key:'therapie',title:'Therapie',required:true},{key:'procedere',title:'Procedere',required:true},
    ]},
  ]}));

  // ── Most specific: session endpoints (highest priority, registered last) ──
  await page.route(`**/${SESSION_ID}/report`,      r => r.fulfill({ json: MOCK_REPORT }));
  await page.route(`**/${SESSION_ID}/orchestrate`, r => r.fulfill({ json: MOCK_ORCHESTRATOR }));
}

// ── Helpers ───────────────────────────────────────────────────────────────────

async function injectSession(page) {
  await page.evaluate(sid => localStorage.setItem('alexiona_session', sid), SESSION_ID);
}

async function clickTab(page, label) {
  const btn = page.locator('button').filter({ hasText: label });
  if (await btn.first().isVisible({ timeout: 3000 }).catch(() => false)) {
    await btn.first().click();
    await page.waitForTimeout(1200);
  }
}

async function shot(page, filename) {
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT_DIR, filename), type:'png', animations:'disabled' });
  console.log(`  ✓ ${filename}`);
}

// ── Main ─────────────────────────────────────────────────────────────────────

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx     = await browser.newContext({
    viewport: { width:W, height:H },
    deviceScaleFactor: 2,
    colorScheme: 'light',
  });
  const page = await ctx.newPage();

  // Inject session into localStorage BEFORE the page loads so the app never
  // creates a random UUID and immediately fetches the mocked session's graph.
  await page.addInitScript((sid) => {
    localStorage.setItem('alexiona_session', sid);
  }, SESSION_ID);

  await setupMocks(page);

  await page.goto(BASE_URL, { waitUntil:'domcontentloaded', timeout:60000 });
  // Wait for React hydration + initial graph fetch to complete
  await page.waitForTimeout(4000);

  // Send one message so reasoning state populates
  const ta = page.locator('textarea').first();
  if (await ta.isVisible({ timeout:2000 }).catch(() => false)) {
    await ta.fill('Patient with fever, dyspnea, elevated WBC, CRP 142, CT right lobe infiltrate.');
    await ta.press('Enter');
    await page.waitForTimeout(2800);
  }

  // ── 09: Clinical Orchestrator (new default view) ───────────────────────────
  await clickTab(page, '◎ Zustand');
  await shot(page, '09_orchestrator.png');

  // ── 01: Evidence Graph ─────────────────────────────────────────────────────
  await clickTab(page, '◈ Graph');
  await shot(page, '01_graph_view.png');

  // ── 02: Conflict banner (same view) ───────────────────────────────────────
  await shot(page, '02_conflict_banner.png');

  // ── 07: Reasoning panel (graph + right panel visible) ────────────────────
  await shot(page, '07_reasoning_panel.png');

  // ── 03: Evidence matrix ───────────────────────────────────────────────────
  await clickTab(page, '⊞ Matrix');
  await shot(page, '03_evidence_matrix.png');

  // ── 04: Counterfactual ────────────────────────────────────────────────────
  await clickTab(page, '💡 What-If?');
  await shot(page, '04_counterfactual.png');

  // ── 08: Hypothesis counterfactual (expand from review panel if visible) ───
  await shot(page, '08_hypothesis_counterfactual.png');

  // ── 05: Handover ──────────────────────────────────────────────────────────
  await clickTab(page, '📋 Übergabe');
  await shot(page, '05_handover.png');

  // ── 06: Timeline ──────────────────────────────────────────────────────────
  await clickTab(page, '⏱ Timeline');
  await shot(page, '06_timeline.png');

  // ── 10: Arztbrief / Report panel ──────────────────────────────────────────
  await clickTab(page, '📝 Bericht');
  await page.waitForTimeout(600);
  // Click "Bericht erstellen" button to load the mock report
  const genBtn = page.locator('button').filter({ hasText: 'Bericht erstellen' });
  if (await genBtn.isVisible({ timeout:2000 }).catch(() => false)) {
    await genBtn.click();
    await page.waitForTimeout(1500);
  }
  await shot(page, '10_report.png');

  // ── 11: Back to Orchestrator with score breakdown visible ─────────────────
  await clickTab(page, '◎ Zustand');
  await shot(page, '11_priority.png');

  await browser.close();
  console.log('\n✅  Screenshots saved to docs/screenshots/');
})();
