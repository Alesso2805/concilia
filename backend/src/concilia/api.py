from typing import Literal

from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app() -> FastAPI:
    app = FastAPI(
        title="Concilia API",
        version="0.1.0",
        openapi_url="/api/openapi.json",
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=_operation_id,
    )

    @app.get("/api/health", tags=["health"])
    async def get_health() -> HealthResponse:
        """Report that the API process is up."""
        return HealthResponse(status="ok")

    return app


app = create_app()
