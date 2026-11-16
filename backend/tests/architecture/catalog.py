from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

GRANTS_FILE = Path(__file__).with_name("db_grants.yaml")
OWNER = "concilia_owner"
CHECKED_GRANTEES = frozenset({"PUBLIC", "concilia_app", "concilia_worker", "concilia_backup"})
EXPECTED_ROLES = {
    "concilia_owner": True,
    "concilia_app": False,
    "concilia_worker": False,
    "concilia_backup": True,
}
TENANT = "(NULLIF(current_setting('app.org_id'::text, true), ''::text))::uuid"
SECURITY_DEFINER_SEARCH_PATH = "search_path=pg_catalog, public"

type Grant = tuple[str, str, str]
type ColumnGrant = tuple[str, str, str, str]


def load_expected() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(GRANTS_FILE.read_text(encoding="utf-8"))
    return loaded


def _grantee(column: str) -> str:
    return f"CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END AS {column}"


async def _rows(connection: AsyncConnection, sql: str) -> list[Any]:
    return list((await connection.execute(text(sql))).all())


async def _role_violations(connection: AsyncConnection) -> list[str]:
    rows = await _rows(
        connection,
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE 'concilia\\_%'",
    )
    actual = {row.rolname: row for row in rows}
    violations = [f"role {name} is missing" for name in EXPECTED_ROLES if name not in actual]
    for name, row in actual.items():
        if row.rolsuper:
            violations.append(f"role {name} is a superuser")
        if name in EXPECTED_ROLES and row.rolbypassrls != EXPECTED_ROLES[name]:
            violations.append(f"role {name} has BYPASSRLS={row.rolbypassrls}")
    return violations


async def _relation_violations(connection: AsyncConnection, tables: Mapping[str, Any]) -> list[str]:
    rows = await _rows(
        connection,
        """
        SELECT c.relname, c.relkind::text AS relkind, c.relrowsecurity, c.relforcerowsecurity,
               pg_get_userbyid(c.relowner) AS owner, c.reloptions
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
        """,
    )
    violations = [
        f"{name} is declared but does not exist"
        for name in tables.keys() - {r.relname for r in rows}
    ]
    for row in rows:
        if row.relname not in tables:
            violations.append(f"{row.relname} is not declared in db_grants.yaml")
            continue
        if row.owner != OWNER:
            violations.append(f"{row.relname} is owned by {row.owner}")
        if row.relkind in ("v", "m"):
            options = row.reloptions or []
            if not {"security_invoker=true", "security_invoker=on"} & set(options):
                violations.append(f"view {row.relname} lacks security_invoker")
            continue
        wants_rls = tables[row.relname]["rls"] != "none"
        if (row.relrowsecurity, row.relforcerowsecurity) != (wants_rls, wants_rls):
            violations.append(
                f"{row.relname} has RLS={row.relrowsecurity} FORCE={row.relforcerowsecurity}"
            )
    return violations


def _expected_policies(kind: str) -> set[tuple[str, str, str]]:
    tenant = f"(organization_id = {TENANT})"
    match kind:
        case "organization":
            return {("public", tenant, tenant)}
        case "organization_root":
            return {("public", f"(id = {TENANT})", f"(id = {TENANT})")}
        case "jobs":
            return {("concilia_app", tenant, tenant), ("concilia_worker", "true", "true")}
        case _:
            return set()


async def _policy_violations(connection: AsyncConnection, tables: Mapping[str, Any]) -> list[str]:
    rows = await _rows(
        connection,
        """
        SELECT tablename, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = 'public'
        """,
    )
    actual: dict[str, set[tuple[str, str, str]]] = {}
    for row in rows:
        if row.cmd != "ALL":
            actual.setdefault(row.tablename, set()).add((f"cmd {row.cmd}", "", ""))
        actual.setdefault(row.tablename, set()).add((",".join(row.roles), row.qual, row.with_check))
    return [
        f"{name} policies {sorted(actual.get(name, set()))} != {sorted(expected)}"
        for name, spec in tables.items()
        if actual.get(name, set()) != (expected := _expected_policies(spec["rls"]))
    ]


