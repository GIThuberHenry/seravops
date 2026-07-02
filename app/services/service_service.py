from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Service
from app.schemas.service import ServiceCreate


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
