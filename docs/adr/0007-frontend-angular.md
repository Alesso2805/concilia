# ADR-0007: Frontend on Angular 22, zoneless, with a generated API client

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

The frontend must show modern Angular (standalone components, signals, native control flow, no zone.js), stay in sync with the API contract, render paginated tables over large data, show accessible charts, and run under a strict Content Security Policy. Versions must be pinned to a combination that every tool in the chain supports.

## Decision

**Versions, verified against npm, nodejs.org and each package's peer dependencies on 2026-11-15:**

| Piece | Version | Why |
| --- | --- | --- |
| Angular (`@angular/*`) | 22.x (22.2.6) | Current major. No 23 prerelease exists yet, so it will not change during the first sprints |
| Angular Material and CDK | 22.x (22.2.7) | Peer range `^22 \|\| ^23` |
| TypeScript | 6.0.x | `@angular/compiler-cli` 22 requires `>=6.0 <6.1`; TypeScript 7 is released but not supported |
| Node.js | 26 (Active LTS since 2026-10-28) | Angular 22 supports `>=26.0.0`. Node 24 entered maintenance on 2026-10-20 |
| ng-openapi-gen | 1.1.x | Supports Angular 16+ and OpenAPI 3.1, which FastAPI emits |
| angular-eslint | 22.x | Matches the Angular major |
| Unit tests | Vitest through `@angular/build:unit-test` | The Angular 22 CLI default (peer `vitest ^4.0.8 \|\| ^5`) |
| End-to-end | Playwright 1.65 and `@axe-core/playwright` 4.14 | From CN-06 |
| Charts | Apache ECharts 6 with ngx-echarts 22 | See below |

The Node version is pinned in `.nvmrc` and read by CI (CN-02). Angular majors are upgraded with `ng update` in a dedicated pull request, once Material, ng-openapi-gen, angular-eslint and ngx-echarts support the new major.

**Application style.**

- Zoneless change detection, which is the CLI default in Angular 22. An architecture rule fails if `zone.js` appears in `package.json` or in any polyfill (CN-02).
- Standalone components with `OnPush`, signals for screen state, `@if`/`@for`, typed reactive forms. RxJS only for real asynchronous streams: HTTP, job polling, debounced search.
- TypeScript `strict` and Angular `strictTemplates`.
- One folder per feature under `src/app/features/`, each with lazy routes and one service that wraps the generated API functions. Shell, interceptors and guards live in `src/app/core/`.

**Generated API client.** ng-openapi-gen generates functional API calls (no `NgModule`) into `src/app/api/` from the backend's OpenAPI document. That folder is never edited by hand. CI regenerates it and fails if the result differs from what is committed (CN-02).

**Tables.** `mat-table` with `mat-paginator` and server-side keyset pagination:

- previous and next only, with no total and no jump to the last page;
- the cursor is the active sort value plus the row id, opaque to the client;
- the cursor resets when filters or tabs change;
- no virtual scroll.

The paginator gets a custom `MatPaginatorIntl` and is driven by the `has_next` and `has_previous` flags returned by the API.

**Charts: Apache ECharts with ngx-echarts.**

- SVG renderer, with the `aria` option on, so each chart gets a generated text description and decal patterns, and color is never the only cue.
- Every chart has a "Ver como tabla" toggle that shows the same data in a table, so all of it is reachable by keyboard and screen readers.
- Only the chart types used are imported from `echarts/core`, and charts load only inside the lazy `reports` feature.

**Content Security Policy**, set by Caddy:

```text
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:;
font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self';
frame-ancestors 'none'
```

- The production build sets `optimization.styles.inlineCritical: false`. Critical-CSS inlining loads the remaining styles through an `onload` attribute, which `script-src 'self'` blocks.
- `index.html` contains no inline scripts, so no hashes or nonces are needed, and Angular's `autoCsp` is not used.
- `style-src 'unsafe-inline'` is the accepted exception for styles that Angular and Material inject at runtime.
- Fonts and Material Symbols are installed as npm packages and served by the app, never from Google Fonts.
- CN-06 verifies the policy against the running app: a header test, plus a Playwright check that fails on any CSP violation while visiting every route.

**Other browser-side choices.** Client-generated ids ([ADR-0009](0009-client-ids-and-idempotent-posts.md)) use `v7()` from the `uuid` package (14.x). The theme is Material 3 with light and dark variants.

## Consequences

- The stack is on current majors with a verified compatible set. TypeScript stays one major behind its latest release until Angular supports 7.
- Zoneless plus `OnPush` makes change detection explicit through signals. Code that mutates state outside signals will not refresh the view, and reviews must catch it.
- The API contract cannot drift silently from the frontend.
- Turning off critical-CSS inlining costs a little first-paint performance in exchange for a CSP without exceptions for scripts.
- ECharts is the largest dependency of the app; lazy loading keeps it out of every route except reports.

## Alternatives considered

- **Angular 21 (LTS).** Rejected: 22 is the active major and avoids an upgrade early in the project.
- **Node 24.** Rejected: it is in maintenance; the rule is to use the active LTS that Angular supports.
- **Chart.js.** Rejected: canvas output exposes no structure to assistive technology without extra work.
- **Highcharts.** Rejected: its accessibility module is strong, but its license is restrictive for anything beyond personal use.
- **Hand-drawn SVG charts.** Rejected: the project calls for an accessible chart library, and ECharts covers future charts without new code.
- **Karma for unit tests.** Rejected: Vitest is the CLI default and the supported path forward.
- **Angular `autoCsp` with hashes.** Rejected: it is unnecessary when the page has no inline scripts.
