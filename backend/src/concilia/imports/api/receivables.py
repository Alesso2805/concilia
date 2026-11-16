from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from concilia.imports.api.routes import HANDLED, http_error
from concilia.imports.application.service import ImportService
from concilia.imports.domain.model import Receivable
from concilia.shared.infrastructure.web import current_principal
from concilia.shared.kernel.cursor import InvalidCursorError, decode_date_cursor, encode_cursor
from concilia.shared.kernel.principal import Principal

CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class ReceivableView(BaseModel):
    id: UUID
    import_file_id: UUID
    customer_name: str
    customer_tax_id: str | None
    doc_number: str
    issued_on: date
    due_on: date
    amount_cents: int
    cancelled_at: datetime | None
    cancel_reason: str | None


class ReceivablePageView(BaseModel):
    receivables: list[ReceivableView]
    has_previous: bool
    has_next: bool
    previous_cursor: str | None
    next_cursor: str | None


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _view(receivable: Receivable) -> ReceivableView:
    return ReceivableView(
        id=receivable.id,
        import_file_id=receivable.import_file_id,
        customer_name=receivable.customer_name,
        customer_tax_id=receivable.customer_tax_id,
        doc_number=receivable.doc_number,
        issued_on=receivable.issued_on,
        due_on=receivable.due_on,
        amount_cents=receivable.amount_cents,
        cancelled_at=receivable.cancelled_at,
        cancel_reason=receivable.cancel_reason,
    )


def receivables_router(service: ImportService) -> APIRouter:
    router = APIRouter(prefix="/api/app/receivables", tags=["receivables"])

    @router.get("")
    async def list_receivables(
        principal: CurrentPrincipal,
        cancelled: bool = False,
        after: str | None = None,
        before: str | None = None,
        limit: Annotated[int, Query(gt=0, le=100)] = 20,
    ) -> ReceivablePageView:
        """Receivables by due date, oldest first, by keyset cursor (no total, no jump to the end).

        `cancelled=true` lists only cancelled receivables; otherwise only live ones.
        """
        try:
            page = await service.receivables(
                principal,
                cancelled=cancelled,
                after=decode_date_cursor(after) if after else None,
                before=decode_date_cursor(before) if before else None,
                limit=limit,
            )
        except InvalidCursorError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_cursor") from None
        except HANDLED as error:
            raise http_error(error) from None
        items = page.receivables
        return ReceivablePageView(
            receivables=[_view(item) for item in items],
            has_previous=page.has_previous,
            has_next=page.has_next,
            previous_cursor=encode_cursor(items[0].due_on, items[0].id) if items else None,
            next_cursor=encode_cursor(items[-1].due_on, items[-1].id) if items else None,
        )

    @router.post("/{receivable_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
    async def cancel_receivable(
        receivable_id: UUID, body: CancelRequest, principal: CurrentPrincipal
    ) -> None:
        """Cancel a receivable with a reason. Analysts only; repeating it changes nothing.

        Refused if the receivable is in a proposed or confirmed match; what is already approved
        stays applied.
        """
        try:
            await service.cancel_receivable(principal, receivable_id, body.reason)
        except HANDLED as error:
            raise http_error(error) from None

    return router
