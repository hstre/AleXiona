.PHONY: help test test-backend test-frontend lint typecheck install smoke

help:
	@echo "AleXiona – available targets:"
	@echo "  make install        Install all backend + frontend dependencies"
	@echo "  make test           Run all tests (backend + frontend)"
	@echo "  make test-backend   Run Python test suite only"
	@echo "  make test-frontend  Run Vitest suite only"
	@echo "  make lint           Ruff lint check (backend)"
	@echo "  make typecheck      TypeScript type check (frontend)"
	@echo "  make smoke          Smoke-test against a running stack (BACKEND_URL / FRONTEND_URL)"

install:
	pip install -r backend/requirements-dev.txt
	cd frontend && npm ci

test: test-backend test-frontend

test-backend:
	cd backend && python -m pytest --tb=short -q

test-frontend:
	cd frontend && npm run test

lint:
	cd backend && python -m ruff check .

typecheck:
	cd frontend && npx tsc --noEmit

smoke:
	python scripts/smoke.py
