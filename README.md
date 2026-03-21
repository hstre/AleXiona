# AleXiona — Clinical Evidence Graph

A clinical reasoning infrastructure demonstrator.
AleXiona turns unstructured clinical input into a versioned, revisable knowledge
structure — an **evidence graph** where every claim carries provenance, supports or
contradicts a hypothesis, and can be challenged by counterfactual analysis.

> **Not a diagnostic system.** AleXiona is a reasoning *aid*. All conclusions require
> verification by a qualified clinician.

---

## Screenshots

| Evidence Graph | Clinical Reasoning |
|---|---|
| ![Evidence graph with type-coloured nodes, derives_from edges and conflict banner](docs/screenshots/01_graph_view.png) | ![AI Reviewer panel: confidence gauge, supporting and conflicting evidence, missing evidence](docs/screenshots/07_reasoning_panel.png) |

| Evidence × Diagnosis Matrix | What-If? Evidence Counterfactual |
|---|---|
| ![Matrix view mapping each evidence node to hypotheses with supports/contradicts annotations](docs/screenshots/03_evidence_matrix.png) | ![Counterfactual panel: selecting D-Dimer shows before/after score shifts for each hypothesis](docs/screenshots/04_counterfactual.png) |

| Hypothesis Counterfactual | Clinical Handover (Übergabe) |
|---|---|
| ![Expanded "What would refute this?" panel showing required changes and decisive evidence](docs/screenshots/08_hypothesis_counterfactual.png) | ![Handover form auto-populated with Leitdiagnose, Befunde, Offene Diagnostik — PDF export](docs/screenshots/05_handover.png) |

| Evidence Timeline | |
|---|---|
| ![Timeline view showing claims distributed by time offset t+0h to t+5h](docs/screenshots/06_timeline.png) | |

---

## What it Does

Instead of storing clinical observations as flat text, AleXiona builds an explicit
**epistemic graph**: each piece of evidence is a typed, timestamped node that either
supports or contradicts a leading hypothesis. Conflicts between claims are detected by
a deterministic rule engine (not an LLM) and surfaced immediately. The graph can be
interrogated — "what changes if this finding were absent?" — via counterfactual
analysis, and exported as a structured handover document.

### Core Capabilities

| Capability | Description |
|---|---|
| **Claim extraction** | LLM converts free text into typed, scored evidence nodes |
| **Evidence graph** | Cytoscape.js force graph with provenance edges (`derives_from`, `possible_related`) |
| **Rule-based hypothesis scoring** | Weighted by source type (guideline ×2.0, lab_system ×1.5, llm ×0.5), temporal decay, and conflict severity (negation −2.0, quantitative clash −1.5) |
| **Claim contribution analysis** | Per-claim breakdown of exactly *how much* each evidence node drives each hypothesis score — direction, magnitude, source_weight, temporal_weight, SPL emission rule, trend_boosted flag |
| **Conflict engine** | 8-rule deterministic detection: contradictory values, stale hypotheses, therapy without indication, temporal inconsistencies, and more |
| **Confidence hard-stop** | Score < 0.2 or ≥ 3 conflicting claims → ⚠ "Insufficient evidence for reliable prioritization" |
| **Explain leading** | Rule-based explanation of *why* the current hypothesis is leading: supporting texts, conflicting texts, key missing evidence |
| **Guideline layer** | Required-evidence terms for 5 diagnoses (pneumonia, PE, sepsis, MI, heart failure); used in missing-evidence detection |
| **Validated risk scores** | 6 bedside scores computed automatically from the claim graph: qSOFA, Wells-PE, GRACE-ACS, HEART, PERC, CURB-65 — each with criteria_met, criteria_missing, and recommendation |
| **Role-based views** | Each clinical role receives exactly the information relevant to their task (see below) |
| **Timeline** | Chronological view of all claims by time offset (`t+0h`, `t+6h`, …) |
| **Evidence counterfactual** | "What if this evidence were absent?" — per-node LLM analysis with hypothesis score shifts |
| **Hypothesis counterfactual** | "What would refute this hypothesis?" — shows required changes, decisive evidence, and which hypothesis would become leading |
| **Evidence-Impact Matrix** | Claim × hypothesis table annotating which evidence supports or contradicts each hypothesis |
| **MED engine** | Minimal Evidence to Decision — simulates which test result would most change the current ranking |
| **Clinical handover** | Auto-populated, editable handover form (Leitdiagnose, Differentialdiagnose, Schlüsselbefunde, Offene Diagnostik, …) with PDF and clipboard export |
| **Conflict explanation** | On-demand LLM explanation for each detected conflict |

