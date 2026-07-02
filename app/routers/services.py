from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
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
