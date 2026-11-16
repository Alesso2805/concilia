from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from concilia.matching.application.manual import (
    ManualApplication,
    ManualMatch,
    ManualMatchService,
)
from concilia.matching.application.runs import NotAllowedError, NotFoundError
from concilia.matching.domain.decisions import DecisionError
from concilia.matching.domain.model import DifferenceReason
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.ids import ClientIdError, IdConflictError
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
UNPROCESSABLE = {"invalid_match", "difference_reason", "reason_required"}


class ApplicationBody(BaseModel):
    receivable_id: UUID
    applied_cents: int = Field(gt=0)


class ManualMatchRequest(BaseModel):
    id: UUID
    bank_account_id: UUID
    credit_ids: list[UUID] = Field(min_length=1, max_length=49)
    applications: list[ApplicationBody] = Field(min_length=1, max_length=49)
    difference_reason: Literal["commission", "detraction", "rounding", "overpayment", "other"] | (
        None
    ) = None
    difference_note: str | None = Field(default=None, max_length=500)


class ManualMatchView(BaseModel):
    id: UUID
    status: Literal["confirmed"]


def manual_router(service: ManualMatchService) -> APIRouter:
    router = APIRouter(prefix="/api/app/matches", tags=["inbox"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_manual_match(
        body: ManualMatchRequest, principal: CurrentPrincipal, response: Response
    ) -> ManualMatchView:
        """Reconcile by hand: free credits of one account against receivables with available
        balance, each with its applied amount (less than the balance leaves it partially paid).
        The analyst who creates it confirms it at once, so another person approves it.

        Idempotent on the client-generated id. Errors: 403 `role_required`; 404 for unknown
        credits or receivables; 409 `credit_not_free`, `insufficient_balance` or `closed_period`;
        422 `invalid_match` or `difference_reason`.
        """
        match = ManualMatch(
            tuple(body.credit_ids),
            tuple(ManualApplication(a.receivable_id, a.applied_cents) for a in body.applications),
        )
        try:
            stored, created = await service.create(
                principal,
                body.id,
                body.bank_account_id,
                match,
                difference_reason=(
                    DifferenceReason(body.difference_reason) if body.difference_reason else None
                ),
                difference_note=body.difference_note,
            )
        except DecisionError as error:
            code = (
                status.HTTP_422_UNPROCESSABLE_CONTENT
                if error.code in UNPROCESSABLE
                else status.HTTP_403_FORBIDDEN
                if error.code == "role_required"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(code, error.code) from None
        except NotAllowedError:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "role_required") from None
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
        except ClientIdError as error:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, error.code) from None
        except IdConflictError:
            raise HTTPException(status.HTTP_409_CONFLICT, "id_conflict") from None
        if not created:
            response.status_code = status.HTTP_200_OK
        return ManualMatchView(id=stored.id, status="confirmed")

    return router
