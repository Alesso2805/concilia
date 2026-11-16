# Architecture Decision Records

Each ADR records one technical decision that the specification ([SPEC.md](../SPEC.md)) does not settle by itself, or explains how the specification is implemented. An ADR is accepted when its pull request is merged. A later ADR may supersede an earlier one; superseded ADRs are kept and marked as such.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Modular monolith with ordered modules and ports | Accepted |
| [0002](0002-multi-tenancy-with-rls.md) | Multi-tenancy with PostgreSQL row-level security | Accepted |
| [0003](0003-append-only-history.md) | Append-only history, `seq` ordering and computed state | Accepted |
| [0004](0004-files-in-postgresql.md) | Uploaded files and exports stored in PostgreSQL | Accepted |
| [0005](0005-job-queue-in-postgresql.md) | Job queue and scheduler in PostgreSQL | Accepted |
| [0006](0006-ai-provider-and-llm-port.md) | AI provider, `LlmClient` port and usage limits | Accepted |
| [0007](0007-frontend-angular.md) | Frontend on Angular 22, zoneless, with a generated API client | Accepted |
| [0008](0008-sessions-csrf-local-https.md) | Cookie sessions, signed double-submit CSRF and local HTTPS | Accepted |
| [0009](0009-client-ids-and-idempotent-posts.md) | Client-generated ids and idempotent POST requests | Accepted |

New ADRs use the next free number and the sections of the existing ones: context, decision, consequences and alternatives considered.
