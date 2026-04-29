# AleXiona – Claude Arbeitsregeln

## Deployment-Workflow

Nach jeder abgeschlossenen Änderung immer:
1. Commits auf den Feature-Branch pushen (`claude/...`)
2. PR auf GitHub erstellen (GitHub API oder `gh pr create`)
3. PR sofort mergen → `main` wird aktualisiert
4. Vercel deployed dann automatisch `ale-xiona.vercel.app`

**Nicht** stehen lassen auf dem Feature-Branch — die Production-URL zeigt immer auf `main`.

## Projekt

- Frontend: `frontend/` (Next.js 14, TypeScript)
- Backend: Python/FastAPI
- Production URL: `ale-xiona.vercel.app`
- GitHub: `hstre/AleXiona`
- Deploy-Branch: `main`
