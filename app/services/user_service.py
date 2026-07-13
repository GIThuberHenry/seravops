from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas.user import UserCreate, UserUpdate
from app.services.auth_service import hash_password


async def list_users(db: AsyncSession) -> list[User]:
    result = await db.scalars(select(User).order_by(User.username))
    return list(result)


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    return await db.get(User, user_id)


async def create_user(db: AsyncSession, data: UserCreate) -> User:
    # Check for duplicate username
    existing = await db.scalar(select(User).where(User.username == data.username))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{data.username}' already exists",
        )
    user = User(
        username=data.username,
        password_hash=hash_password(data.password),
        role=data.role,
        allowed_ips=data.allowed_ips or None,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user(db: AsyncSession, user_id: int, data: UserUpdate) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    # Check for duplicate username (exclude self)
    if data.username != user.username:
        existing = await db.scalar(select(User).where(User.username == data.username))
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{data.username}' already exists",
            )
    user.username = data.username
    user.role = data.role
    user.allowed_ips = data.allowed_ips or None
    if data.password:
        user.password_hash = hash_password(data.password)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: int, current_user_id: int) -> None:
    if user_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await db.delete(user)
    await db.commit()
