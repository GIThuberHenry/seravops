from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_auth
from app.db import get_db
from app.models import User
from app.services import flutter_service, recipe_service

router = APIRouter(tags=["flutter"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.get("/flutter", response_class=HTMLResponse)
async def flutter_page(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    recipe = await flutter_service.get_or_create_flutter_recipe(db)
    executions = await recipe_service.list_executions(db, recipe.id, limit=15)
    return templates.TemplateResponse(
        request,
        "flutter/index.html",
        {
            "current_user": user,
            "clients": flutter_service.FLUTTER_CLIENTS,
            "executions": executions,
            "github_repo": get_settings().github_repo,
        },
    )


@router.post("/flutter/trigger")
async def flutter_trigger(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[str, Form()] = "001. ShiftMMS",
    platform: Annotated[str, Form()] = "android",
    action: Annotated[str, Form()] = "build_only",
    track: Annotated[str, Form()] = "internal",
    bump_version: Annotated[str, Form()] = "false",
    version_name: Annotated[str, Form()] = "",
) -> RedirectResponse:
    execution = await flutter_service.create_flutter_execution(db, user)
    background_tasks.add_task(
        flutter_service.run_flutter_trigger,
        execution.id,
        client.strip(),
        platform.strip(),
        action.strip(),
        track.strip(),
        bump_version.lower() in {"true", "1", "yes", "on"},
        version_name.strip(),
    )
    return RedirectResponse(f"/executions/{execution.id}", status_code=status.HTTP_303_SEE_OTHER)
