from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_auth
from app.db import get_db
from app.models import User
from app.services import flutter_service

router = APIRouter(tags=["flutter"])
templates = Jinja2Templates(directory=get_settings().template_dir)


class CallbackPayload(BaseModel):
    token: str
    logs: list[dict[str, Any]] = []
    status: str | None = None


@router.get("/flutter", response_class=HTMLResponse)
async def flutter_page(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    recipe = await flutter_service.get_or_create_flutter_recipe(db)
    executions = await flutter_service.list_flutter_executions(db, recipe.id, limit=15)
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


@router.post("/api/flutter/executions/{execution_id}/callback")
async def flutter_execution_callback(
    execution_id: int,
    payload: CallbackPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    if not flutter_service.verify_callback_token(execution_id, payload.token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid callback token")
    ok = await flutter_service.append_callback_logs(
        db, execution_id, payload.logs, payload.status
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return JSONResponse({"ok": True})
