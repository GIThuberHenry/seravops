from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_admin, require_auth
from app.db import get_db
from app.models import User
from app.models.enums import UserRole
from app.schemas.user import UserCreate, UserUpdate
from app.services import user_service

router = APIRouter(tags=["users"])
templates = Jinja2Templates(directory=get_settings().template_dir)


# ── List ───────────────────────────────────────────────────────────────────


@router.get("/users", response_class=HTMLResponse)
async def user_list(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    users = await user_service.list_users(db)
    return templates.TemplateResponse(
        request, "users/list.html", {"users": users, "current_user": user}
    )


# ── Create ─────────────────────────────────────────────────────────────────


@router.get("/users/new", response_class=HTMLResponse)
async def user_new_page(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "users/new.html", {"current_user": user, "error": None, "form": {}}
    )


@router.post("/users/new", response_class=HTMLResponse)
async def user_new_submit(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    username: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "developer",
    allowed_ips: Annotated[str, Form()] = "",
) -> HTMLResponse:
    form = {"username": username, "role": role, "allowed_ips": allowed_ips}
    try:
        data = UserCreate(
            username=username,
            password=password,
            role=UserRole(role),
            allowed_ips=allowed_ips.strip() or None,
        )
        await user_service.create_user(db, data)
        return RedirectResponse("/users", status_code=status.HTTP_303_SEE_OTHER)
    except ValidationError as exc:
        error = "; ".join(e["msg"] for e in exc.errors())
        return templates.TemplateResponse(
            request, "users/new.html",
            {"current_user": user, "error": error, "form": form},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as exc:
        return templates.TemplateResponse(
            request, "users/new.html",
            {"current_user": user, "error": exc.detail, "form": form},
            status_code=status.HTTP_409_CONFLICT,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request, "users/new.html",
            {"current_user": user, "error": str(exc), "form": form},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


# ── Edit ───────────────────────────────────────────────────────────────────


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
async def user_edit_page(
    user_id: int,
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    target = await user_service.get_user(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return templates.TemplateResponse(
        request,
        "users/edit.html",
        {
            "current_user": user,
            "target_user": target,
            "error": None,
            "form": {
                "username": target.username,
                "role": target.role.value,
                "allowed_ips": target.allowed_ips or "",
            },
        },
    )


@router.post("/users/{user_id}/edit", response_class=HTMLResponse)
async def user_edit_submit(
    user_id: int,
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    username: Annotated[str, Form()] = "",
    role: Annotated[str, Form()] = "developer",
    allowed_ips: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> HTMLResponse:
    target = await user_service.get_user(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    form = {"username": username, "role": role, "allowed_ips": allowed_ips}
    try:
        data = UserUpdate(
            username=username,
            role=UserRole(role),
            allowed_ips=allowed_ips.strip() or None,
            password=password.strip() or None,
        )
        await user_service.update_user(db, user_id, data)
        return RedirectResponse("/users", status_code=status.HTTP_303_SEE_OTHER)
    except ValidationError as exc:
        error = "; ".join(e["msg"] for e in exc.errors())
        return templates.TemplateResponse(
            request, "users/edit.html",
            {"current_user": user, "target_user": target, "error": error, "form": form},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except HTTPException as exc:
        return templates.TemplateResponse(
            request, "users/edit.html",
            {"current_user": user, "target_user": target, "error": exc.detail, "form": form},
            status_code=status.HTTP_409_CONFLICT,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request, "users/edit.html",
            {"current_user": user, "target_user": target, "error": str(exc), "form": form},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


# ── Delete ─────────────────────────────────────────────────────────────────


@router.post("/users/{user_id}/delete", response_class=HTMLResponse)
async def user_delete(
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    await user_service.delete_user(db, user_id, user.id)
    return RedirectResponse("/users", status_code=status.HTTP_303_SEE_OTHER)
