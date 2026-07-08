from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.security import require_admin, require_auth
from app.db import get_db
from app.models import User
from app.models.enums import UserRole
from app.routers import templates
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    users = await user_service.get_users(db)
    return templates.TemplateResponse(
        request, "users/list.html", {"current_user": user, "users": users}
    )

@router.get("/new", response_class=HTMLResponse)
async def new_user_form(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "users/new.html", {"current_user": user, "form": {}}
    )

@router.post("/new", response_class=HTMLResponse)
async def new_user_submit(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    role: Annotated[UserRole, Form()],
    ip_address: Annotated[str, Form()] = "",
) -> HTMLResponse:
    try:
        await user_service.create_user(
            db=db,
            username=username,
            password=password,
            role=role,
            ip_address=ip_address if ip_address else None
        )
        return RedirectResponse("/users", status_code=303)
    except IntegrityError:
        return templates.TemplateResponse(
            request, "users/new.html",
            {
                "current_user": user,
                "error": "Username already exists.",
                "form": {"username": username, "role": role.value, "ip_address": ip_address}
            },
            status_code=422,
        )

@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_form(
    request: Request,
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    target_user = await user_service.get_user_by_id(db, user_id)
    if not target_user:
        return HTMLResponse("User not found", status_code=404)
    
    return templates.TemplateResponse(
        request, "users/edit.html",
        {"current_user": user, "target_user": target_user}
    )

@router.post("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_submit(
    request: Request,
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    username: Annotated[str, Form()],
    role: Annotated[UserRole, Form()],
    ip_address: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
) -> HTMLResponse:
    target_user = await user_service.get_user_by_id(db, user_id)
    if not target_user:
        return HTMLResponse("User not found", status_code=404)

    try:
        await user_service.update_user(
            db=db,
            user=target_user,
            username=username,
            role=role,
            ip_address=ip_address if ip_address else None,
            password=password if password else None
        )
        return RedirectResponse("/users", status_code=303)
    except IntegrityError:
        return templates.TemplateResponse(
            request, "users/edit.html",
            {
                "current_user": user,
                "target_user": target_user,
                "error": "Username already exists."
            },
            status_code=422,
        )

@router.post("/{user_id}/delete", response_class=HTMLResponse)
async def delete_user_submit(
    request: Request,
    user_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    target_user = await user_service.get_user_by_id(db, user_id)
    if not target_user:
        return HTMLResponse("User not found", status_code=404)
    if target_user.id == user.id:
        return HTMLResponse("Cannot delete yourself", status_code=400)

    await user_service.delete_user(db, target_user)
    return RedirectResponse("/users", status_code=303)
