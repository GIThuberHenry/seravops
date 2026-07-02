from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.routers import auth, executions, recipes, services


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        description="Deployment recipe orchestration platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    application.include_router(auth.router)
    application.include_router(services.router)
    application.include_router(recipes.router)
    application.include_router(executions.router)

    @application.exception_handler(HTTPException)
    async def authentication_redirect(request: Request, exc: HTTPException) -> Response:
        if (
            exc.status_code == status.HTTP_401_UNAUTHORIZED
            and "text/html" in request.headers.get("accept", "")
            and request.url.path != "/login"
        ):
            return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        return await http_exception_handler(request, exc)

    @application.get("/", include_in_schema=False)
    async def index() -> RedirectResponse:
        return RedirectResponse("/services")

    @application.get("/health", tags=["health"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return application


app = create_app()
