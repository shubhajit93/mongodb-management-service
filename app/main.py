"""FastAPI application entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.deps import build_container
from app.api.response import fail
from app.api.routers import router
from app.config import Settings, get_settings
from app.domain.errors import DomainError

logger = logging.getLogger("mongodb_management")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="ASAT MongoDB Management API",
        description=(
            "Private control plane on the database host. "
            "Starts backup and restore by calling the installed shell scripts. "
            "Does not replace mongodump, mongorestore, or the systemd timer."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.container = build_container(settings=settings)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=fail(exc.message))

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(status_code=exc.status_code, content=fail(detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", []) if part != "body")
            messages.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
        return JSONResponse(status_code=422, content=fail("; ".join(messages) or "Validation failed"))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", exc_info=exc)
        return JSONResponse(status_code=500, content=fail("Internal server error"))

    app.include_router(router)

    @app.get("/")
    def root():
        return {
            "success": True,
            "message": "ASAT MongoDB Management API",
            "data": {"docs": "/docs", "health": "/api/v1/health"},
        }

    return app


app = create_app


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.bind_port,
        reload=False,
    )


if __name__ == "__main__":
    run()