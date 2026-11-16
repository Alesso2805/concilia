.PHONY: lint test

lint:
	cd backend && uv run ruff format --check && uv run ruff check && uv run mypy && uv run lint-imports

test:
	cd backend && uv run pytest