---

## Role-Based Clinical Views

`GET /api/graph/{session_id}/view/{role}`

The same claim graph produces a role-filtered view for each member of the clinical team. Each role sees exactly what they need — nothing more.

| Role | German alias | What they see |
|---|---|---|
| `nurse` | `pfleger`, `pflegerin` | Vitals with HIGH/LOW flags, trend alerts (tachycardia, hypoxia, fever), active symptoms, monitoring tasks for undocumented parameters |
| `resident` | `assistenzarzt`, `assistenzärztin` | Full hypothesis ranking + guideline compliance, relevant risk scores, evidence by type (lab / finding / symptom / imaging), critical alerts for high-risk scores |
| `specialist` | `facharzt`, `fachärztin` | Specialty-filtered hypotheses, per-claim contribution breakdown (source_weight, temporal_weight, SPL rule, trend_boosted), specialty-matched risk scores — `?specialty=cardiology\|pulmonology\|infectiology\|neurology\|nephrology\|gastroenterology` |
| `lab` | `labor`, `laborant` | Parsed lab values with qualitative flags, abnormal values section, unstructured lab notes, requested/pending tests derived from guideline gaps |
| `chief` | `chefarzt`, `chefärztin`, `oberarzt`, `attending` | Executive summary (confidence + leading hypothesis), differential top-5, risk flags (relevant + high/intermediate), open issues (contested/inferred claims), case statistics |

Alerts are sorted `critical → warning → info` within each view.

---

## Validated Risk Scores

`GET /api/graph/{session_id}/risk-scores`

All six scores are computed simultaneously from the claim graph and annotated with `relevant: true` when they match the active differential.

| Score | Guideline | Interpretation |
|---|---|---|
| **qSOFA** | Singer et al., JAMA 2016 | ≥2 → high sepsis risk |
| **Wells-PE** | Wells et al., 2000 | >6 high / 2–6 intermediate / <2 low PE probability |
| **GRACE-ACS** | Fox et al., BMJ 2006 | ≥5 high / ≥3 intermediate ACS risk |
| **HEART** | Backus et al., 2010 | ≥7 high / 4–6 intermediate / ≤3 low MACE risk |
| **PERC** | Kline et al., 2004 | All 8 absent → PE excluded without D-Dimer |
| **CURB-65** | Lim et al., Thorax 2003 | ≥3 high / 2 intermediate / ≤1 low pneumonia severity |

Each score returns: `criteria_met` (with point values), `criteria_missing`, `interpretation`, `relevant`, and an evidence-based `recommendation`.

---

## Claim Contribution Analysis

`GET /api/graph/{session_id}/reasoning/explain`

Per-claim transparency for every active hypothesis — the SHAP equivalent for rule-based clinical reasoning:

```json
{
  "hypothesis_text": "pulmonary embolism suspected",
  "rule_based_score": 0.855,
  "total_support": 0.855,
  "total_conflict": 0.0,
  "contributions": [
    {
      "claim_text": "D-Dimer 3.2 µg/mL elevated",
      "direction": "supporting",
      "contribution": 0.855,
      "spl_emission_rule": "E1",
      "source_weight": 1.5,
      "temporal_weight": 1.0,
      "trend_boosted": false
    }
  ],
  "guideline": {
    "required_present": ["dyspnea"],
    "required_missing": ["tachycardia"],
    ...
  }
}
```

---

## Architecture

