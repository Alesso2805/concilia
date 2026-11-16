from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, StringConstraints

from concilia.banking.application.profile_config import (
    ProfileConfig,
    ReceivablesConfig,
    StatementConfig,
    parse_config,
)
from concilia.banking.application.service import (
    AccountCommand,
    ArchivedError,
    BankingService,
    KindMismatchError,
    NotAdminError,
    NotFoundError,
    ProfileCommand,
)
from concilia.banking.domain.model import (
    BankAccount,
    ImportProfile,
    InvalidLast4Error,
    ProfileKind,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

ERRORS: dict[type[Exception], tuple[int, str]] = {
    NotAdminError: (status.HTTP_403_FORBIDDEN, "role_required"),
    NotFoundError: (status.HTTP_404_NOT_FOUND, "not_found"),
    ArchivedError: (status.HTTP_409_CONFLICT, "archived"),
    IdConflictError: (status.HTTP_409_CONFLICT, "id_conflict"),
    InvalidLast4Error: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_last4"),
    KindMismatchError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "kind_mismatch"),
}
HANDLED: tuple[type[Exception], ...] = (ClientIdError, *ERRORS)


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ClientIdError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code)
    code, detail = ERRORS[type(error)]
    return HTTPException(code, detail)


class AccountRequest(BaseModel):
    bank: Annotated[Text, Field(max_length=60)]
    alias: Annotated[Text, Field(max_length=80)]
    number_last4: str = Field(min_length=4, max_length=4)


class CreateAccountRequest(AccountRequest):
    id: UUID


class BankAccountView(BaseModel):
    id: UUID
    bank: str
    currency: Literal["PEN"]
    alias: str
    number_last4: str
    created_at: datetime
    archived_at: datetime | None


class StatementProfileRequest(BaseModel):
    kind: Literal["bank_statement"]
    name: Annotated[Text, Field(max_length=80)]
    config: StatementConfig


class ReceivablesProfileRequest(BaseModel):
    kind: Literal["receivables"]
    name: Annotated[Text, Field(max_length=80)]
    config: ReceivablesConfig


class CreateStatementProfileRequest(StatementProfileRequest):
    id: UUID
    bank_account_id: UUID


class CreateReceivablesProfileRequest(ReceivablesProfileRequest):
    id: UUID


ProfileRequest = Annotated[
    StatementProfileRequest | ReceivablesProfileRequest, Field(discriminator="kind")
]
CreateProfileRequest = Annotated[
    CreateStatementProfileRequest | CreateReceivablesProfileRequest, Field(discriminator="kind")
]


class StatementProfileView(BaseModel):
    id: UUID
    kind: Literal["bank_statement"]
    bank_account_id: UUID
    name: str
    config: StatementConfig
    created_at: datetime
    archived_at: datetime | None


class ReceivablesProfileView(BaseModel):
    id: UUID
    kind: Literal["receivables"]
    name: str
    config: ReceivablesConfig
    created_at: datetime
    archived_at: datetime | None


ProfileView = Annotated[StatementProfileView | ReceivablesProfileView, Field(discriminator="kind")]


class StatementTemplateView(BaseModel):
    key: str
    name: str
    bank: str
    kind: Literal["bank_statement"]
    config: StatementConfig


class ReceivablesTemplateView(BaseModel):
    key: str
    name: str
    kind: Literal["receivables"]
    config: ReceivablesConfig


TemplateView = Annotated[
    StatementTemplateView | ReceivablesTemplateView, Field(discriminator="kind")
]


def _account_view(account: BankAccount) -> BankAccountView:
    return BankAccountView(
        id=account.id,
        bank=account.bank,
        currency="PEN",
        alias=account.alias,
        number_last4=account.number_last4,
        created_at=account.created_at,
        archived_at=account.archived_at,
    )


def _profile_view(profile: ImportProfile) -> StatementProfileView | ReceivablesProfileView:
    config = parse_config(profile.kind, profile.config)
    if isinstance(config, StatementConfig) and profile.bank_account_id is not None:
        return StatementProfileView(
            id=profile.id,
            kind="bank_statement",
            bank_account_id=profile.bank_account_id,
            name=profile.name,
            config=config,
            created_at=profile.created_at,
            archived_at=profile.archived_at,
        )
    if isinstance(config, ReceivablesConfig):
        return ReceivablesProfileView(
            id=profile.id,
            kind="receivables",
            name=profile.name,
            config=config,
            created_at=profile.created_at,
            archived_at=profile.archived_at,
        )
    raise TypeError(profile.kind)


