import json
import shlex
import time
from datetime import UTC, datetime

import httpx
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
    Service,
    StepKind,
    User,
)
from app.services import ssh_service

SessionFactory = async_sessionmaker[AsyncSession]

FLUTTER_RECIPE_NAME = "Flutter Multi-Client CI/CD"

FLUTTER_CLIENTS: list[str] = [
    "001. ShiftMMS",
    "003. ELT",
    "004. SMCC",
    "005. Pandhega Jaya",
    "006. Seijinkai",
    "007. GBI PCW",
    "009. GBI Family Blessing",
    "010. Lahai Roi",
    "020. BethanyManado",
    "023. LGF Church",
    "024. Little Flock",
    "025. Inspire",
    "026. GBI Haleluya",
    "030. GBI Rock Timika",
    "031. ICOLC",
    "034. GBI Rock Mataram",
    "042. GBI Daan Mogot",
    "043. Pledge United",
    "044. GPIA KKS",
    "045. GBI Imamat Rajani",
    "048. GBI City of Love",
    "050. HFC Yogyakarta",
    "052. GBI Cikampek",
    "054. GPKdI HOT",
    "055. GBKP Banjarmasin",
    "056. GBI Bethel",
    "065. GCC JOGJA",
    "066. GBI River Of Life",
    "067. HCC Palu",
    "068. GKS Kemuliaan Sion",
    "068. Kemuliaan Sion",
    "069. HKBP Dalung",
    "070. ROCK Jayapura",
    "072. Sinode GPIA",
    "073. GKI Puri Indah",
    "074. Gereja Advent",
    "075. GBI Kingdom Vision",
    "076. GBI Ecclesia Tangerang",
    "077. TokTokTok",
    "078. JJM Net",
    "080. GBI Tampak Siring",
    "086. GBI Kapasari",
    "087. JKI Mahanaim",
    "088. BNKP Petrus Medan",
    "089. Decaffein",
    "090. GPIB Bukit Zaitun Mks",
    "091. Uang Recehan",
    "096. ECC Global",
    "099. GBI Sukawarna",
    "104. BDH Peduli",
    "106. LenteraTV",
    "107. GPdI Tiberias",
    "108. ROCK Surabaya",
    "109. GKPB MDC Malang",
    "111. GUPDITA",
    "112. GPIm Seraphim",
    "114. Arrow Basketball",
    "116. Marco Motor",
    "117. Tabgha Batam",
    "118. Blessing Music Studio",
    "122. Getsemani Padang",
    "123. GEPKIN",
    "124. SMCC Network",
    "125. OSAKA",
    "127. M&S Corner",
    "128. GPKdI Jelambar",
    "130. ISRA",
    "131. GBI Krispen",
    "132. DSCM Batu",
    "134 GBI Medan Plaza",
    "136. Viralkan",
    "137. LBCM",
    "138. King Sword",
    "139. IFGF Duri",
    "150. Hananeel",
    "156. GKKA Jemaat Palu",
    "156. GPIL JVDM",
    "160. GSRI Bekasi",
    "AmbassadorSchool",
    "ShiftAcademy",
    "app1",
    "ikapetra",
]


async def get_or_create_flutter_recipe(db: AsyncSession) -> Recipe:
    recipe = await db.scalar(
        select(Recipe)
        .where(Recipe.name == FLUTTER_RECIPE_NAME)
        .options(selectinload(Recipe.steps), selectinload(Recipe.service))
    )
    if recipe:
        return recipe

    service = await db.scalar(select(Service).where(Service.slug == "shiftsoft"))
    if not service:
        service = await db.scalar(select(Service).order_by(Service.id))
    if not service:
        service = Service(
            name="Shiftsoft",
            slug="shiftsoft",
            framework="Flutter, Go",
            target_server="server_2",
            app_path="/home/osb/",
        )
        db.add(service)
        await db.flush()

    recipe = Recipe(
        service_id=service.id,
        name=FLUTTER_RECIPE_NAME,
        description="Trigger GitHub Actions multi-client Flutter build & store publish",
        steps=[
            RecipeStep(
                position=1,
                name="Trigger GitHub Actions Workflow (Dinamigra/ss-flutter)",
                kind=StepKind.COMMAND,
                command="echo 'Triggered via Seravops Flutter CI/CD'",
                config={},
            )
        ],
    )
    db.add(recipe)
    await db.commit()
    return await db.scalar(
        select(Recipe)
        .where(Recipe.id == recipe.id)
        .options(selectinload(Recipe.steps), selectinload(Recipe.service))
    )  # type: ignore[return-value]


async def create_flutter_execution(db: AsyncSession, user: User) -> RecipeExecution:
    recipe = await get_or_create_flutter_recipe(db)
    execution = RecipeExecution(recipe_id=recipe.id, triggered_by_id=user.id)
    db.add(execution)
    await db.commit()
    await db.refresh(execution)
    return execution


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


