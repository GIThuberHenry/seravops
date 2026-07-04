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
from app.schemas.service import ServiceCreate, ServiceResponse
from app.services import service_service

router = APIRouter(tags=["services"])
templates = Jinja2Templates(directory=get_settings().template_dir)


@router.get("/services", response_class=HTMLResponse)
async def service_list(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    services = await service_service.list_services(db)
    return templates.TemplateResponse(
        request, "services/list.html", {"services": services, "current_user": user}
    )


@router.get("/api/services", response_model=list[ServiceResponse])
async def service_list_api(
    _user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list:
    return await service_service.list_services(db)


@router.post("/services", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def service_create(
    data: ServiceCreate,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceResponse:
    return ServiceResponse.model_validate(await service_service.create_service(db, data))


@router.get("/services/new", response_class=HTMLResponse)
async def service_new_page(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "services/new.html", {"current_user": user, "error": None, "form": {}}
    )


@router.post("/services/new", response_class=HTMLResponse)
async def service_new_submit(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    name: Annotated[str, Form()] = "",
    slug: Annotated[str, Form()] = "",
    framework: Annotated[str, Form()] = "",
    target_server: Annotated[str, Form()] = "server_1",
    app_path: Annotated[str, Form()] = "",
) -> HTMLResponse:
    form = {"name": name, "slug": slug, "framework": framework, "target_server": target_server, "app_path": app_path}
    try:
        data = ServiceCreate(**form)
        service = await service_service.create_service(db, data)
        return RedirectResponse(f"/services/{service.id}/recipes", status_code=status.HTTP_303_SEE_OTHER)
    except ValidationError as exc:
        error = "; ".join(e["msg"] for e in exc.errors())
        return templates.TemplateResponse(
            request, "services/new.html", {"current_user": user, "error": error, "form": form},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request, "services/new.html", {"current_user": user, "error": str(exc), "form": form},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/services/{service_id}", response_model=ServiceResponse)
async def service_get(
    service_id: int,
    _user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ServiceResponse:
    service = await service_service.get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return ServiceResponse.model_validate(service)