```
Clinician / Import
       │
       ▼
  Next.js 14 UI
  ├── Evidence Graph (Cytoscape.js)
  ├── Timeline Panel
  ├── Evidence-Impact Matrix
  ├── Evidence Counterfactual Panel
  ├── Hypothesis Counterfactual (inline in AI Reviewer)
  └── Clinical Handover (PDF export)
       │ HTTP / SSE
       ▼
  FastAPI Backend
  ├── LLM Client (OpenAI GPT-4o, structured JSON)
  │     ├── Claim extraction
  │     ├── Clinical reasoning summary
  │     ├── Evidence counterfactual analysis
  │     ├── Hypothesis counterfactual analysis
  │     └── Conflict explanation
  ├── Reasoning Engine (rule-based, deterministic)
  │     ├── Source-weighted hypothesis scoring
  │     │     (guideline ×2.0 / lab_system ×1.5 / clinician ×1.2 / llm ×0.5)
  │     ├── Temporal decay (lab 12h / finding 48h / symptom 72h / imaging 96h half-life)
  │     ├── Typed conflict penalties
  │     │     (negation −2.0 / quantitative clash −1.5 / default −1.0)
  │     ├── Trend signal boost (×1.4 for matching clinical_flag keywords)
  │     ├── explain_leading() — why this hypothesis is ranked first
  │     ├── explain_hypothesis_scores() — per-claim contribution breakdown
  │     ├── Guideline layer — required evidence for known diagnoses
  │     ├── Hard stop — insufficient evidence signal
  │     └── Case snapshot — timestamped audit record
  ├── Composite Score Engine (rule-based, deterministic)
  │     ├── qSOFA, Wells-PE, GRACE-ACS   (existing)
  │     ├── HEART, PERC, CURB-65         (new)
  │     └── compute_all_scores() — all six with relevance flags + recommendations
  ├── Role View Engine
  │     ├── nurse    — vitals, trend alerts, monitoring tasks
  │     ├── resident — full differential + risk scores + evidence
  │     ├── specialist — specialty-filtered + claim contribution breakdown
  │     ├── lab      — parsed lab values + abnormal flags + pending
  │     └── chief    — executive summary + risk flags + open issues
  ├── Conflict Engine (rule-based, deterministic)
  │     ├── competing_hypothesis
  │     ├── negation
  │     ├── evidence_mismatch
  │     ├── timeline_gap
  │     ├── therapy_without_indication
  │     ├── stale_hypothesis
  │     ├── contradictory_values
  │     └── temporal_inconsistency
  ├── MED Engine — Minimal Evidence to Decision
  └── Neo4j 5
        ├── (:Claim) nodes — typed, timestamped, versioned
        ├── [:DERIVES_FROM] — explicit epistemic provenance (user-confirmed)
        └── [:POSSIBLE_RELATED] — heuristic similarity (not derivation)
```

---

## API Reference (Backend)

| Endpoint | Description |
|---|---|
| `POST /{session_id}/claims` | Add one or more claims |
| `GET /{session_id}/graph` | Full graph (nodes + edges) |
| `GET /{session_id}/reasoning` | LLM reasoning summary with rule-based anchors |
| `GET /{session_id}/reasoning/explain` | Per-claim contribution breakdown for all hypotheses |
| `GET /{session_id}/risk-scores` | All 6 validated bedside risk scores |
| `GET /{session_id}/view/{role}` | Role-filtered clinical view (nurse / resident / specialist / lab / chief) |
| `GET /{session_id}/conflicts` | All detected conflicts |
| `POST /{session_id}/counterfactual` | Evidence counterfactual analysis |
| `POST /{session_id}/hypothesis-counterfactual` | Hypothesis counterfactual analysis |
| `GET /{session_id}/med` | Minimal Evidence to Decision |
| `GET /{session_id}/snapshot` | Timestamped case state snapshot |

Full interactive docs: `http://localhost:8000/docs`

---

## Graph Schema

```
(:Claim {
  id, text, session_id,
  claim_type,              // symptom | finding | lab | imaging | hypothesis |
                           // diagnosis | therapy | risk_factor | guideline
  source_type,             // clinician | llm | guideline | imaging_model |
                           //   lab_system | imported_document | wearable |
                           //   home_device | caregiver_report | patient_report
  evidence_support_score,  // 0.0–1.0 internal support metric (NOT probability)
  status,                  // active | observed | inferred | confirmed | contested |
                           //   resolved | superseded | refuted | withdrawn
  time_offset,             // "t+0h", "t+6h", etc. (legacy)
  event_time,              // ISO-8601 absolute timestamp (preferred)
  spl_emission_rule,       // "E1" | "E2" | "E3" | "E4" — epistemic quality tier
  trend,                   // improving | worsening | stable | unknown
  derived_from             // JSON list of source claim IDs (explicit only)
})

(:Entity { name })

(:Claim)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATION {type}]->(:Entity)
(:Claim)-[:DERIVES_FROM]->(:Claim)      // explicit epistemic derivation only
(:Claim)-[:POSSIBLE_RELATED]->(:Claim) // heuristic keyword overlap — NOT derivation
```

