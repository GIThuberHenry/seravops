import json
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
from app.schemas.recipe import RecipeCreate, RecipeResponse, RecipeStepCreate, RecipeUpdate
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


@router.get("/services/{service_id}/recipes/new", response_class=HTMLResponse)
async def recipe_new_page(
    service_id: int,
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    service = await service_service.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return templates.TemplateResponse(
        request,
        "recipes/new.html",
        {"service": service, "current_user": user, "error": None, "form": {}, "prefill_steps": []},
    )


@router.post("/services/{service_id}/recipes/new", response_class=HTMLResponse)
async def recipe_new_submit(
    service_id: int,
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    service = await service_service.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")

    raw = await request.form()
    form_name = raw.get("name", "")
    form_description = raw.get("description", "")

    # Parse dynamic steps[N][field] from form data
    steps_by_index: dict[int, dict] = {}
    for key, val in raw.multi_items():
        if key.startswith("steps["):
            # steps[0][name] → index=0, field=name
            bracket = key.index("]")
            idx = int(key[6:bracket])
            field = key[bracket + 2 : -1]
            steps_by_index.setdefault(idx, {})[field] = val

    prefill_steps = []
    step_schemas = []
    for i, (_, step_data) in enumerate(sorted(steps_by_index.items())):
        kind = step_data.get("kind", "command")
        prefill = {
            "name": step_data.get("name", ""),
            "kind": kind,
            "command": step_data.get("command", ""),
            "nginx_subdomain": step_data.get("nginx_subdomain", ""),
            "nginx_port": step_data.get("nginx_port", ""),
            "nginx_service_name": step_data.get("nginx_service_name", ""),
        }
        prefill_steps.append(prefill)

        config: dict = {}
        if kind == "nginx":
            config = {
                "subdomain": step_data.get("nginx_subdomain", ""),
                "upstream_port": int(step_data.get("nginx_port", 0) or 0),
                "service_name": step_data.get("nginx_service_name", ""),
            }

        step_schemas.append({
            "position": i + 1,
            "name": step_data.get("name", ""),
            "kind": kind,
            "command": step_data.get("command") or None,
            "config": config,
        })

    def _render_error(error: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "recipes/new.html",
            {
                "service": service,
                "current_user": user,
                "error": error,
                "form": {"name": form_name, "description": form_description},
                "prefill_steps": prefill_steps,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if not step_schemas:
        return _render_error("Add at least one step before creating a recipe.")

    try:
        data = RecipeCreate(
            service_id=service_id,
            name=str(form_name),
            description=str(form_description),
            steps=[RecipeStepCreate(**s) for s in step_schemas],
        )
        recipe = await recipe_service.create_recipe(db, data)
        return RedirectResponse(f"/recipes/{recipe.id}", status_code=status.HTTP_303_SEE_OTHER)
    except (ValidationError, ValueError) as exc:
        msg = "; ".join(e["msg"] for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
        return _render_error(msg)
    except Exception as exc:
        return _render_error(str(exc))


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
    executions = await recipe_service.list_executions(db, recipe_id)
    return templates.TemplateResponse(
        request,
        "recipes/detail.html",
        {"recipe": recipe, "current_user": user, "executions": executions},
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


# ── Edit recipe ────────────────────────────────────────────────────────────


def _parse_steps_from_form(raw) -> tuple[list[dict], list[dict]]:
    """Parse steps[N][field] form data. Returns (step_schemas, prefill_steps)."""
    steps_by_index: dict[int, dict] = {}
    for key, val in raw.multi_items():
        if key.startswith("steps["):
            bracket = key.index("]")
            idx = int(key[6:bracket])
            field = key[bracket + 2 : -1]
            steps_by_index.setdefault(idx, {})[field] = val

    prefill_steps, step_schemas = [], []
    for i, (_, step_data) in enumerate(sorted(steps_by_index.items())):
        kind = step_data.get("kind", "command")
        prefill_steps.append({
            "name": step_data.get("name", ""),
            "kind": kind,
            "command": step_data.get("command", ""),
            "nginx_subdomain": step_data.get("nginx_subdomain", ""),
            "nginx_port": step_data.get("nginx_port", ""),
            "nginx_service_name": step_data.get("nginx_service_name", ""),
        })
        config: dict = {}
        if kind == "nginx":
            config = {
                "subdomain": step_data.get("nginx_subdomain", ""),
                "upstream_port": int(step_data.get("nginx_port", 0) or 0),
                "service_name": step_data.get("nginx_service_name", ""),
            }
        step_schemas.append({
            "position": i + 1,
            "name": step_data.get("name", ""),
            "kind": kind,
            "command": step_data.get("command") or None,
            "config": config,
        })
    return step_schemas, prefill_steps


def _steps_to_prefill(steps) -> list[dict]:
    """Convert ORM RecipeStep objects to prefill_steps dicts for the builder JS."""
    result = []
    for step in sorted(steps, key=lambda s: s.position):
        entry: dict = {
            "name": step.name,
            "kind": step.kind.value,
            "command": step.command or "",
            "nginx_subdomain": "",
            "nginx_port": "",
            "nginx_service_name": "",
        }
        if step.kind.value == "nginx" and step.config:
            entry["nginx_subdomain"] = step.config.get("subdomain", "")
            entry["nginx_port"] = str(step.config.get("upstream_port", ""))
            entry["nginx_service_name"] = step.config.get("service_name", "")
        result.append(entry)
    return result


@router.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
async def recipe_edit_page(
    recipe_id: int,
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return templates.TemplateResponse(
        request,
        "recipes/edit.html",
        {
            "recipe": recipe,
            "current_user": user,
            "error": None,
            "form": {"name": recipe.name, "description": recipe.description},
            "prefill_steps": _steps_to_prefill(recipe.steps),
        },
    )


@router.post("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
async def recipe_edit_submit(
    recipe_id: int,
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    raw = await request.form()
    form_name = raw.get("name", "")
    form_description = raw.get("description", "")
    step_schemas, prefill_steps = _parse_steps_from_form(raw)

    def _render_error(error: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "recipes/edit.html",
            {
                "recipe": recipe,
                "current_user": user,
                "error": error,
                "form": {"name": form_name, "description": form_description},
                "prefill_steps": prefill_steps,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    if not step_schemas:
        return _render_error("Add at least one step before saving.")

    try:
        data = RecipeUpdate(
            name=str(form_name),
            description=str(form_description),
            steps=[RecipeStepCreate(**s) for s in step_schemas],
        )
        await recipe_service.update_recipe(db, recipe_id, data)
        return RedirectResponse(f"/recipes/{recipe_id}", status_code=status.HTTP_303_SEE_OTHER)
    except (ValidationError, ValueError) as exc:
        msg = "; ".join(e["msg"] for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
        return _render_error(msg)
    except Exception as exc:
        return _render_error(str(exc))


@router.post("/recipes/{recipe_id}/delete", response_class=HTMLResponse)
async def recipe_delete(
    recipe_id: int,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    recipe = await recipe_service.get_recipe(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    service_id = recipe.service_id
    await recipe_service.delete_recipe(db, recipe_id)
    return RedirectResponse(f"/services/{service_id}/recipes", status_code=status.HTTP_303_SEE_OTHER)

