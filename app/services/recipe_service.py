import shlex
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.logging import logger
from app.db import async_session_factory
from app.models import (
    ExecutionLog,
    ExecutionStatus,
    LogStream,
    Recipe,
    RecipeExecution,
    RecipeStep,
    StepKind,
    User,
)
from app.schemas.recipe import RecipeCreate, RecipeUpdate
from app.services import git_service, nginx_service, ssh_service
from app.services.ssh_service import CommandResult

SessionFactory = async_sessionmaker[AsyncSession]


async def list_recipes(db: AsyncSession, service_id: int | None = None) -> list[Recipe]:
    query = select(Recipe).options(selectinload(Recipe.steps)).order_by(Recipe.name)
    if service_id is not None:
        query = query.where(Recipe.service_id == service_id)
    return list(await db.scalars(query))


async def get_recipe(db: AsyncSession, recipe_id: int) -> Recipe | None:
    return await db.scalar(
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(selectinload(Recipe.steps), selectinload(Recipe.service))
    )


async def create_recipe(db: AsyncSession, data: RecipeCreate) -> Recipe:
    recipe = Recipe(
        service_id=data.service_id,
        name=data.name,
        description=data.description,
        steps=[RecipeStep(**step.model_dump()) for step in data.steps],
    )
    db.add(recipe)
    await db.commit()
    return await get_recipe(db, recipe.id)  # type: ignore[return-value]


async def update_recipe(db: AsyncSession, recipe_id: int, data: RecipeUpdate) -> Recipe:
    from sqlalchemy import delete as sa_delete

    recipe = await db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    recipe.name = data.name
    recipe.description = data.description
    # Replace all steps atomically
    await db.execute(sa_delete(RecipeStep).where(RecipeStep.recipe_id == recipe_id))
    for step_data in data.steps:
        db.add(RecipeStep(recipe_id=recipe_id, **step_data.model_dump()))
    await db.commit()
    return await get_recipe(db, recipe_id)  # type: ignore[return-value]


async def delete_recipe(db: AsyncSession, recipe_id: int) -> None:
    recipe = await db.get(Recipe, recipe_id)
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    await db.delete(recipe)
    await db.commit()



async def create_execution(db: AsyncSession, recipe_id: int, user: User) -> RecipeExecution:
    if not await db.get(Recipe, recipe_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    execution = RecipeExecution(recipe_id=recipe_id, triggered_by_id=user.id)
    db.add(execution)
    await db.commit()
    await db.refresh(execution)
    return execution


async def get_execution(db: AsyncSession, execution_id: int) -> RecipeExecution | None:
    return await db.scalar(
        select(RecipeExecution)
        .where(RecipeExecution.id == execution_id)
        .options(
            selectinload(RecipeExecution.recipe).selectinload(Recipe.service),
            selectinload(RecipeExecution.logs).selectinload(ExecutionLog.step),
        )
    )


async def list_executions(
    db: AsyncSession, recipe_id: int, limit: int = 20
) -> list[RecipeExecution]:
    from app.models.user import User  # avoid circular at module level

    return list(
        await db.scalars(
            select(RecipeExecution)
            .where(RecipeExecution.recipe_id == recipe_id)
            .options(selectinload(RecipeExecution.triggered_by))
            .order_by(RecipeExecution.id.desc())
            .limit(limit)
        )
    )


async def _append_log(
    session_factory: SessionFactory,
    execution_id: int,
    step_id: int | None,
    stream: LogStream,
    message: str,
    exit_code: int | None = None,
) -> None:
    async with session_factory() as db:
        db.add(
            ExecutionLog(
                execution_id=execution_id,
                step_id=step_id,
                stream=stream,
                message=message,
                exit_code=exit_code,
            )
        )
        await db.commit()


async def _set_execution_status(
    session_factory: SessionFactory,
    execution_id: int,
    execution_status: ExecutionStatus,
) -> None:
    async with session_factory() as db:
        execution = await db.get(RecipeExecution, execution_id)
        if not execution:
            return
        execution.status = execution_status
        if execution_status == ExecutionStatus.RUNNING:
            execution.started_at = datetime.now(UTC)
        elif execution_status in {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED}:
            execution.finished_at = datetime.now(UTC)
        await db.commit()


async def _execute_step(
    step: RecipeStep,
    recipe: Recipe,
    on_output: Callable,
) -> CommandResult:
    service = recipe.service
    target = get_settings().server(service.target_server)
    if step.kind == StepKind.GIT_PULL:
        return await git_service.pull(service.app_path, target, on_output)
    if step.kind == StepKind.NGINX:
        return await nginx_service.validate_and_apply(
            target=target, on_output=on_output, **step.config
        )
    command = f"cd {shlex.quote(service.app_path)} && {step.command}"
    return await ssh_service.execute(command, target, on_output)


async def run_recipe_execution(
    execution_id: int,
    session_factory: SessionFactory = async_session_factory,
) -> None:
    await _set_execution_status(session_factory, execution_id, ExecutionStatus.RUNNING)
    async with session_factory() as db:
        execution = await db.scalar(
            select(RecipeExecution)
            .where(RecipeExecution.id == execution_id)
            .options(
                selectinload(RecipeExecution.recipe).selectinload(Recipe.steps),
                selectinload(RecipeExecution.recipe).selectinload(Recipe.service),
            )
        )
        if not execution:
            return
        recipe = execution.recipe

    try:
        for step in recipe.steps:
            await _append_log(
                session_factory,
                execution_id,
                step.id,
                LogStream.SYSTEM,
                f"Starting step {step.position}: {step.name}",
            )

            async def on_output(stream: str, message: str, step_id: int = step.id) -> None:
                await _append_log(
                    session_factory,
                    execution_id,
                    step_id,
                    LogStream(stream),
                    message,
                )

            result = await _execute_step(step, recipe, on_output)
            await _append_log(
                session_factory,
                execution_id,
                step.id,
                LogStream.SYSTEM,
                f"Step finished with exit code {result.exit_code}",
                exit_code=result.exit_code,
            )
            if result.exit_code != 0:
                await _set_execution_status(session_factory, execution_id, ExecutionStatus.FAILED)
                return

        await _set_execution_status(session_factory, execution_id, ExecutionStatus.SUCCESS)
    except Exception as exc:
        logger.exception("recipe_execution_failed", execution_id=execution_id)
        await _append_log(
            session_factory,
            execution_id,
            None,
            LogStream.STDERR,
            f"Execution error: {exc}",
        )
        await _set_execution_status(session_factory, execution_id, ExecutionStatus.FAILED)
