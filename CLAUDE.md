# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What AleXiona is

A clinical reasoning infrastructure demonstrator. AleXiona turns unstructured clinical
input into a versioned **evidence graph**: every claim is a typed, timestamped node that
supports or contradicts a hypothesis, carries explicit provenance, and can be challenged
by counterfactual analysis. It is a reasoning *aid*, **not a diagnostic system** — all
conclusions require verification by a qualified clinician.

The guiding architectural rule: **LLM for language, rules for logic.** Conflict detection,
hypothesis scoring, orchestration, and risk-score computation are deterministic; the LLM
only handles claim extraction, explanation, and document generation. When changing
reasoning behaviour, keep this boundary — do not move scoring/orchestration logic into an
LLM call.

## Deployment-Workflow (verbindlich)

Nach jeder abgeschlossenen Änderung immer:
1. Commits auf den Feature-Branch pushen (`claude/...`)
2. PR auf GitHub erstellen (GitHub API oder `gh pr create`)
3. PR sofort mergen → `main` wird aktualisiert
4. Vercel deployed dann automatisch `ale-xiona.vercel.app`

**Nicht** stehen lassen auf dem Feature-Branch — die Production-URL zeigt immer auf `main`.

## Commands

All common tasks run from the repo root via the `Makefile`:

```bash
make install        # backend (requirements-dev.txt) + frontend (npm ci)
make test           # backend pytest + frontend vitest
make test-backend   # cd backend && python -m pytest --tb=short -q
make test-frontend  # cd frontend && npm run test
make lint           # cd backend && python -m ruff check .
make typecheck      # cd frontend && npx tsc --noEmit
```

Run a single backend test: `cd backend && python -m pytest tests/test_reasoning_engine.py::test_name -q`
Run frontend tests in watch mode: `cd frontend && npm run test:watch`

CI (`.github/workflows/ci.yml`) runs on every branch and mirrors the above: backend =
ruff + pytest; frontend = `tsc --noEmit` + vitest + `next build`. Match all of these
before pushing — `next build` is part of CI even though it is not a `make` target.

### Running locally

- `docker compose up` — full stack (Neo4j 5.15 + backend + frontend). Frontend on :3000,
  backend on :8000 (`/docs`), Neo4j Browser on :7474 (`neo4j` / `alexiona123`).
- `./start.sh` — runs Neo4j in Docker but backend + frontend on the host (uvicorn `--reload`
  + `next dev`). Requires `.env` with an LLM key.
- Backend alone: `cd backend && pip install -r requirements.txt && NEO4J_URI=bolt://localhost:7687 DEEPSEEK_API_KEY=sk-... uvicorn main:app --reload`
- Frontend alone: `cd frontend && npm install && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev`

### Configuration

- Set **one** LLM key in `.env` (see `.env.example`). `DEEPSEEK_API_KEY` takes priority
  over `OPENAI_API_KEY`; the client is OpenAI-compatible and selects model `deepseek-chat`
  or `gpt-4o` accordingly (`backend/llm_client.py`).
- Neo4j connection: `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` (defaults
  `bolt://localhost:7687` / `neo4j` / `alexiona123`).
- Frontend talks to the backend via `NEXT_PUBLIC_API_URL`.
- Deploy stack: Neo4j Aura Free + Render (backend, `render.yaml`, health check `/health`) +
  Vercel (frontend, root directory `frontend/`).

## Architecture

### Backend (`backend/`, Python 3.11 / FastAPI / Pydantic v2)

`main.py` mounts six routers (all under `/api/...`):

| Router | Prefix | Responsibility |
|---|---|---|
| `chat.py` | `/api/chat` | LLM claim extraction; `POST ""` and SSE `POST /stream` |
| `graph.py` | `/api/graph` | The bulk of the API — graph CRUD, orchestrate, reasoning/explain, risk-scores, role views, conflicts, counterfactuals, MED, report, export/import, entity dedup |
| `sessions.py` | `/api/sessions` | List / delete sessions |
| `intake.py` | `/api/intake` | Patient-data ingestion |
| `demo.py` | `/api/demo` | Seed demo scenarios (`cap` / `pe` / `ards` / `nstemi`) |
| `audit.py` | `/api/audit` | Read the append-only audit log |

Note: the README documents endpoints as `/{session_id}/...` — the actual full path is
`/api/graph/{session_id}/...`.

