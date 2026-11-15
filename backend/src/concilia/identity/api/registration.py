from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field

from concilia.identity.application.registration import (
    EmailTakenError,
    PasswordTooShortError,
    Registration,
    RegistrationService,
)
from concilia.shared.kernel.ids import ClientIdError, IdConflictError


class RegistrationRequest(BaseModel):
    id: UUID
    organization_name: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(max_length=1024)


class RegistrationView(BaseModel):
    organization_id: UUID


def registration_router(service: RegistrationService, *, enabled: bool) -> APIRouter:
    router = APIRouter(prefix="/api/public", tags=["registration"])

    @router.post("/registrations", status_code=status.HTTP_201_CREATED)
    async def register(body: RegistrationRequest, response: Response) -> RegistrationView:
        """Create an organization and its first admin. Idempotent on the client-generated id."""
        if not enabled:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "registration_disabled")
        command = Registration(
            body.id, body.organization_name, body.display_name, body.email, body.password
        )
        try:
            organization_id, created = await service.register(command, source="registration")
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except PasswordTooShortError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "password_too_short"
            ) from None
        except EmailTakenError:
            raise HTTPException(status.HTTP_409_CONFLICT, "email_taken") from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return RegistrationView(organization_id=organization_id)

    return router
