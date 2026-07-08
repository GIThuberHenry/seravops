from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Sequence

from app.models.user import User
from app.models.enums import UserRole
from app.services.auth_service import hash_password

async def get_users(db: AsyncSession) -> Sequence[User]:
    result = await db.scalars(select(User).order_by(User.id))
    return result.all()

async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    return await db.scalar(select(User).where(User.id == user_id))

async def create_user(
    db: AsyncSession,
    username: str,
    password: str,
    role: UserRole,
    ip_address: str | None = None
) -> User:
    hashed_password = hash_password(password)
    user = User(
        username=username,
        password_hash=hashed_password,
        role=role,
        ip_address=ip_address
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def update_user(
    db: AsyncSession,
    user: User,
    username: str,
    role: UserRole,
    ip_address: str | None = None,
    password: str | None = None
) -> User:
    user.username = username
    user.role = role
    user.ip_address = ip_address
    if password:
        user.password_hash = hash_password(password)
    await db.commit()
    await db.refresh(user)
    return user

async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.commit()
