from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_admin, require_auth
from app.db import get_db
from app.models import User
from app.schemas.recipe import RecipeCreate, RecipeResponse
from app.services import recipe_service, service_service

router = APIRouter(tags=["recipes"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.get("/services/{service_id}/recipes", response_class=HTMLResponse)
async def recipe_list(
    service_id: int,
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    service = await service_service.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    recipes = await recipe_service.list_recipes(db, service_id)
    return templates.TemplateResponse(
        request,
        "recipes/list.html",
        {"service": service, "recipes": recipes, "current_user": user},
    )


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse)
async def recipe_detail(
    recipe_id: int,
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return templates.TemplateResponse(
        request, "recipes/detail.html", {"recipe": recipe, "current_user": user}
    )


@router.get("/api/recipes/{recipe_id}", response_model=RecipeResponse)
async def recipe_get_api(
    recipe_id: int,
    _user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecipeResponse:
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return RecipeResponse.model_validate(recipe)


@router.post("/recipes", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
async def recipe_create(
    data: RecipeCreate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RecipeResponse:
    recipe = await recipe_service.create_recipe(db, data)
    return RecipeResponse.model_validate(recipe)