The reasoning stack is a layered pipeline of deterministic engines feeding one orchestrator:

- **`clinical_orchestrator.py`** — the "Dirigent". Deterministic, **no LLM**. Merges five
  sub-engine signals into one authoritative state (`confident` / `undecided` / `contested`
  / `insufficient`) with a German verdict and one next action. Weights:
  evidence 40% / guideline 25% / composite 15% / temporal 10% / conflict −10%.
- **`reasoning_engine.py`** — rule-based hypothesis scoring:
  `score(H) = Σ(ess × overlap × source_weight × temporal_weight) − Σ(conflict_penalty) + composite_boost`,
  composite boost bounded at +0.08, clamped to [0,1]. Source weights (guideline ×2.0,
  lab_system ×1.5, clinician ×1.2, llm ×0.5, …) and temporal half-lives live here. Also
  produces the per-claim contribution breakdown and the 5-factor priority decomposition.
- **`composite_scores.py`** — six validated bedside scores (qSOFA, Wells-PE, GRACE-ACS,
  HEART, PERC, CURB-65) computed from the claim graph.
- **`conflict_engine.py`** — 8 deterministic conflict rules (negation, contradictory_values,
  stale_hypothesis, therapy_without_indication, temporal_inconsistency, …).
- **`role_views.py`** — filters the same graph into nurse / resident / specialist / lab /
  chief views (accepts German role aliases).
- **`med_engine.py`** — Minimal Evidence to Decision: which single test would most change
  the ranking.

The **SPL (Semantic Projection Layer)** is the mandatory primary path for every
LLM-extracted claim:
- `spl.py` is ported **verbatim** from the upstream Alexandria-Semantic-Projection-Layer
  repo — treat it as vendored; do not refactor it casually.
- `clinical_spl.py` adapts SPL to AleXiona's `Claim` model. Emission rules: E1 (ESS ≥ 0.90,
  high-confidence) / E2 (0.62–0.90) / E3 (< 0.62 → tentative) / E0 (structural → blocked) /
  E4 (JSD > 0.40 → two tentative claims). Clinician direct entries are `MANUAL` overrides,
  exempt from SPL — not a shortcut around it.

Claim extraction is a 5-stage pipeline: LLM (`llm_client.py`) → normalise → Pydantic
validation (`models.py`) → SPL → persist (`neo4j_client.py`). `patient_data.py` enforces
the epistemic contract that patient-generated inputs never become clinical-grade evidence
directly. Every claim mutation writes an `AuditEvent` (`audit_log.py`), and API errors go
through `api_errors.py` to return structured `{code, message}` detail dicts.

Persistence is **Neo4j 5** (`neo4j_client.py`, single shared driver closed on shutdown):
`(:Claim)` nodes with `[:DERIVES_FROM]` (explicit, user-confirmed provenance) and
`[:POSSIBLE_RELATED]` (heuristic similarity — **not** derivation). Provenance is never
auto-inferred from topical similarity.

### Frontend (`frontend/src/`, Next.js 14 / React 18 / Tailwind)

- `app/page.tsx` is the single-page shell; `lib/api.ts` is the **typed boundary** to the
  backend — all fetch calls, enums, and interfaces live there. Keep `ClaimType` /
  `SourceType` / `ConflictType` etc. in sync with `backend/models.py`.
- `components/` are panels matching backend capabilities: `OrchestratorPanel` (default view),
  `GraphView` (Cytoscape.js), `TimelinePanel`, `EvidenceMatrix`, `CounterfactualPanel`,
  `ReviewPanel`, `HandoverPanel`, `ReportPanel` (jsPDF export), plus modals for add/import/dedup.
- Tests are Vitest + happy-dom, colocated under `__tests__/`.

## Conventions

- Ruff config in `backend/pyproject.toml` (`E,F,I,UP,B,SIM`, line length 100). Mypy expects
  typed defs but is non-strict. Several rules are intentionally ignored (e.g. `E402` because
  `load_dotenv()` must run before importing modules that read env vars — preserve this import
  ordering in `main.py`).
- `evidence_support_score` is an internal support metric in [0,1], **not a probability** —
  do not present it as diagnostic certainty.
- German is a first-class output language (verdicts, role aliases, report types like
  Arztbrief / Entlassbrief / Konsiliarbrief / Befundbericht). Preserve German strings.
</content>
</invoke>
