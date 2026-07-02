from sqlalchemy import select

from app.models import (
    ExecutionLog,
    ExecutionStatus,
    Recipe,
    RecipeStep,
    Service,
    StepKind,
    User,
    UserRole,
)
from app.services import recipe_service, ssh_service
from app.services.auth_service import hash_password
from app.services.ssh_service import CommandResult


async def test_recipe_execution_streams_logs_and_succeeds(session_factory, monkeypatch) -> None:
    async with session_factory() as db:
        user = User(
            username="developer",
            password_hash=hash_password("secret"),
            role=UserRole.DEVELOPER,
        )
        service = Service(
            name="Demo",
            slug="demo",
            framework="FastAPI",
            target_server="server_1",
            app_path="/tmp/demo",
        )
        recipe = Recipe(
            service=service,
            name="Update",
            description="Test update",
            steps=[
                RecipeStep(position=1, name="Pull", kind=StepKind.GIT_PULL, config={}),
                RecipeStep(
                    position=2,
                    name="Restart",
                    kind=StepKind.COMMAND,
                    command="echo restarted",
                    config={},
                ),
            ],
        )
        db.add_all([user, recipe])
        await db.commit()
        execution = await recipe_service.create_execution(db, recipe.id, user)
        execution_id = execution.id

    async def fake_execute(_command, _target, on_output):
        await on_output("stdout", "first chunk")
        await on_output("stderr", "diagnostic chunk")
        return CommandResult(exit_code=0)

    monkeypatch.setattr(ssh_service, "execute", fake_execute)
    await recipe_service.run_recipe_execution(execution_id, session_factory)

    async with session_factory() as db:
        execution = await recipe_service.get_execution(db, execution_id)
        messages = list(
            await db.scalars(
                select(ExecutionLog.message)
                .where(ExecutionLog.execution_id == execution_id)
                .order_by(ExecutionLog.id)
            )
        )

    assert execution is not None
    assert execution.status == ExecutionStatus.SUCCESS
    assert execution.started_at is not None
    assert execution.finished_at is not None
    assert "first chunk" in messages
    assert "diagnostic chunk" in messages
    assert messages[-1] == "Step finished with exit code 0"


async def test_recipe_execution_stops_after_failed_step(session_factory, monkeypatch) -> None:
    async with session_factory() as db:
        user = User(username="admin", password_hash=hash_password("secret"), role=UserRole.ADMIN)
        service = Service(
            name="Failure Demo",
            slug="failure-demo",
            framework="Golang",
            target_server="server_1",
            app_path="/tmp/demo",
        )
        recipe = Recipe(
            service=service,
            name="Fail",
            steps=[
                RecipeStep(
                    position=1,
                    name="Broken",
                    kind=StepKind.COMMAND,
                    command="false",
                    config={},
                )
            ],
        )
        db.add_all([user, recipe])
        await db.commit()
        execution = await recipe_service.create_execution(db, recipe.id, user)

    async def fail(_command, _target, on_output):
        await on_output("stderr", "command failed")
        return CommandResult(exit_code=7)

    monkeypatch.setattr(ssh_service, "execute", fail)
    await recipe_service.run_recipe_execution(execution.id, session_factory)

    async with session_factory() as db:
        completed = await recipe_service.get_execution(db, execution.id)
    assert completed is not None
    assert completed.status == ExecutionStatus.FAILED
