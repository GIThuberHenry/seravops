from pydantic import BaseModel, ConfigDict, Field


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9-]+$")
    framework: str
    target_server: str = Field(pattern=r"^server_[12]$")
    app_path: str


class ServiceResponse(ServiceCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
