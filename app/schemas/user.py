from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=128)
    role: UserRole = UserRole.DEVELOPER
    allowed_ips: str | None = None


class UserUpdate(BaseModel):
    username: str = Field(min_length=2, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$")
    role: UserRole = UserRole.DEVELOPER
    allowed_ips: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: UserRole
    allowed_ips: str | None
    created_at: str | None = None
