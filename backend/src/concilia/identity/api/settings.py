from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from concilia.identity.application.settings import SettingsAccessError, SettingsService
from concilia.identity.domain.settings import (
    BASIS_POINTS,
    MAX_DETRACTION_RATES,
    MAX_TOLERANCE_MIN_CENTS,
    InvalidSettingsError,
    OrganizationSettings,
)
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class OrganizationSettingsView(BaseModel):
    name: str
    tolerance_min_cents: int
    tolerance_bp: int
    detraction_rates_bp: list[int]


class OrganizationSettingsRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tolerance_min_cents: int = Field(ge=0, le=MAX_TOLERANCE_MIN_CENTS)
    tolerance_bp: int = Field(ge=0, le=BASIS_POINTS)
    detraction_rates_bp: list[Annotated[int, Field(gt=0, le=BASIS_POINTS)]] = Field(
        max_length=MAX_DETRACTION_RATES
    )


def settings_router(service: SettingsService) -> APIRouter:
    router = APIRouter(prefix="/api/app", tags=["organization"])

    @router.get("/organization")
    async def get_organization_settings(principal: CurrentPrincipal) -> OrganizationSettingsView:
        """Name, difference tolerance and detraction rates used by the matching engine."""
        try:
            settings = await service.get(principal)
        except SettingsAccessError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        return OrganizationSettingsView(
            name=settings.name,
            tolerance_min_cents=settings.tolerance_min_cents,
            tolerance_bp=settings.tolerance_bp,
            detraction_rates_bp=list(settings.detraction_rates_bp),
        )

    @router.put("/organization", status_code=status.HTTP_204_NO_CONTENT)
    async def update_organization_settings(
        body: OrganizationSettingsRequest, principal: CurrentPrincipal
    ) -> None:
        """Change the organization settings. Admins only.

        Amounts are in cents and rates in basis points.
        """
        try:
            settings = OrganizationSettings(
                body.name,
                body.tolerance_min_cents,
                body.tolerance_bp,
                tuple(body.detraction_rates_bp),
            )
            await service.update(principal, settings)
        except SettingsAccessError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        except InvalidSettingsError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_settings") from None

    return router
