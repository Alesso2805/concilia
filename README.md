# Concilia

Bank reconciliation backoffice: it matches bank statement credits against expected receivables, with two-step (maker-checker) approval, an append-only history, and an AI assistant that suggests but never decides.

Status: work in progress (Sprint 0). The product specification ([docs/SPEC.md](docs/SPEC.md)) and backlog ([docs/BACKLOG.md](docs/BACKLOG.md)) are written in Spanish; architecture decision records, architecture rules and this README are in English.

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
