.PHONY: lint test openapi

lint:
	cd backend && uv run ruff format --check && uv run ruff check && uv run mypy && uv run lint-imports
	cd web && npm run lint && npm run typecheck

test:
	cd backend && uv run pytest
	cd web && npm run test:ci

openapi:
	cd backend && uv run python -m concilia.openapi openapi.json
	cd web && npm run generate:api
