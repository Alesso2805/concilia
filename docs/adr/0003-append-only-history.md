# ADR-0003: Append-only history, `seq` ordering and computed state

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

Concilia's value is that every reconciliation decision can be traced: who created, confirmed, approved, rejected or reverted a match, who closed or reopened a period, and who accepted an AI suggestion. A status column that is updated in place loses that history, and an audit log kept beside it can drift from the status.

## Decision

**Append-only tables.** `matches`, `match_items`, `match_decisions`, `period_events`, `ai_suggestions`, `ai_suggestion_decisions` and `audit_events` only receive inserts. No role used by the API or the worker has `UPDATE` or `DELETE` on them; the catalog test enforces it. The only deletions are performed by the `SECURITY DEFINER` functions `app_reset_demo` and `app_cleanup`, which remove expired demo organizations as a whole.

**State is the latest event.** A match's state is the action of its latest `match_decisions` row (or "proposed" if it has none). A period's state is the action of its latest `period_events` row for `(bank_account_id, period)` (or "open" if it has none). Corrections are new events: a wrong approval is reverted, never edited.

**Ordering by `seq`, never by time.** Event tables have `seq bigint GENERATED ALWAYS AS IDENTITY`. Identity values are assigned at insert time, not at commit, so `seq` matches commit order only when writers do not interleave. Every write that creates match or period events takes the organization lock ([ADR-0002](0002-multi-tenancy-with-rls.md)), so within an organization they never interleave. Timestamps (`decided_at`, `created_at`, `at`) are informative, are set by the application from the injected `Clock`, and never decide order.

**Computed state through views.** Match state, the open and available balances of each receivable, and period state are read through views created with `security_invoker = true`. Supporting indexes: `match_decisions (match_id, seq)`, `match_items (receivable_id)` and `period_events (bank_account_id, period, seq)`.

**Rules enforced twice.** The domain validates every transition first. The database repeats the critical checks so that a bug or direct SQL cannot break them:

- a trigger on `match_decisions` validates the transition from the current state and the four-eyes rule (the decider is neither the creator nor the confirmer);
- `UNIQUE (match_id, action)` makes each action happen at most once per match;
- a trigger on `period_events` requires close and reopen to alternate;
- a constraint trigger, deferred to commit, requires every match to have at least one credit and one receivable.

Each of these rules has a domain test and a direct SQL test.

## Consequences

- The full history of every match and period is available without a separate audit mechanism, and the audit trail cannot disagree with the state.
- Reading state needs a join to the latest event. The indexes above and the p95 test in CN-13 keep this within budget.
- Mistakes are fixed with compensating events, which the UI must present clearly (for example, "reverted by ... because ...").
- Demo deletion needs owner-level functions, because no application role can delete history.

## Alternatives considered

- **Mutable status column plus an audit table.** Rejected: two sources of truth that can drift.
- **Full event sourcing with projections.** Rejected: rebuilding projections and versioning events is more machinery than the MVP needs; computed views give the same guarantees for this size.
- **Ordering by timestamp.** Rejected: clocks tie and skew, and the application sets the time, so it cannot define order.
