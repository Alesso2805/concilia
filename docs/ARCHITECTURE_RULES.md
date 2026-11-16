# Architecture rules

Every rule has an ID, a statement, the reason it exists, and the automated check that enforces it in CI. Every check also has a meta-test that feeds it a deliberate violation and asserts that the check catches it, so a rule cannot silently stop working. A pull request with a red architecture check is not merged.

A rule changes only together with its check, its meta-test and, when the architecture changes, the ADR that motivates it.

| ID | Rule | Check |
| --- | --- | --- |
| AR-01 | Modules import only earlier modules; nothing imports a composition root | import-linter |
| AR-02 | Layers inside each business module point inward | import-linter |
| AR-03 | The pure core imports only the standard library and the kernel | AST test |
| AR-04 | Other modules are reached only through their `application` layer | AST test |
| AR-05 | Only the clock implementation reads the wall clock, in Python or SQL | AST test |
| AR-06 | Money and scores are never floats | AST test |
| AR-07 | The API process never runs background work | AST test |
| AR-08 | Logs carry only allowlisted fields and literal event names | AST test and logging tests |
| AR-09 | The frontend runs without zone.js | Project file test |

Checks live in `backend/.importlinter` (contracts) and `backend/tests/architecture/` (AST tests and every meta-test). The import-linter contracts run in CI as `lint-imports`, and their meta-tests copy the package to a temporary directory, add one violating module, and assert that the named contract breaks.

## AR-01 Module order

Modules are ordered as in [ADR-0001](adr/0001-modular-monolith.md): `shared.kernel`, `shared.infrastructure`, `audit`, `identity`, `banking`, `periods`, `imports`, `matching`, `ai`, `reporting`, `demo`. A module may import only modules that come before it. No module imports the composition roots `concilia.api` or `concilia.worker`.

**Why:** dependencies flow one way, so a module can be understood, tested and changed without the ones after it. When an earlier module needs a later one, it declares a port (ADR-0001).

**Check:** contracts `AR-01 Modules import only earlier modules` (layers) and `AR-01 No module imports a composition root` (forbidden).

## AR-02 Layers inside each business module

In every business module, `domain` imports no other layer, `application` imports only `domain`, and `api` and `infrastructure` may import `application` and `domain` but never each other.

**Why:** the domain stays independent of frameworks and storage, and adapters are wired only in the composition roots.

**Check:** contract `AR-02 Layers inside each business module` (layers with containers, `api | infrastructure` as independent siblings).

## AR-03 Pure core

Files in `shared.kernel` and in any `domain` layer import only the standard library, `concilia.shared.kernel`, their own module's `domain`, and the pure computation libraries in an explicit allowlist (today: `rapidfuzz`).

**Why:** the reconciliation engine must be a pure, deterministic function (project rule 6), and the domain never touches FastAPI, SQLAlchemy, httpx, provider SDKs or Pydantic.

**Check:** `pure_core_imports` in `tests/architecture/rules.py`.

## AR-04 Access through the application layer

A module reaches another business module only through `concilia.<module>.application`. Importing a module's package root, `domain`, `infrastructure` or `api` from another module is a violation. `domain` and `application` layers never import `concilia.shared.infrastructure`. The composition roots are exempt.

**Why:** each module's `application` layer is its public interface; everything else may change without notice.

**Check:** `cross_module_access`.

## AR-05 Injected time only

Only `concilia.shared.infrastructure.clock` may call `datetime.now`, `datetime.utcnow`, `datetime.today`, `date.today` or `time.time`, directly or through an import alias. No Python string in the source or in migrations may contain SQL that reads the clock (`now()`, `CURRENT_DATE`, `CURRENT_TIMESTAMP`, `LOCALTIMESTAMP`, `clock_timestamp`, `statement_timestamp`, `transaction_timestamp`).

**Why:** project rule 2. Business time comes from the injected `Clock` and is passed to SQL as a parameter, so tests can control it and month-end, year-end and leap-day cases are reproducible.

**Check:** `no_wall_clock`.

## AR-06 No floats for money

In the pure core (`shared.kernel` and every `domain` layer), there are no float literals, no use of `float`, and no true division (`/`); integer division and explicit rounding are used instead. Everywhere else, no variable, attribute, parameter or function whose name refers to money or scores (`cents`, `amount`, `balance`, `applied`, `difference`, `tolerance`, `detraction`, `score`) is typed as `float`.

**Why:** project rule 1. Amounts are integer cents and scores are integers from 0 to 100; a float anywhere in that path produces rounding errors that reconciliation cannot tolerate.

**Check:** `no_float_money`.

## AR-07 No background work in the API process

Nothing imports FastAPI's or Starlette's `BackgroundTasks` or `BackgroundTask`. The composition root `concilia.api` and every `api` layer never spawn tasks (`create_task`, `ensure_future`, `TaskGroup`), including in the lifespan.

**Why:** background work belongs to the worker and its durable queue ([ADR-0005](adr/0005-job-queue-in-postgresql.md)). A task started inside the API is lost on restart and escapes retries, idempotency and monitoring.

**Check:** `no_background_tasks`.

## AR-08 Logs without customer data

All logging goes through structlog, configured in `concilia.shared.infrastructure.logging`, which is the only module that imports the standard `logging` package. That configuration also routes third-party loggers (Uvicorn, SQLAlchemy) through the same processors. Two processors run on every record:

- Keep only the fields in `ALLOWED_FIELDS` (identifiers, codes, counts, timings). Every other field is dropped, and only its name is recorded in `dropped_fields`.
- Replace any exception with its type and its frames (`file:line in function`). Exception messages, stack text and local values are never written.

Event names are string literals. A call on a logger (`log.info(...)`, `logger.bind(...).error(...)`) must not use an f-string, a variable, or formatting arguments as its event, because the event text bypasses the field allowlist.

**Why:** project rule 12. Logs and errors never contain customer names, descriptions, references, amounts, prompts or AI responses.

**Check:**

- `log_events_are_literals` enforces literal events and the single `logging` import.
- `tests/unit/shared/test_logging.py` covers dropped fields, exceptions and third-party loggers, plus a Hypothesis property: no field outside the allowlist ever reaches the output.

## AR-09 Zoneless frontend

`web/package.json` does not depend on `zone.js`. `web/angular.json` does not reference it in any polyfill or option. No TypeScript file under `web/src` imports `zone.js` or calls `provideZoneChangeDetection`.

**Why:** the frontend uses zoneless change detection driven by signals ([ADR-0007](adr/0007-frontend-angular.md)). Adding zone.js back would silently hide missing signal updates.

**Check:** `zoneless_frontend` in `tests/architecture/test_frontend_rules.py`, which reads the real project files and has meta-tests for each of the four ways zone.js could return.

## Rules still to come

- Database catalog rules (CN-03): forced RLS on every organization table, the closed list of tables without RLS, the per-role policies of `jobs` (the single exception to the uniform policy, [ADR-0002](adr/0002-multi-tenancy-with-rls.md)), `security_invoker` views, and grants that match `db_grants.yaml` exactly.
