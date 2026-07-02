from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_auth
from app.db import get_db
from app.models import User
from app.schemas.execution import ExecutionResponse
from app.services import recipe_service

router = APIRouter(tags=["executions"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.post("/executions/run")
async def execution_run(
    recipe_id: Annotated[int, Form()],
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    execution = await recipe_service.create_execution(db, recipe_id, user)
    background_tasks.add_task(recipe_service.run_recipe_execution, execution.id)
    return RedirectResponse(f"/executions/{execution.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/executions/{execution_id}", response_class=HTMLResponse)
async def execution_detail(
    execution_id: int,
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    execution = await recipe_service.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    context = {"execution": execution, "current_user": user}
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "executions/_status.html", context)
    return templates.TemplateResponse(request, "executions/detail.html", context)


@router.get("/api/executions/{execution_id}", response_model=ExecutionResponse)
async def execution_get_api(
    execution_id: int,
    _user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExecutionResponse:
    execution = await recipe_service.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return ExecutionResponse.model_validate(execution)
