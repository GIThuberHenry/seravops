from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ExecutionStatus, LogStream

if TYPE_CHECKING:
    from app.models.recipe import Recipe, RecipeStep
    from app.models.user import User


class RecipeExecution(Base):
    __tablename__ = "recipe_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id", ondelete="CASCADE"))
    triggered_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, native_enum=False), default=ExecutionStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    recipe: Mapped["Recipe"] = relationship(back_populates="executions")
    triggered_by: Mapped["User"] = relationship(back_populates="executions")
    logs: Mapped[list["ExecutionLog"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="ExecutionLog.id"
    )


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("recipe_executions.id", ondelete="CASCADE"), index=True
    )
    step_id: Mapped[int | None] = mapped_column(ForeignKey("recipe_steps.id"), nullable=True)
    stream: Mapped[LogStream] = mapped_column(Enum(LogStream, native_enum=False))
    message: Mapped[str] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    execution: Mapped["RecipeExecution"] = relationship(back_populates="logs")
    step: Mapped["RecipeStep | None"] = relationship()
