.PHONY: up down trust-ca create-org lint test e2e openapi

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

create-org:
	docker compose run --rm migrator python -m concilia.cli create-org --name "$(NAME)" --email "$(EMAIL)" --display-name "$(DISPLAY_NAME)"
