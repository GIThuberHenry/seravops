from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db import get_db
from app.schemas.auth import Token
from app.services import auth_service

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    user = await auth_service.authenticate(db, username, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=status.HTTP_401_UNAUTHORIZED,
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


@router.post("/auth/token", response_model=Token)
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Token:
    user = await auth_service.authenticate(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        )
    return Token(access_token=auth_service.issue_token(user))
