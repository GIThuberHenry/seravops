from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.rate_limit import check_auth_rate_limit
from app.core.security import get_client_ip, is_ip_allowed
from app.db import get_db
from app.schemas.auth import Token
from app.services import auth_service, google_auth_service

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str | None = None) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": error,
            "google_enabled": google_auth_service.is_google_auth_configured(),
            "enable_local_auth": settings.enable_local_auth,
        },
    )


@router.get("/login/google", dependencies=[Depends(check_auth_rate_limit)])
async def login_google(request: Request) -> RedirectResponse:
    if not google_auth_service.is_google_auth_configured():
        return RedirectResponse(
            f"/login?error={quote('Google authentication is not configured')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    settings = get_settings()
    state = google_auth_service.generate_state_token()
    redirect_uri = google_auth_service.get_redirect_uri(request)
    auth_url = google_auth_service.build_authorization_url(redirect_uri, state)

    response = RedirectResponse(auth_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "oauth_state",
        state,
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        max_age=600,
    )
    return response


@router.get("/login/google/callback", dependencies=[Depends(check_auth_rate_limit)])
async def google_callback(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    settings = get_settings()

    if error:
        return RedirectResponse(
            f"/login?error={quote('Google sign-in was cancelled: ' + error)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    expected_state = request.cookies.get("oauth_state")
    if not expected_state or not state or expected_state != state:
        response = RedirectResponse(
            f"/login?error={quote('Invalid or expired login session. Please try again.')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.delete_cookie("oauth_state")
        return response

    if not code:
        response = RedirectResponse(
            f"/login?error={quote('Missing authorization code from Google')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.delete_cookie("oauth_state")
        return response

    redirect_uri = google_auth_service.get_redirect_uri(request)
    try:
        user_info = await google_auth_service.exchange_code_for_user_info(code, redirect_uri)
        user = await google_auth_service.get_or_create_google_user(db, user_info)
    except HTTPException as exc:
        response = RedirectResponse(
            f"/login?error={quote(str(exc.detail))}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.delete_cookie("oauth_state")
        return response
    except Exception as exc:
        response = RedirectResponse(
            f"/login?error={quote(f'Authentication failed: {exc}')}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.delete_cookie("oauth_state")
        return response

    client_ip = get_client_ip(request)
    if not is_ip_allowed(client_ip, user.allowed_ips):
        err_msg = f"Access denied: IP address {client_ip} is not authorized for your account."
        response = RedirectResponse(
            f"/login?error={quote(err_msg)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
        response.delete_cookie("oauth_state")
        return response

    response = RedirectResponse("/services", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "access_token",
        auth_service.issue_token(user),
        httponly=True,
        samesite="lax",
        secure=not settings.debug,
        max_age=settings.access_token_expire_minutes * 60,
    )
    response.delete_cookie("oauth_state")
    return response


@router.post("/login", response_class=HTMLResponse, dependencies=[Depends(check_auth_rate_limit)])
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    settings = get_settings()
    if not settings.enable_local_auth:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Username/password login is disabled. Please use Google Sign-in.",
                "google_enabled": google_auth_service.is_google_auth_configured(),
                "enable_local_auth": False,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = await auth_service.authenticate(db, username, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "Invalid username or password",
                "google_enabled": google_auth_service.is_google_auth_configured(),
                "enable_local_auth": settings.enable_local_auth,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    client_ip = get_client_ip(request)
    if not is_ip_allowed(client_ip, user.allowed_ips):
        err_msg = f"Access denied: IP address {client_ip} is not authorized for your account."
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": err_msg,
                "google_enabled": google_auth_service.is_google_auth_configured(),
                "enable_local_auth": settings.enable_local_auth,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )

    response = RedirectResponse("/services", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "access_token",
        auth_service.issue_token(user),
        httponly=True,
        samesite="lax",
        secure=not get_settings().debug,
        max_age=get_settings().access_token_expire_minutes * 60,
    )
    return response


@router.post("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response


@router.post("/auth/token", response_model=Token, dependencies=[Depends(check_auth_rate_limit)])
async def token(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    settings = get_settings()
    if not settings.enable_local_auth:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password authentication is disabled. Please use Google Sign-in.",
        )

    user = await auth_service.authenticate(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        )

    client_ip = get_client_ip(request)
    if not is_ip_allowed(client_ip, user.allowed_ips):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: IP address {client_ip} is not authorized for this account",
        )

    return Token(access_token=auth_service.issue_token(user))