def banking_router(service: BankingService) -> APIRouter:
    router = APIRouter(prefix="/api/app", tags=["banking"])

    @router.get("/bank-accounts")
    async def list_bank_accounts(principal: CurrentPrincipal) -> list[BankAccountView]:
        """List the organization's bank accounts, archived ones included."""
        try:
            return [_account_view(a) for a in await service.accounts(principal)]
        except HANDLED as error:
            raise _http_error(error) from None

    @router.post("/bank-accounts", status_code=status.HTTP_201_CREATED)
    async def create_bank_account(
        body: CreateAccountRequest, principal: CurrentPrincipal, response: Response
    ) -> BankAccountView:
        """Register a PEN bank account. Admins only; idempotent on the client-generated id."""
        command = AccountCommand(body.bank, body.alias, body.number_last4)
        try:
            account, created = await service.create_account(principal, body.id, command)
        except HANDLED as error:
            raise _http_error(error) from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _account_view(account)

    @router.put("/bank-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def update_bank_account(
        account_id: UUID, body: AccountRequest, principal: CurrentPrincipal
    ) -> None:
        """Change the bank, alias or last four digits of an active account. Admins only."""
        command = AccountCommand(body.bank, body.alias, body.number_last4)
        try:
            await service.update_account(principal, account_id, command)
        except HANDLED as error:
            raise _http_error(error) from None

    @router.post("/bank-accounts/{account_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
    async def archive_bank_account(account_id: UUID, principal: CurrentPrincipal) -> None:
        """Archive an account so it takes no new imports. Admins only."""
        try:
            await service.archive_account(principal, account_id)
        except HANDLED as error:
            raise _http_error(error) from None

    @router.get("/import-templates")
    async def list_import_templates(principal: CurrentPrincipal) -> list[TemplateView]:
        """Example profiles to copy. Bank layouts must be checked against a real file."""
        views: list[StatementTemplateView | ReceivablesTemplateView] = []
        for template in service.templates():
            if isinstance(template.config, StatementConfig) and template.bank is not None:
                views.append(
                    StatementTemplateView(
                        key=template.key,
                        name=template.name,
                        bank=template.bank,
                        kind="bank_statement",
                        config=template.config,
                    )
                )
            elif isinstance(template.config, ReceivablesConfig):
                views.append(
                    ReceivablesTemplateView(
                        key=template.key,
                        name=template.name,
                        kind="receivables",
                        config=template.config,
                    )
                )
        return views

    @router.get("/import-profiles")
    async def list_import_profiles(principal: CurrentPrincipal) -> list[ProfileView]:
        """List the organization's import profiles, archived ones included."""
        try:
            return [_profile_view(p) for p in await service.profiles(principal)]
        except HANDLED as error:
            raise _http_error(error) from None

    @router.post("/import-profiles", status_code=status.HTTP_201_CREATED)
    async def create_import_profile(
        body: CreateProfileRequest, principal: CurrentPrincipal, response: Response
    ) -> ProfileView:
        """Create an import profile. Admins only; idempotent on the client-generated id."""
        account_id = getattr(body, "bank_account_id", None)
        command = ProfileCommand(ProfileKind(body.kind), body.name, body.config, account_id)
        try:
            profile, created = await service.create_profile(principal, body.id, command)
        except HANDLED as error:
            raise _http_error(error) from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return _profile_view(profile)

    @router.put("/import-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def update_import_profile(
        profile_id: UUID, body: ProfileRequest, principal: CurrentPrincipal
    ) -> None:
        """Rename an active profile or change its file layout. Admins only."""
        config: ProfileConfig = body.config
        try:
            await service.update_profile(principal, profile_id, body.name, config)
        except HANDLED as error:
            raise _http_error(error) from None

    @router.post("/import-profiles/{profile_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
    async def archive_import_profile(profile_id: UUID, principal: CurrentPrincipal) -> None:
        """Archive a profile so it is no longer offered for imports. Admins only."""
        try:
            await service.archive_profile(principal, profile_id)
        except HANDLED as error:
            raise _http_error(error) from None

    return router