### Evidence Support Score

`evidence_support_score` is an **internal support metric** (0.0–1.0).
It is displayed as `low / moderate / strong` in the UI.
It is **not a diagnostic probability** and must not be interpreted as such.

### Derivation vs. Similarity

`DERIVES_FROM` is set only by explicit user action ("Add Evidence Node" dialog).
It means: *this claim is a direct logical/clinical consequence of the source*.

`POSSIBLE_RELATED` is a heuristic edge created automatically when two claims share
≥ 2 key medical terms. It indicates topical proximity, **not epistemic derivation**,
and appears as a dotted grey edge in the graph.

---

## Reasoning Engine

The reasoning engine scores hypotheses rule-based — no LLM involved.

### Hypothesis Score Formula

```
score(H) = Σ(ess_i × overlap_weight_i × source_weight_i × temporal_weight_i × confirm_weight_i)
           for supporting evidence i
         − Σ(conflict_penalty_i)
           for conflicting evidence i
  clamped to [0.0, 1.0]
```

### Source Weights

| Source type | Weight | Rationale |
|---|---|---|
| `guideline` | ×2.0 | Clinical guideline — highest authority |
| `lab_system` | ×1.5 | Direct lab measurement — objective |
| `clinician` | ×1.2 | Direct observation |
| `imaging_model` | ×1.0 | Neutral |
| `imported_document` | ×1.0 | Neutral |
| `llm` | ×0.5 | LLM inference — down-weighted until confirmed |
| `wearable` | ×0.7 | Patient-generated — own epistemic tier |
| `patient_report` | ×0.4 | Self-reported — lowest authority |

### Temporal Decay

Evidence loses relevance over time (exponential half-life, clamped to [0.25, 1.0]):

| Claim type | Half-life |
|---|---|
| `lab` | 12 h |
| `finding` | 48 h |
| `symptom` | 72 h |
| `imaging` | 96 h |

### Conflict Penalties

| Contradiction type | Penalty | Trigger |
|---|---|---|
| Negation | −2.0 | "no fever", "ruled out", "kein …" |
| Quantitative clash | −1.5 | "CRP elevated" vs "CRP normal" |
| Generic overlap | −1.0 | Shared terms, no polarity signal |

### Hard Stop

When the top hypothesis has `score < 0.2` **or** `≥ 3 conflicting claims`, the engine returns:

```
⚠ Insufficient evidence for reliable prioritization
```

### Guideline Layer

Required evidence terms for five diagnoses:

| Diagnosis | Required |
|---|---|
| Pneumonia | fever, cough |
| Pulmonary embolism | dyspnea, tachycardia |
| Sepsis | fever, infection |
| Myocardial infarction | chest pain, troponin |
| Heart failure | dyspnea, edema |

---

## Conflict Engine

The conflict engine runs deterministically on the current claim set — no LLM involved.

| Rule | Severity | Trigger |
|---|---|---|
| `competing_hypothesis` | warning | ≥ 2 active diagnosis/hypothesis claims |
| `negation` | error | Two claims share ≥ 2 key terms; one negates the other |
| `evidence_mismatch` | info | Strong evidence (ess ≥ 0.85) exists but leading hypothesis has low support (ess < 0.4) |
| `timeline_gap` | warning | Active claim derives from a superseded claim |
| `therapy_without_indication` | warning | Active therapy has no matching active indication |
| `stale_hypothesis` | warning | Hypothesis supported only by superseded evidence |
| `contradictory_values` | error | Two evidence claims share ≥ 2 key terms with opposing high/low qualifiers |
| `temporal_inconsistency` | error | A derived claim's `time_offset` precedes its source |

Conflicts are tiered: `error` → `warning` → `info`. Each can be explained on demand
via the LLM.

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- OpenAI API key

### Run

