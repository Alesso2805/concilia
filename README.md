# Concilia

Bank reconciliation backoffice: it matches bank statement credits against expected receivables, with two-step (maker-checker) approval, an append-only history, and an AI assistant that suggests but never decides.

Status: work in progress (Sprint 0). The product specification ([docs/SPEC.md](docs/SPEC.md)) and backlog ([docs/BACKLOG.md](docs/BACKLOG.md)) are written in Spanish; architecture decision records, architecture rules and this README are in English.

## Run it locally

Requires Docker with Compose and GNU Make.

```sh
make up        # builds and starts PostgreSQL, migrations, API, worker and Caddy
```

Open <https://localhost>. Caddy serves the app over HTTPS with its own local certificate authority, so that `__Host-` cookies and the Content Security Policy behave exactly as in production.

**One-time step:** your browser does not trust that authority yet. After the first `make up`, run:

```sh
make trust-ca  # copies Caddy's root certificate and adds it to your OS trust store
```

It uses `certutil` on Windows (a confirmation dialog appears), `security` on macOS and `update-ca-certificates` on Debian-based Linux. Until you run it, everything works, but the browser shows a certificate warning. The certificate lives in the `caddy_data` volume; if you delete that volume, run `make trust-ca` again.

`make down` stops everything and keeps the data. Local passwords have development defaults in `docker-compose.yml`; any real deployment must override them with environment variables (`POSTGRES_PASSWORD`, `CONCILIA_OWNER_PASSWORD`, `CONCILIA_APP_PASSWORD`, `CONCILIA_WORKER_PASSWORD`, `CONCILIA_BACKUP_PASSWORD`).

## Development

Prerequisites: [uv](https://docs.astral.sh/uv/) (it installs Python 3.14), Node.js at the version in [`.nvmrc`](.nvmrc) (for example with [fnm](https://github.com/Schniz/fnm)), and GNU Make.

```sh
cd web && npm ci && cd ..
make lint      # Ruff, Mypy, import-linter, ESLint and TypeScript
make test      # Pytest (including architecture rules) and Vitest
make openapi   # regenerate backend/openapi.json and the Angular API client
```

Architecture rules and how they are enforced: [docs/ARCHITECTURE_RULES.md](docs/ARCHITECTURE_RULES.md).

## License

[MIT](LICENSE)
