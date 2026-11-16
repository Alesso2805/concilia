from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from concilia.shared.kernel.principal import Principal


def current_principal(request: Request) -> Principal:
    principal: Principal | None = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    return principal


def current_org(principal: Annotated[Principal, Depends(current_principal)]) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "organization_not_selected")
    return principal.organization_id


async def _validation_error(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise TypeError(type(error).__name__)
    details = [{"loc": list(item["loc"]), "type": item["type"]} for item in error.errors()]
    return JSONResponse({"detail": details}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