async def _privilege_violations(
    connection: AsyncConnection, tables: Mapping[str, Any]
) -> list[str]:
    table_rows = await _rows(
        connection,
        f"""
        SELECT c.relname, {_grantee("grantee")}, a.privilege_type
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm')
        """,
    )
    column_rows = await _rows(
        connection,
        f"""
        SELECT c.relname, att.attname, {_grantee("grantee")}, a.privilege_type
        FROM pg_attribute att
        JOIN pg_class c ON c.oid = att.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        CROSS JOIN LATERAL aclexplode(att.attacl) a
        WHERE n.nspname = 'public' AND att.attnum > 0 AND NOT att.attisdropped
        """,
    )
    actual: set[Grant] = {
        (r.relname, r.grantee, r.privilege_type)
        for r in table_rows
        if r.grantee in CHECKED_GRANTEES
    }
    actual_columns: set[ColumnGrant] = {
        (r.relname, r.attname, r.grantee, r.privilege_type)
        for r in column_rows
        if r.grantee in CHECKED_GRANTEES
    }
    expected: set[Grant] = {
        (table, grantee, privilege)
        for table, spec in tables.items()
        for grantee, privileges in spec.get("privileges", {}).items()
        for privilege in privileges
    }
    expected_columns: set[ColumnGrant] = {
        (table, column, grantee, privilege)
        for table, spec in tables.items()
        for grantee, by_privilege in spec.get("column_privileges", {}).items()
        for privilege, columns in by_privilege.items()
        for column in columns
    }
    return (
        [f"unexpected grant {grant}" for grant in sorted(actual - expected)]
        + [f"missing grant {grant}" for grant in sorted(expected - actual)]
        + [
            f"unexpected column grant {grant}"
            for grant in sorted(actual_columns - expected_columns)
        ]
        + [f"missing column grant {grant}" for grant in sorted(expected_columns - actual_columns)]
    )


async def _function_violations(
    connection: AsyncConnection, functions: Mapping[str, Any]
) -> list[str]:
    rows = await _rows(
        connection,
        f"""
        SELECT p.proname, p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) AS owner,
               {_grantee("grantee")}, a.privilege_type
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        CROSS JOIN LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
        WHERE n.nspname = 'public'
        """,
    )
    names = {row.proname for row in rows}
    violations = [
        f"function {name} is declared but does not exist" for name in functions.keys() - names
    ]
    executors: dict[str, set[str]] = {name: set() for name in names}
    for row in rows:
        if row.proname not in functions:
            violations.append(f"function {row.proname} is not declared in db_grants.yaml")
            continue
        spec = functions[row.proname]
        if row.owner != OWNER:
            violations.append(f"function {row.proname} is owned by {row.owner}")
        if row.prosecdef != spec["security_definer"]:
            violations.append(f"function {row.proname} has SECURITY DEFINER={row.prosecdef}")
        if row.prosecdef and SECURITY_DEFINER_SEARCH_PATH not in (row.proconfig or []):
            violations.append(f"function {row.proname} does not pin its search_path")
        if row.grantee in CHECKED_GRANTEES and row.privilege_type == "EXECUTE":
            executors[row.proname].add(row.grantee)
    violations += [
        f"function {name} is executable by {sorted(executors[name])}"
        for name, spec in functions.items()
        if name in executors and executors[name] != set(spec["execute"])
    ]
    return sorted(set(violations))


async def catalog_violations(connection: AsyncConnection, expected: Mapping[str, Any]) -> list[str]:
    return [
        *await _role_violations(connection),
        *await _relation_violations(connection, expected["tables"]),
        *await _policy_violations(connection, expected["tables"]),
        *await _privilege_violations(connection, expected["tables"]),
        *await _function_violations(connection, expected["functions"]),
    ]
