# ADR-0002: Multi-tenancy with PostgreSQL row-level security

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

Every organization's data lives in one PostgreSQL 17 database. A single missing `WHERE organization_id = ...` in application code must not be enough to leak data across organizations, and the public demo creates many organizations that strangers use at the same time.

## Decision

**Row-level security on every organization table.** Every table holding an organization's data has `organization_id`, `ENABLE` and `FORCE ROW LEVEL SECURITY`, and policies whose `USING` and `WITH CHECK` are:

```sql
organization_id = NULLIF(current_setting('app.org_id', true), '')::uuid
```

`organizations` applies the same expression to `id`. When `app.org_id` is unset or empty, the expression is null and no row is visible or writable.

**Closed list of tables without RLS:** `users`, `sessions`, `rate_limits` and Alembic's version table. The catalog test fails if any other table lacks forced RLS.

**`jobs` is the single exception to the uniform policy.** It has forced RLS, but with one policy per role: `concilia_app` sees and inserts only rows of `app.org_id`; `concilia_worker` sees and updates all rows, because it claims jobs of every organization and system jobs with a null `organization_id`. `docs/ARCHITECTURE_RULES.md` records this exception and the catalog test checks both policies (CN-02, CN-03).

**Cross-organization references are impossible by construction.** Each organization table has `UNIQUE (organization_id, id)`, and foreign keys between organization tables are composite `(organization_id, x_id)`. Users who create or decide something are referenced through `memberships (organization_id, user_id)`.

**Roles.** `concilia_owner` owns every object, runs migrations and has `BYPASSRLS`. `concilia_app` (API) and `concilia_worker` (worker) never own tables and never have `BYPASSRLS`. `concilia_backup` has `BYPASSRLS` and only `SELECT`. Grants follow the role table in SPEC exactly, are declared in `backend/tests/architecture/db_grants.yaml`, and the catalog test compares them with `table_privileges`, `column_privileges` and `routine_privileges`, including grants to `PUBLIC`.

**Access contexts.**

| Context | Routes or process | How `app.org_id` is set |
| --- | --- | --- |
| `anonymous` | `/api/public/*` | Not set. Only tables without RLS and `SECURITY DEFINER` functions are touched, except registration and demo creation, which set it to the newly generated organization id and create everything in one transaction |
| `org` | `/api/app/*` | The `current_org` dependency runs `SELECT set_config('app.org_id', :org_id, true)` with a bound parameter at the start of the request transaction |
| `system` | worker | A job of an organization sets it to the job's `organization_id`; periodic tasks use only `SECURITY DEFINER` functions |

The third argument `true` makes the setting transaction-local, so it never leaks to the next user of a pooled connection.

**Views** are always created `WITH (security_invoker = true)`, so the querying role's RLS applies to the underlying tables. The catalog test checks every view.

**`SECURITY DEFINER` functions** are owned by `concilia_owner`, declare `SET search_path = pg_catalog, public`, receive the current time as a parameter, and are created with `REVOKE ALL ON FUNCTION ... FROM PUBLIC`. The first migration runs `ALTER DEFAULT PRIVILEGES FOR ROLE concilia_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`.

**The organization lock.** Every operation that changes matches, receivable balances, imports or a period's state takes a transaction-scoped advisory lock before validating and writing:

```sql
SELECT pg_advisory_xact_lock(1, hashtext(:org_id::text));
```

Advisory locks use the two-key form with a fixed namespace in the first key, so locks of different kinds never collide:

| Namespace | Lock | Scope |
| --- | --- | --- |
| 1 | Organization | Transaction (`pg_advisory_xact_lock`) |
| 2 | Running job, held by the worker | Session, on the job's dedicated connection |
| 3 | Global AI quota (second key is always 0) | Transaction |

A hash collision inside a namespace only makes two unrelated organizations or jobs wait for each other; it never lets two operations on the same organization run concurrently. SQL functions that need the organization lock (`app_accept_invitation`, `app_reset_demo`) use the same expression.

## Consequences

- Isolation holds even if application code forgets a filter, and it covers raw SQL, views and the worker.
- Every request and job must run inside a transaction that sets `app.org_id`; code that forgets sees no rows, which fails loudly in tests instead of leaking.
- Every endpoint gets a test with two organizations, and the catalog test watches tables added by later stories.
- Policies add a predicate to every query, so indexes on organization tables lead with `organization_id`.
- Writes to an organization's guarded data are serialized. That is acceptable for the expected load and removes a class of race conditions from validation logic.

## Alternatives considered

- **Filtering only in application code.** Rejected: one missed filter leaks data, and nothing verifies it.
- **Schema per organization.** Rejected: migrations multiply with every demo, and demo cleanup becomes DDL.
- **Database per organization.** Rejected: incompatible with one small server and hundreds of short-lived demos.
- **Single-key advisory locks on a 64-bit hash of the id.** Rejected: the keys of organizations and jobs would share one space.
