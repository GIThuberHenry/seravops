from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import require_auth
from app.db import get_db
from app.models import ExecutionStatus, Recipe, RecipeExecution, Service, User
from app.services import flutter_service

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.get("/dashboard", response_class=HTMLResponse)
async def main_dashboard(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    settings = get_settings()

    # 1. Services & recipes
    services = list(
        await db.scalars(
            select(Service).options(selectinload(Service.recipes)).order_by(Service.name)
        )
    )
    total_recipes = sum(len(s.recipes) for s in services)

    # 2. Users count
    users_count = await db.scalar(select(func.count()).select_from(User)) or 0
    users_list = list(await db.scalars(select(User).order_by(User.id).limit(8)))

    # 3. Flutter CI/CD stats & recent runs
    flutter_recipe = await flutter_service.get_or_create_flutter_recipe(db)
    flutter_execs = await flutter_service.list_flutter_executions(
        db, flutter_recipe.id, limit=8
    )
    _, catalog_stats = flutter_service.build_enriched_catalog(flutter_execs)

    # 4. Recent general recipe executions (excluding Flutter CI/CD)
    recent_recipe_execs = list(
        await db.scalars(
            select(RecipeExecution)
            .where(RecipeExecution.recipe_id != flutter_recipe.id)
            .options(
                selectinload(RecipeExecution.recipe).selectinload(Recipe.service),
                selectinload(RecipeExecution.triggered_by),
            )
            .order_by(RecipeExecution.id.desc())
            .limit(6)
        )
    )

    active_total = await db.scalar(
        select(func.count())
        .select_from(RecipeExecution)
        .where(
            RecipeExecution.status.in_(
                [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]
            )
        )
    ) or 0

    return templates.TemplateResponse(
        request,
        "dashboard/index.html",
        {
            "current_user": user,
            "services": services,
            "total_services": len(services),
            "total_recipes": total_recipes,
            "users_count": users_count,
            "users_list": users_list,
            "flutter_execs": flutter_execs[:5],
            "catalog_stats": catalog_stats,
            "recent_recipe_execs": recent_recipe_execs,
            "active_total": active_total,
            "github_repo": settings.github_repo,
            "flutter_branch": settings.flutter_branch,
        },
    )
