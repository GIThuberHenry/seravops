from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi import HTTPException, status

from app.models import Service
from app.schemas.service import ServiceCreate, ServiceUpdate


async def list_services(db: AsyncSession) -> list[Service]:
    result = await db.scalars(select(Service).order_by(Service.name))
    return list(result)


async def get_service(db: AsyncSession, service_id: int) -> Service | None:
    return await db.scalar(
        select(Service).where(Service.id == service_id).options(selectinload(Service.recipes))
    )


async def create_service(db: AsyncSession, data: ServiceCreate) -> Service:
    service = Service(**data.model_dump())
    db.add(service)
    await db.commit()
    await db.refresh(service)
    return service


async def update_service(db: AsyncSession, service_id: int, data: ServiceUpdate) -> Service:
    service = await db.get(Service, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    service.name = data.name
    service.framework = data.framework
    service.target_server = data.target_server
    service.app_path = data.app_path
    await db.commit()
    return await get_service(db, service_id)  # type: ignore[return-value]


async def delete_service(db: AsyncSession, service_id: int) -> None:
    service = await get_service(db, service_id)
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    await db.delete(service)
    await db.commit()

