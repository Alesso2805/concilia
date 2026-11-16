from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid7

import httpx
import pytest
import time_machine
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.support.api import (
    Member,
    add_member,
    build_app,
    create_member,
    signed_in,
    xsrf_header,
)
from tests.support.clock import FixedClock
from tests.support.database import DatabaseUrls

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 23, 14, 0, tzinfo=UTC)
STATEMENT_CONFIG: dict[str, Any] = {
    "format": "csv",
    "delimiter": ";",
    "date_format": "DD/MM/YYYY",
    "decimal_separator": ",",
    "thousands_separator": ".",
    "columns": {"date": "Fecha", "description": "Detalle", "amount": "Importe"},
}
RECEIVABLES_CONFIG: dict[str, Any] = {
    "format": "xlsx",
    "date_format": "YYYY-MM-DD",
    "columns": {
        "customer_name": "Cliente",
        "doc_number": "Factura",
        "issued_on": "Emisión",
        "due_on": "Vence",
        "amount": "Total",
    },
}


def _client_id() -> str:
    with time_machine.travel(NOW, tick=False):
        return str(uuid7())


@pytest.fixture
async def app(database: DatabaseUrls) -> AsyncIterator[FastAPI]:
    app = build_app(database.for_role("concilia_app"), FixedClock(NOW))
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def admin(owner_engine: AsyncEngine) -> Member:
    return await create_member(owner_engine, NOW, organizations={"Andina": ["admin"]})


async def _post(client: httpx.AsyncClient, url: str, body: Any = None) -> httpx.Response:
    return await client.post(url, json=body, headers=xsrf_header(client))


async def _put(client: httpx.AsyncClient, url: str, body: Any) -> httpx.Response:
    return await client.put(url, json=body, headers=xsrf_header(client))


def _account(**changes: str) -> dict[str, str]:
    return {
        "id": _client_id(),
        "bank": "BCP",
        "alias": "Cuenta principal",
        "number_last4": "4521",
    } | (changes)


async def _actions(owner_engine: AsyncEngine, organization_id: UUID) -> list[tuple[str, Any]]:
    async with owner_engine.connect() as connection:
        rows = await connection.execute(
            text(
                """SELECT action, metadata FROM audit_events
                   WHERE organization_id = :org ORDER BY seq"""
            ),
            {"org": organization_id},
        )
        return [(row.action, dict(row.metadata)) for row in rows]