```bash
cp .env.example .env
# Add your OPENAI_API_KEY to .env

docker compose up
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs
- Neo4j Browser: http://localhost:7474 (neo4j / alexiona123)

### Local Dev

**Backend:**
```bash
cd backend
pip install -r requirements.txt
NEO4J_URI=bolt://localhost:7687 OPENAI_API_KEY=sk-... uvicorn main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React 18, Cytoscape.js, Tailwind CSS |
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| LLM | OpenAI GPT-4o (structured JSON output) |
| Graph DB | Neo4j 5 (Docker) |
| PDF export | jsPDF |

---

## Design Principles

- **Epistemic claims, not assertions** — every node represents a supported claim, not a fact
- **Conflicts are first-class** — the system highlights what is in tension, not just what is known
- **LLM for language, rules for logic** — conflict detection, hypothesis scoring, and risk score computation are deterministic; the LLM handles extraction, explanation, and natural language — not the reasoning structure itself
- **Source authority matters** — guideline- and lab-system-sourced claims carry more weight than LLM inferences; this is explicit in the scoring formula
- **Temporal relevance** — evidence decays exponentially by claim type; old lab values down-weighted automatically
- **Role-appropriate information** — each clinical role receives a filtered view of the same graph; the nurse sees vitals, the chief sees risks, the specialist sees depth
- **Provenance over recency** — `derived_from` is explicit and user-confirmed, never auto-inferred from topical similarity
- **Support categories over percentages** — scores are surfaced as `low / moderate / strong`, not as probabilities that could be misread as diagnostic confidence
- **Hard stops over silent failure** — when evidence is insufficient for reliable prioritization, the system signals this explicitly rather than returning a low-confidence answer


---

## Screenshots

| Evidence Graph | Clinical Reasoning |
|---|---|
| ![Evidence graph with type-coloured nodes, derives_from edges and conflict banner](docs/screenshots/01_graph_view.png) | ![AI Reviewer panel: confidence gauge, supporting and conflicting evidence, missing evidence](docs/screenshots/07_reasoning_panel.png) |

| Evidence × Diagnosis Matrix | What-If? Evidence Counterfactual |
|---|---|
| ![Matrix view mapping each evidence node to hypotheses with supports/contradicts annotations](docs/screenshots/03_evidence_matrix.png) | ![Counterfactual panel: selecting D-Dimer shows before/after score shifts for each hypothesis](docs/screenshots/04_counterfactual.png) |

| Hypothesis Counterfactual | Clinical Handover (Übergabe) |
|---|---|
| ![Expanded "What would refute this?" panel showing required changes and decisive evidence](docs/screenshots/08_hypothesis_counterfactual.png) | ![Handover form auto-populated with Leitdiagnose, Befunde, Offene Diagnostik — PDF export](docs/screenshots/05_handover.png) |

| Evidence Timeline | |
|---|---|
| ![Timeline view showing claims distributed by time offset t+0h to t+5h](docs/screenshots/06_timeline.png) | |

---

## What it Does

Instead of storing clinical observations as flat text, AleXiona builds an explicit
**epistemic graph**: each piece of evidence is a typed, timestamped node that either
supports or contradicts a leading hypothesis. Conflicts between claims are detected by
a deterministic rule engine (not an LLM) and surfaced immediately. The graph can be
interrogated — "what changes if this finding were absent?" — via counterfactual
analysis, and exported as a structured handover document.

### Core Capabilities

| Capability | Description |
|---|---|
| **Claim extraction** | LLM converts free text into typed, scored evidence nodes |
| **Evidence graph** | Cytoscape.js force graph with provenance edges (`derives_from`, `possible_related`) |
| **Rule-based hypothesis scoring** | Weighted by source type (guideline ×2.0, lab_system ×1.5, llm ×0.5) and conflict severity (negation −2.0, quantitative clash −1.5) |
| **Conflict engine** | 8-rule deterministic detection: contradictory values, stale hypotheses, therapy without indication, temporal inconsistencies, and more |
| **Confidence hard-stop** | Score < 0.2 or ≥ 3 conflicting claims → ⚠ "Insufficient evidence for reliable prioritization" |
| **Explain leading** | Rule-based explanation of *why* the current hypothesis is leading: supporting texts, conflicting texts, key missing evidence |
| **Guideline layer** | Required-evidence terms for 5 diagnoses (pneumonia, PE, sepsis, MI, heart failure); used in missing-evidence detection |
| **Timeline** | Chronological view of all claims by time offset (`t+0h`, `t+6h`, …) |
| **Evidence counterfactual** | "What if this evidence were absent?" — per-node LLM analysis with hypothesis score shifts |
| **Hypothesis counterfactual** | "What would refute this hypothesis?" — shows required changes, decisive evidence, and which hypothesis would become leading |
| **Evidence-Impact Matrix** | Claim × hypothesis table annotating which evidence supports or contradicts each hypothesis |
| **Clinical handover** | Auto-populated, editable handover form (Leitdiagnose, Differentialdiagnose, Schlüsselbefunde, Offene Diagnostik, …) with PDF and clipboard export |
| **Conflict explanation** | On-demand LLM explanation for each detected conflict |

