# ADR-0001: Modular monolith with ordered modules and ports

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

Concilia is built by one developer with an AI pair, deployed on a single small server, and published as a portfolio project. It must show clean, verifiable boundaries without paying the operational cost of distributed services. Some work (parsing imports, running the engine, calling the AI provider, building exports, periodic cleanup) must not run inside HTTP requests.

## Decision

**One codebase, two processes.** The Python package `concilia` has two entry points that share code and the database:

- `concilia.api`: FastAPI served by Uvicorn. It validates, writes and enqueues jobs. It never runs background work: no tasks started in the lifespan and no `BackgroundTasks`.
- `concilia.worker`: runs queued jobs and the periodic task scheduler ([ADR-0005](0005-job-queue-in-postgresql.md)).

**Ordered modules.** The backend is split into modules with a fixed order. A module may import only modules that come before it:

| Order | Module |
| --- | --- |
| 0 | `shared.kernel` |
| 1 | `shared.infrastructure` |
| 2 | `audit` |
| 3 | `identity` |
| 4 | `banking` |
| 5 | `periods` |
| 6 | `imports` |
| 7 | `matching` |
| 8 | `ai` |
| 9 | `reporting` |
| 10 | `demo` |

`shared.kernel` is pure (no I/O, no third-party frameworks) and may be imported anywhere. `shared.infrastructure` (database session, access contexts, job queue, settings, logging) may be imported only by `infrastructure` and `api` layers and by the composition roots.

**Layers inside each business module.** Every module from `audit` to `demo` has four layers:

| Layer | May import |
| --- | --- |
| `domain` | `shared.kernel` and the standard library. Never FastAPI, SQLAlchemy, httpx or a provider SDK |
| `application` | its own `domain`, `shared.kernel`, and the `application` layer of earlier modules |
| `infrastructure` | its own `application` and `domain`, `shared.kernel`, `shared.infrastructure`, and the `application` layer of earlier modules |
| `api` | its own `application` and `domain`, `shared.kernel`, `shared.infrastructure` (session and access-context dependencies) |

A module talks to another module only through that module's `application` layer. The `api` layer never imports `infrastructure`; concrete adapters are wired in the composition roots `concilia/api.py` and `concilia/worker.py`, which are the only places allowed to import every module.

**Ports toward later modules.** When a module needs information owned by a later module, it declares a `typing.Protocol` port in its `application` layer, the later module implements it in its `infrastructure` layer, and the composition roots wire them. The MVP ports are:

- `periods.PendingMatchesQuery`, implemented by `matching`: are there proposed or confirmed matches in this period?
- `imports.ActiveMatchesQuery`, implemented by `matching`: are these movements or receivables in active or approved matches?

Until `matching` exists (CN-12), both are wired to a null adapter that answers "no matches".

**Enforcement.** import-linter contracts encode the module order, the layer rules and the forbidden imports of `domain`. They run in CI together with the architecture tests described in `docs/ARCHITECTURE_RULES.md` (CN-02), and each rule has a meta-test proving it detects a violation.

## Consequences

- Boundaries are checked on every pull request instead of relying on review.
- A module could later be extracted into a service by replacing its `application` interface with a client, because nothing reaches into its internals.
- Ports and null adapters add some boilerplate, and the composition roots grow with every module.
- Both processes ship in the same image and are versioned together, so a schema migration never has to support two code versions running different modules.

## Alternatives considered

- **Microservices per module.** Rejected: more deployments, network failure modes and cost than a one-server portfolio project can justify.
- **A layered monolith without modules** (`models/`, `services/`, `routers/`). Rejected: it hides the business boundaries the project wants to demonstrate and cannot express "matching may use imports, never the reverse".
- **A dependency-injection framework.** Rejected: constructor injection in two composition roots is enough and keeps the wiring readable.
