.PHONY: lint test

lint:
	cd backend && uv run ruff format --check && uv run ruff check && uv run mypy

test:
	cd backend && uv run pytest
