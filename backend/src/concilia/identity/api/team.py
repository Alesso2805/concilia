from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from concilia.identity.api.sessions import LoginView, login_view
from concilia.identity.application.registration import PasswordTooShortError
from concilia.identity.application.sessions import IssuedSession, SessionService
from concilia.identity.application.team import (
    AlreadyMemberError,
    InvitationAlreadyAcceptedError,
    InvitationNotValidError,
    InviteCommand,
    NewAccount,
    NotAdminError,
    NotFoundError,
    TeamService,
)
from concilia.identity.domain.team import (
    InvalidEmailError,
    Invitation,
    LastAdminError,
    NoRolesError,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

type RoleName = Literal["admin", "analyst", "reviewer"]
Roles = Annotated[list[RoleName], Field(min_length=1, max_length=3)]
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

ERRORS: dict[type[Exception], tuple[int, str]] = {
    NotAdminError: (status.HTTP_403_FORBIDDEN, "role_required"),
    NotFoundError: (status.HTTP_404_NOT_FOUND, "not_found"),
    AlreadyMemberError: (status.HTTP_409_CONFLICT, "already_member"),
    IdConflictError: (status.HTTP_409_CONFLICT, "id_conflict"),
    LastAdminError: (status.HTTP_409_CONFLICT, "last_admin"),
    InvitationAlreadyAcceptedError: (status.HTTP_409_CONFLICT, "invitation_accepted"),
    InvitationNotValidError: (status.HTTP_409_CONFLICT, "invitation_not_valid"),
    InvalidEmailError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_email"),
    NoRolesError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "roles_required"),
    PasswordTooShortError: (status.HTTP_422_UNPROCESSABLE_CONTENT, "password_too_short"),
}


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, ClientIdError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code)
    code, detail = ERRORS[type(error)]
    return HTTPException(code, detail)


HANDLED: tuple[type[Exception], ...] = (ClientIdError, *ERRORS)


class MemberView(BaseModel):
    user_id: UUID
    display_name: str
    email: str
    roles: list[RoleName]
    joined_at: datetime


class InvitationView(BaseModel):
    id: UUID
    email: str
    roles: list[RoleName]
    created_at: datetime
    expires_at: datetime


class TeamView(BaseModel):
    members: list[MemberView]
    invitations: list[InvitationView]


class InviteRequest(BaseModel):
    id: UUID
    email: str = Field(min_length=3, max_length=320)
    roles: Roles


class CreatedInvitationView(BaseModel):
    invitation: InvitationView
    token: str | None


class RolesRequest(BaseModel):
    roles: Roles


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class AcceptedInvitationView(BaseModel):
    organization_id: UUID


class NewAccountRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(max_length=1024)


def _invitation_view(invitation: Invitation) -> InvitationView:
    return InvitationView(
        id=invitation.id,
        email=invitation.email,
        roles=sorted(role.value for role in invitation.roles),
        created_at=invitation.created_at,
        expires_at=invitation.expires_at,
    )


def team_routers(
    service: TeamService,
    sessions: SessionService,
    set_session_cookies: Callable[[Response, IssuedSession], None],
) -> tuple[APIRouter, APIRouter]:
    app = APIRouter(prefix="/api/app", tags=["team"])
    public = APIRouter(prefix="/api/public", tags=["team"])

    @app.get("/team")
    async def get_team(principal: CurrentPrincipal) -> TeamView:
        """List the active members and pending invitations. Admins only."""
        try:
            overview = await service.overview(principal)
        except HANDLED as error:
            raise _http_error(error) from None
        return TeamView(
            members=[
                MemberView(
                    user_id=member.user_id,
                    display_name=member.display_name,
                    email=member.email,
                    roles=sorted(role.value for role in member.roles),
                    joined_at=member.joined_at,
                )
                for member in overview.members
            ],
            invitations=[_invitation_view(invitation) for invitation in overview.invitations],
        )

    @app.post("/invitations", status_code=status.HTTP_201_CREATED)
    async def create_invitation(
        body: InviteRequest, principal: CurrentPrincipal, response: Response
    ) -> CreatedInvitationView:
        """Invite someone by email. The token is returned only when the invitation is created.

        Idempotent on the client-generated id.
        """
        try:
            issued = await service.invite(
                principal, InviteCommand(body.id, body.email, frozenset(body.roles))
            )
        except HANDLED as error:
            raise _http_error(error) from None
        if not issued.created:
            response.status_code = status.HTTP_200_OK
        return CreatedInvitationView(
            invitation=_invitation_view(issued.invitation), token=issued.token
        )

    @app.post("/invitations/{invitation_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
    async def revoke_invitation(invitation_id: UUID, principal: CurrentPrincipal) -> None:
        """Revoke a pending invitation. Admins only."""
        try:
            await service.revoke(principal, invitation_id)
        except HANDLED as error:
            raise _http_error(error) from None

    @app.put("/team/members/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
    async def set_member_roles(
        user_id: UUID, body: RolesRequest, principal: CurrentPrincipal
    ) -> None:
        """Replace the roles of a member. The organization always keeps an admin."""
        try:
            await service.set_roles(principal, user_id, body.roles)
        except HANDLED as error:
            raise _http_error(error) from None

    @app.post("/team/members/{user_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_member(user_id: UUID, principal: CurrentPrincipal) -> None:
        """Remove a member, drop their roles and end their sessions in this organization."""
        try:
            await service.remove(principal, user_id)
        except HANDLED as error:
            raise _http_error(error) from None

    @app.post("/invitations/accept")
    async def accept_invitation(
        body: AcceptInvitationRequest, principal: CurrentPrincipal
    ) -> AcceptedInvitationView:
        """Accept an invitation addressed to the signed-in user's email."""
        try:
            organization_id = await service.accept_as_member(principal, body.token)
        except HANDLED as error:
            raise _http_error(error) from None
        return AcceptedInvitationView(organization_id=organization_id)

    @public.post("/invitations/accept")
    async def accept_invitation_with_new_account(
        body: NewAccountRequest, response: Response
    ) -> LoginView:
        """Create an account for the invited email, accept the invitation and sign in.

        Any reason the invitation cannot be used, including an email that already has an
        account, gives the same answer.
        """
        account = NewAccount(body.token, body.email, body.display_name, body.password)
        try:
            user = await service.accept_as_new_user(account)
        except HANDLED as error:
            raise _http_error(error) from None
        issued = await sessions.start(user.id)
        set_session_cookies(response, issued)
        return login_view(issued)

    return app, public
