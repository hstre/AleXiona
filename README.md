# AleXiona V0 – Knowledge Graph Demonstrator

Turn text into structured, persistent knowledge graphs via LLM dialog.

## Architecture

```
User → Chat UI → FastAPI Backend → GPT-4o (claim extraction)
                                 ↓
                            Neo4j Graph
                                 ↑
                     Graph Query / Retrieval → Grounded Response
```

## Stack

- **Frontend**: Next.js 14, Cytoscape.js, Tailwind CSS
- **Backend**: Python FastAPI
- **LLM**: OpenAI GPT-4o (structured JSON output)
- **Database**: Neo4j 5 (Docker)

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
- Backend API: http://localhost:8000
- Neo4j Browser: http://localhost:7474 (user: neo4j, pass: alexiona123)

### Local Dev (without Docker)

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

## How it Works

1. User enters text or asks a question
2. Backend sends text to GPT-4o with structured JSON prompt
3. Claims, entities, and relations are extracted
4. Data is stored in Neo4j as a labeled property graph
5. Graph is visualized in real time with Cytoscape.js
6. Follow-up questions are answered using graph context (grounded responses)

## Graph Schema

```
(:Claim {id, text, session_id})
(:Entity {name})
(:Claim)-[:MENTIONS]->(:Entity)
(:Entity)-[:RELATION {type}]->(:Entity)
```

## V0 Scope

- Single-user sessions (session ID stored in localStorage)
- Claim editing and deletion via graph node click
- Grounded Q&A using stored claims as context