---

## Architecture

```
Clinician / Import
       │
       ▼
  Next.js 14 UI
  ├── Evidence Graph (Cytoscape.js)
  ├── Timeline Panel
  ├── Evidence-Impact Matrix
  ├── Evidence Counterfactual Panel
  ├── Hypothesis Counterfactual (inline in AI Reviewer)
  └── Clinical Handover (PDF export)
       │ HTTP / SSE
       ▼
  FastAPI Backend
  ├── LLM Client (OpenAI GPT-4o, structured JSON)
  │     ├── Claim extraction
  │     ├── Clinical reasoning summary
  │     ├── Evidence counterfactual analysis
  │     ├── Hypothesis counterfactual analysis
  │     └── Conflict explanation
  ├── Reasoning Engine (rule-based, deterministic)
  │     ├── Source-weighted hypothesis scoring
  │     │     (guideline ×2.0 / lab_system ×1.5 / clinician ×1.2 / llm ×0.5)
  │     ├── Typed conflict penalties
  │     │     (negation −2.0 / quantitative clash −1.5 / default −1.0)
  │     ├── explain_leading() — why this hypothesis is ranked first
  │     ├── Guideline layer — required evidence for known diagnoses
  │     ├── Hard stop — insufficient evidence signal
  │     └── Case snapshot — timestamped audit record
  ├── Conflict Engine (rule-based, deterministic)
  │     ├── competing_hypothesis
  │     ├── negation
  │     ├── evidence_mismatch
  │     ├── timeline_gap
  │     ├── therapy_without_indication
  │     ├── stale_hypothesis
  │     ├── contradictory_values
  │     └── temporal_inconsistency
  └── Neo4j 5
        ├── (:Claim) nodes — typed, timestamped, versioned
        ├── [:DERIVES_FROM] — explicit epistemic provenance (user-confirmed)
        └── [:POSSIBLE_RELATED] — heuristic similarity (not derivation)
```

---

## Graph Schema

```
(:Claim {
  id, text, session_id,
  claim_type,              // symptom | finding | lab | imaging | hypothesis |
                           // diagnosis | therapy | risk_factor | guideline
  source_type,             // clinician | llm | guideline | imaging_model |
                           //   lab_system | imported_document
  evidence_support_score,  // 0.0–1.0 internal support metric (NOT probability)
  status,                  // active | resolved | superseded
  time_offset,             // "t+0h", "t+6h", etc.
  trend,                   // improving | worsening | stable | unknown
  derived_from             // JSON list of source claim IDs (explicit only)
})

(:Entity { name })

(:Claim)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATION {type}]->(:Entity)
(:Claim)-[:DERIVES_FROM]->(:Claim)      // explicit epistemic derivation only
(:Claim)-[:POSSIBLE_RELATED]->(:Claim) // heuristic keyword overlap — NOT derivation
```

### Evidence Support Score

`evidence_support_score` is an **internal support metric** (0.0–1.0).
It is displayed as `low / moderate / strong` in the UI.
It is **not a diagnostic probability** and must not be interpreted as such.

### Derivation vs. Similarity

`DERIVES_FROM` is set only by explicit user action ("Add Evidence Node" dialog).
It means: *this claim is a direct logical/clinical consequence of the source*.

`POSSIBLE_RELATED` is a heuristic edge created automatically when two claims share
≥ 2 key medical terms. It indicates topical proximity, **not epistemic derivation**,
and appears as a dotted grey edge in the graph.