async def test_admins_register_accounts_idempotently_and_every_member_sees_them(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    analyst = await add_member(owner_engine, NOW, admin.organization_ids[0], ["analyst"])
    other = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    body = _account()
    async with signed_in(app, admin.email) as client:
        created = await _post(client, "/api/app/bank-accounts", body)
        replay = await _post(client, "/api/app/bank-accounts", body)
        changed = await _post(client, "/api/app/bank-accounts", {**body, "alias": "Otra"})
    async with signed_in(app, other.email) as client:
        elsewhere = await _post(client, "/api/app/bank-accounts", body)
        foreign = (await client.get("/api/app/bank-accounts")).json()
    async with signed_in(app, analyst.email) as client:
        listed = (await client.get("/api/app/bank-accounts")).json()
        forbidden = await _post(client, "/api/app/bank-accounts", _account())

    assert (created.status_code, replay.status_code) == (201, 200)
    assert created.json() | {"created_at": None} == {
        "id": body["id"],
        "bank": "BCP",
        "currency": "PEN",
        "alias": "Cuenta principal",
        "number_last4": "4521",
        "created_at": None,
        "archived_at": None,
    }
    assert (changed.status_code, elsewhere.status_code) == (409, 409)
    assert foreign == []
    assert [account["id"] for account in listed] == [body["id"]]
    assert (forbidden.status_code, forbidden.json()["detail"]) == (403, "role_required")
    assert await _actions(owner_engine, admin.organization_ids[0]) == [("bank_account.created", {})]


@pytest.mark.parametrize(
    ("changes", "detail"),
    [({"number_last4": "45a1"}, "invalid_last4"), ({"id": "0" * 32}, "id_not_uuid7")],
)
async def test_invalid_accounts_are_rejected(
    app: FastAPI, admin: Member, changes: dict[str, str], detail: str
) -> None:
    async with signed_in(app, admin.email) as client:
        response = await _post(client, "/api/app/bank-accounts", _account(**changes))

    assert (response.status_code, response.json()["detail"]) == (422, detail)


async def test_accounts_are_edited_and_archived_within_the_organization(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    other = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    body = _account()
    account_url = f"/api/app/bank-accounts/{body['id']}"
    edit = {"bank": "Interbank", "alias": "Recaudación", "number_last4": "0099"}
    async with signed_in(app, admin.email) as client:
        await _post(client, "/api/app/bank-accounts", body)
        async with signed_in(app, other.email) as stranger:
            foreign_edit = await _put(stranger, account_url, edit)
            foreign_archive = await _post(stranger, f"{account_url}/archive")
        edited = await _put(client, account_url, edit)
        archived = [await _post(client, f"{account_url}/archive") for _ in range(2)]
        after_archive = await _put(client, account_url, edit)
        listed = (await client.get("/api/app/bank-accounts")).json()

    assert (foreign_edit.status_code, foreign_archive.status_code) == (404, 404)
    assert edited.status_code == 204
    assert [response.status_code for response in archived] == [204, 204]
    assert (after_archive.status_code, after_archive.json()["detail"]) == (409, "archived")
    assert listed[0]["bank"] == "Interbank"
    assert listed[0]["archived_at"] is not None
    actions = [action for action, _ in await _actions(owner_engine, admin.organization_ids[0])]
    assert actions == ["bank_account.created", "bank_account.updated", "bank_account.archived"]


async def test_templates_are_offered_to_members(app: FastAPI, admin: Member) -> None:
    async with signed_in(app, admin.email) as client:
        templates = (await client.get("/api/app/import-templates")).json()

    assert [(t["key"], t["kind"]) for t in templates] == [
        ("bcp", "bank_statement"),
        ("interbank", "bank_statement"),
        ("bbva", "bank_statement"),
        ("receivables", "receivables"),
    ]
    assert templates[1]["config"]["columns"]["credit"] == "Abono"


async def test_profiles_are_created_from_a_config_and_tied_to_an_active_account(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    other = await create_member(owner_engine, NOW, organizations={"Beta": ["admin"]})
    account = _account()
    statement = {
        "id": _client_id(),
        "kind": "bank_statement",
        "bank_account_id": account["id"],
        "name": "BCP soles",
        "config": STATEMENT_CONFIG,
    }
    receivables = {
        "id": _client_id(),
        "kind": "receivables",
        "name": "Facturas",
        "config": RECEIVABLES_CONFIG,
    }
    async with signed_in(app, admin.email) as client:
        await _post(client, "/api/app/bank-accounts", account)
        created = await _post(client, "/api/app/import-profiles", statement)
        replay = await _post(client, "/api/app/import-profiles", statement)
        second = await _post(client, "/api/app/import-profiles", receivables)
        listed = (await client.get("/api/app/import-profiles")).json()
    async with signed_in(app, other.email) as client:
        foreign = await _post(client, "/api/app/import-profiles", {**statement, "id": _client_id()})

    assert (created.status_code, replay.status_code, second.status_code) == (201, 200, 201)
    assert created.json()["config"] == {
        **STATEMENT_CONFIG,
        "version": 1,
        "sheet": None,
        "encoding": "utf-8",
        "skip_rows": 0,
        "columns": {
            **STATEMENT_CONFIG["columns"],
            "operation_number": None,
            "debit": None,
            "credit": None,
        },
    }
    assert sorted(p["name"] for p in listed) == ["BCP soles", "Facturas"]
    assert (foreign.status_code, foreign.json()["detail"]) == (404, "not_found")
    assert ("import_profile.created", {"kind": "receivables"}) in await _actions(
        owner_engine, admin.organization_ids[0]
    )


async def test_an_invalid_config_is_rejected_without_echoing_it(
    app: FastAPI, admin: Member
) -> None:
    account = _account()
    columns = {
        "date": "Fecha",
        "description": "Detalle",
        "amount": "M",
        "debit": "C",
        "credit": "A",
    }
    async with signed_in(app, admin.email) as client:
        await _post(client, "/api/app/bank-accounts", account)
        response = await _post(
            client,
            "/api/app/import-profiles",
            {
                "id": _client_id(),
                "kind": "bank_statement",
                "bank_account_id": account["id"],
                "name": "Mal",
                "config": {**STATEMENT_CONFIG, "columns": columns},
            },
        )

    assert response.status_code == 422
    assert "Detalle" not in response.text


async def test_profiles_keep_their_kind_and_freeze_when_archived(
    app: FastAPI, admin: Member, owner_engine: AsyncEngine
) -> None:
    account = _account()
    profile_id = _client_id()
    url = f"/api/app/import-profiles/{profile_id}"
    async with signed_in(app, admin.email) as client:
        await _post(client, "/api/app/bank-accounts", account)
        await _post(
            client,
            "/api/app/import-profiles",
            {
                "id": profile_id,
                "kind": "bank_statement",
                "bank_account_id": account["id"],
                "name": "BCP",
                "config": STATEMENT_CONFIG,
            },
        )
        renamed = await _put(
            client,
            url,
            {"kind": "bank_statement", "name": "BCP soles", "config": STATEMENT_CONFIG},
        )
        other_kind = await _put(
            client, url, {"kind": "receivables", "name": "X", "config": RECEIVABLES_CONFIG}
        )
        await _post(client, f"{url}/archive")
        frozen = await _put(
            client, url, {"kind": "bank_statement", "name": "Otro", "config": STATEMENT_CONFIG}
        )
        await _post(client, f"/api/app/bank-accounts/{account['id']}/archive")
        on_archived = await _post(
            client,
            "/api/app/import-profiles",
            {
                "id": _client_id(),
                "kind": "bank_statement",
                "bank_account_id": account["id"],
                "name": "Nuevo",
                "config": STATEMENT_CONFIG,
            },
        )
        listed = (await client.get("/api/app/import-profiles")).json()

    assert renamed.status_code == 204
    assert (other_kind.status_code, other_kind.json()["detail"]) == (422, "kind_mismatch")
    assert (frozen.status_code, frozen.json()["detail"]) == (409, "archived")
    assert (on_archived.status_code, on_archived.json()["detail"]) == (409, "archived")
    assert [(p["name"], p["archived_at"] is not None) for p in listed] == [("BCP soles", True)]
