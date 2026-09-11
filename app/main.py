from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.routers import auth, executions, recipes, services, users


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()

    # Startup security validation for production mode
    if not settings.debug:
        insecure_secrets = {
            "change-me-in-production-secret-min-32-bytes",
            "change-me-in-production",
            "replace-with-a-long-random-secret",
            "",
        }
        if settings.jwt_secret in insecure_secrets or len(settings.jwt_secret) < 32:
            msg = (
                "FATAL SECURITY CONFIGURATION: Insecure or default JWT_SECRET detected in "
                "production! JWT_SECRET must be at least 32 characters long and not a default."
            )
            raise RuntimeError(msg)

    # Bootstrap initial admin if configured and not yet present
    if settings.initial_admin_email:
        admin_email = settings.initial_admin_email.strip().lower()
        if admin_email:
            try:
                from sqlalchemy import select

                from app.db import async_session_factory
                from app.models import User
                from app.models.enums import UserRole

                async with async_session_factory() as session:
                    existing = await session.scalar(
                        select(User).where(
                            (User.email == admin_email) | (User.username == admin_email)
                        )
                    )
                    if not existing:
                        admin_user = User(
                            username=admin_email,
                            email=admin_email,
                            role=UserRole.ADMIN,
                            password_hash=None,
                        )
                        session.add(admin_user)
                        await session.commit()
            except Exception:
                # If database tables are not yet created (e.g. before initial migration), ignore
                pass

    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        description="Deployment recipe orchestration platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.googleusercontent.com; "
            "frame-ancestors 'none';"
        )
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    application.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    application.include_router(auth.router)
    application.include_router(services.router)
    application.include_router(recipes.router)
    application.include_router(executions.router)
    application.include_router(users.router)

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
