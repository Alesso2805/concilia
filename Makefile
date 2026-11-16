.PHONY: up down trust-ca create-org demo lint test e2e openapi record-ai

CA_FILE := caddy-local-root.crt

up:
	docker compose up --build --detach

down:
	docker compose down

trust-ca:
	docker compose cp web:/data/caddy/pki/authorities/local/root.crt $(CA_FILE)
ifeq ($(OS),Windows_NT)
	certutil -user -addstore Root $(CA_FILE)
else ifeq ($(shell uname -s),Darwin)
	sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $(CA_FILE)
else
	sudo cp $(CA_FILE) /usr/local/share/ca-certificates/concilia-caddy-local.crt
	sudo update-ca-certificates
endif

lint:
	cd backend && uv run ruff format --check && uv run ruff check && uv run mypy && uv run lint-imports
	cd web && npm run lint && npm run typecheck

test:
	cd backend && uv run pytest
	cd web && npm run test:ci

e2e:
	cd web && npm run e2e

openapi:
	cd backend && uv run python -m concilia.openapi openapi.json
	cd web && npm run generate:api

demo:
	cd backend && uv run python -m webbrowser -t https://localhost/demo

create-org:
	docker compose run --rm migrator python -m concilia.cli create-org --name "$(NAME)" --email "$(EMAIL)" --display-name "$(DISPLAY_NAME)"

RECORDINGS := backend/src/concilia/ai/recordings/dataset_v1.json

record-ai:
	docker build -q -t concilia-backend:local ./backend
	docker compose run --rm -T -e OPENAI_API_KEY -e CONCILIA_AI_MODEL migrator python -m concilia.record_ai > $(RECORDINGS).tmp
	mv $(RECORDINGS).tmp $(RECORDINGS)