---

## Reasoning Engine

The reasoning engine scores hypotheses rule-based — no LLM involved.

### Hypothesis Score Formula

```
score(H) = Σ(ess_i × overlap_weight_i × source_weight_i)  for supporting evidence i
         − Σ(conflict_penalty_i)                           for conflicting evidence i
  clamped to [0.0, 1.0]
```

### Source Weights

| Source type | Weight | Rationale |
|---|---|---|
| `guideline` | ×2.0 | Clinical guideline — highest authority |
| `lab_system` | ×1.5 | Direct lab measurement — objective |
| `clinician` | ×1.2 | Direct observation |
| `imaging_model` | ×1.0 | Neutral |
| `imported_document` | ×1.0 | Neutral |
| `llm` | ×0.5 | LLM inference — down-weighted until confirmed |

### Conflict Penalties

| Contradiction type | Penalty | Trigger |
|---|---|---|
| Negation | −2.0 | "no fever", "ruled out", "kein …" |
| Quantitative clash | −1.5 | "CRP elevated" vs "CRP normal" |
| Generic overlap | −1.0 | Shared terms, no polarity signal |

### Hard Stop

When the top hypothesis has `score < 0.2` **or** `≥ 3 conflicting claims`, the engine returns:

```
⚠ Insufficient evidence for reliable prioritization
```

### Guideline Layer

Required evidence terms for five diagnoses:

| Diagnosis | Required |
|---|---|
| Pneumonia | fever, cough |
| Pulmonary embolism | dyspnea, tachycardia |
| Sepsis | fever, infection |
| Myocardial infarction | chest pain, troponin |
| Heart failure | dyspnea, edema |

---

## Conflict Engine

The conflict engine runs deterministically on the current claim set — no LLM involved.

| Rule | Severity | Trigger |
|---|---|---|
| `competing_hypothesis` | warning | ≥ 2 active diagnosis/hypothesis claims |
| `negation` | error | Two claims share ≥ 2 key terms; one negates the other |
| `evidence_mismatch` | info | Strong evidence (ess ≥ 0.85) exists but leading hypothesis has low support (ess < 0.4) |
| `timeline_gap` | warning | Active claim derives from a superseded claim |
| `therapy_without_indication` | warning | Active therapy has no matching active indication |
| `stale_hypothesis` | warning | Hypothesis supported only by superseded evidence |
| `contradictory_values` | error | Two evidence claims share ≥ 2 key terms with opposing high/low qualifiers |
| `temporal_inconsistency` | error | A derived claim's `time_offset` precedes its source |

Conflicts are tiered: `error` → `warning` → `info`. Each can be explained on demand
via the LLM.

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- OpenAI API key

### Run

```bash
cp .env.example .env
# Add your OPENAI_API_KEY to .env

docker compose up
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs
- Neo4j Browser: http://localhost:7474 (neo4j / alexiona123)

### Local Dev

**Backend:**
```bash
cd backend
pip install -r requirements.txt
NEO4J_URI=bolt://localhost:7687 OPENAI_API_KEY=sk-... uvicorn main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, React 18, Cytoscape.js, Tailwind CSS |
| Backend | Python 3.11, FastAPI, Pydantic v2 |
| LLM | OpenAI GPT-4o (structured JSON output) |
| Graph DB | Neo4j 5 (Docker) |
| PDF export | jsPDF |

---

## Design Principles

- **Epistemic claims, not assertions** — every node represents a supported claim, not a fact
- **Conflicts are first-class** — the system highlights what is in tension, not just what is known
- **LLM for language, rules for logic** — conflict detection and hypothesis scoring are deterministic; the LLM handles extraction, explanation, and natural language — not the reasoning structure itself
- **Source authority matters** — guideline- and lab-system-sourced claims carry more weight than LLM inferences; this is explicit in the scoring formula
- **Provenance over recency** — `derived_from` is explicit and user-confirmed, never auto-inferred from topical similarity
- **Support categories over percentages** — scores are surfaced as `low / moderate / strong`, not as probabilities that could be misread as diagnostic confidence
- **Hard stops over silent failure** — when evidence is insufficient for reliable prioritization, the system signals this explicitly rather than returning a low-confidence answer
