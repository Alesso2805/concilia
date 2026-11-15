# Architecture Decision Records

Each ADR records one technical decision that the specification ([SPEC.md](../SPEC.md)) does not settle by itself, or explains how the specification is implemented. An ADR is accepted when its pull request is merged. A later ADR may supersede an earlier one; superseded ADRs are kept and marked as such.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Modular monolith with ordered modules and ports | Accepted |
| [0002](0002-multi-tenancy-with-rls.md) | Multi-tenancy with PostgreSQL row-level security | Accepted |
| [0003](0003-append-only-history.md) | Append-only history, `seq` ordering and computed state | Accepted |

New ADRs use the next free number and the sections of the existing ones: context, decision, consequences and alternatives considered.
