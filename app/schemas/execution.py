from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import ExecutionStatus, LogStream


class ExecutionRun(BaseModel):
    recipe_id: int


class ExecutionLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_id: int | None
    stream: LogStream
    message: str
    exit_code: int | None
    created_at: datetime


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipe_id: int
    status: ExecutionStatus
    started_at: datetime | None
    finished_at: datetime | None
    logs: list[ExecutionLogResponse] = []