async def _set_status(
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


async def run_flutter_trigger(
    execution_id: int,
    client: str,
    platform: str,
    action: str,
    track: str,
    bump_version: bool,
    version_name: str,
    session_factory: SessionFactory = async_session_factory,
) -> None:
    settings = get_settings()
    await _set_status(session_factory, execution_id, ExecutionStatus.RUNNING)

    step_id: int | None = None
    async with session_factory() as db:
        execution = await db.scalar(
            select(RecipeExecution)
            .where(RecipeExecution.id == execution_id)
            .options(selectinload(RecipeExecution.recipe).selectinload(Recipe.steps))
        )
        if execution and execution.recipe and execution.recipe.steps:
            step_id = execution.recipe.steps[0].id

    payload = {
        "client": client,
        "platform": platform,
        "action": action,
        "track": track,
        "bump_version": bump_version,
        "version_name": version_name,
    }

    await _append_log(
        session_factory,
        execution_id,
        step_id,
        LogStream.SYSTEM,
        f"Triggering Flutter CI/CD: client='{client}', platform='{platform}', "
        f"action='{action}', track='{track}', bump_version={bump_version}",
    )

    try:
        if settings.github_token:
            url = (
                f"https://api.github.com/repos/{settings.github_repo}"
                "/actions/workflows/deploy.yml/dispatches"
            )
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.github_token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            body = {
                "ref": "master",
                "inputs": {
                    "client": client,
                    "platform": platform,
                    "action": action,
                    "track": track,
                    "bump_version": bump_version,
                    "version_name": version_name,
                },
            }
            async with httpx.AsyncClient(timeout=20.0) as http_client:
                resp = await http_client.post(url, headers=headers, json=body)
            if resp.status_code in {200, 201, 204}:
                await _append_log(
                    session_factory,
                    execution_id,
                    step_id,
                    LogStream.STDOUT,
                    f"Dispatched workflow via GitHub REST API (HTTP {resp.status_code}).",
                )
                await _append_log(
                    session_factory,
                    execution_id,
                    step_id,
                    LogStream.STDOUT,
                    f"View live run: https://github.com/{settings.github_repo}/actions",
                )
                await _append_log(
                    session_factory,
                    execution_id,
                    step_id,
                    LogStream.SYSTEM,
                    "Step finished with exit code 0",
                    exit_code=0,
                )
                await _set_status(session_factory, execution_id, ExecutionStatus.SUCCESS)
                return

            await _append_log(
                session_factory,
                execution_id,
                step_id,
                LogStream.STDERR,
                f"GitHub API returned {resp.status_code}: {resp.text}. Falling back to SSH trigger.",
            )

        # Trigger via SSH git tag push on server_2 (already authenticated as GIThuberHenry)
        tag_name = f"cicd-trigger-{platform}-{int(time.time())}"
        payload_json = json.dumps(payload)
        q_tag = shlex.quote(tag_name)
        q_msg = shlex.quote(payload_json)
        q_repo = shlex.quote(f"git@github.com:{settings.github_repo}.git")

        cmd = (
            "set -e; "
            "WORKDIR=/tmp/seravops-ss-flutter-trigger; "
            "mkdir -p $WORKDIR && cd $WORKDIR; "
            "if [ ! -d .git ]; then "
            "  git init -q && "
            "  git config user.name 'Seravops CI/CD' && "
            "  git config user.email 'seravops@shiftsoft.org'; "
            "fi; "
            f"git remote set-url origin {q_repo} 2>/dev/null || git remote add origin {q_repo}; "
            "echo 'Fetching latest master commit from GitHub...'; "
            "git fetch --depth=1 origin master; "
            f"git tag -a {q_tag} FETCH_HEAD -m {q_msg}; "
            f"echo 'Pushing trigger tag {tag_name} to GitHub Actions...'; "
            f"git push origin refs/tags/{q_tag}; "
            f"git tag -d {q_tag} >/dev/null 2>&1 || true; "
            f"echo 'Successfully triggered GitHub Actions workflow!'; "
            f"echo 'Monitor run at: https://github.com/{settings.github_repo}/actions'"
        )

        target = settings.server("server_2")

        async def on_output(stream: str, message: str) -> None:
            await _append_log(
                session_factory,
                execution_id,
                step_id,
                LogStream(stream),
                message,
            )

        result = await ssh_service.execute(cmd, target, on_output)
        await _append_log(
            session_factory,
            execution_id,
            step_id,
            LogStream.SYSTEM,
            f"Step finished with exit code {result.exit_code}",
            exit_code=result.exit_code,
        )
        if result.exit_code == 0:
            await _set_status(session_factory, execution_id, ExecutionStatus.SUCCESS)
        else:
            await _set_status(session_factory, execution_id, ExecutionStatus.FAILED)
    except Exception as exc:
        logger.exception("flutter_trigger_failed", execution_id=execution_id)
        await _append_log(
            session_factory,
            execution_id,
            step_id,
            LogStream.STDERR,
            f"Trigger error: {exc}",
        )
        await _set_status(session_factory, execution_id, ExecutionStatus.FAILED)
