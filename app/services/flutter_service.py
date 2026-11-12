import hashlib
import hmac
import json
import re
import shlex
import time
from datetime import UTC, datetime
from typing import Any

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
    "999. Fastlane Test",
]


def make_callback_token(execution_id: int) -> str:
    secret = get_settings().jwt_secret.encode()
    msg = f"flutter-callback:{execution_id}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def verify_callback_token(execution_id: int, token: str) -> bool:
    expected = make_callback_token(execution_id)
    return hmac.compare_digest(expected, token)


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
                name="Flutter Cloud CI/CD",
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


def _extract_meta_from_logs(logs: list[ExecutionLog]) -> dict[str, str]:
    for log in logs:
        if "Triggering Flutter CI/CD:" in log.message:
            client_m = re.search(r"client='([^']+)'", log.message)
            plat_m = re.search(r"platform='([^']+)'", log.message)
            act_m = re.search(r"action='([^']+)'", log.message)
            trk_m = re.search(r"track='([^']+)'", log.message)
            return {
                "client": client_m.group(1) if client_m else "",
                "platform": plat_m.group(1) if plat_m else "",
                "action": act_m.group(1) if act_m else "",
                "track": trk_m.group(1) if trk_m else "",
            }
    return {}


async def list_flutter_executions(
    db: AsyncSession, recipe_id: int, limit: int = 15
) -> list[dict[str, Any]]:
    executions = list(
        await db.scalars(
            select(RecipeExecution)
            .where(RecipeExecution.recipe_id == recipe_id)
            .options(
                selectinload(RecipeExecution.triggered_by),
                selectinload(RecipeExecution.logs),
            )
            .order_by(RecipeExecution.id.desc())
            .limit(limit)
        )
    )
    results: list[dict[str, Any]] = []
    for ex in executions:
        meta = _extract_meta_from_logs(ex.logs)
        results.append(
            {
                "id": ex.id,
                "status": ex.status,
                "triggered_by": ex.triggered_by,
                "started_at": ex.started_at,
                "finished_at": ex.finished_at,
                "meta": meta,
            }
        )
    return results


async def append_callback_logs(
    db: AsyncSession,
    execution_id: int,
    logs: list[dict[str, Any]],
    final_status: str | None = None,
) -> bool:
    execution = await db.scalar(
        select(RecipeExecution)
        .where(RecipeExecution.id == execution_id)
        .options(selectinload(RecipeExecution.recipe).selectinload(Recipe.steps))
    )
    if not execution:
        return False

    step_id: int | None = None
    if execution.recipe and execution.recipe.steps:
        step_id = execution.recipe.steps[0].id

    for entry in logs:
        stream_str = str(entry.get("stream", "stdout")).lower()
        if stream_str not in {"stdout", "stderr", "system"}:
            stream_str = "stdout"
        msg = str(entry.get("message", ""))
        code = entry.get("exit_code")
        if msg:
            db.add(
                ExecutionLog(
                    execution_id=execution_id,
                    step_id=step_id,
                    stream=LogStream(stream_str),
                    message=msg,
                    exit_code=int(code) if code is not None else None,
                )
            )

    if final_status == "success":
        execution.status = ExecutionStatus.SUCCESS
        execution.finished_at = datetime.now(UTC)
    elif final_status == "failed":
        execution.status = ExecutionStatus.FAILED
        execution.finished_at = datetime.now(UTC)

    await db.commit()
    return True


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

    callback_url = f"{settings.app_url.rstrip('/')}/api/flutter/executions/{execution_id}/callback"
    callback_token = make_callback_token(execution_id)

    payload = {
        "client": client,
        "platform": platform,
        "action": action,
        "track": track,
        "bump_version": bump_version,
        "version_name": version_name,
        "execution_id": execution_id,
        "callback_url": callback_url,
        "callback_token": callback_token,
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
        # Trigger via SSH git tag push on server_2 (carries callback_url & callback_token)
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
            "git fetch -q --depth=1 origin master; "
            f"git tag -a {q_tag} FETCH_HEAD -m {q_msg}; "
            f"git push -q origin refs/tags/{q_tag}; "
            f"git tag -d {q_tag} >/dev/null 2>&1 || true; "
            "echo '✅ Dispatched job to GitHub Actions cloud runner.'"
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
        if result.exit_code != 0:
            await _append_log(
                session_factory,
                execution_id,
                step_id,
                LogStream.STDERR,
                f"Failed to dispatch trigger (exit code {result.exit_code}).",
                exit_code=result.exit_code,
            )
            await _set_status(session_factory, execution_id, ExecutionStatus.FAILED)
            return

        await _append_log(
            session_factory,
            execution_id,
            step_id,
            LogStream.SYSTEM,
            "⏳ Waiting for GitHub Actions runner to start and stream live build steps...",
        )
        # Execution remains RUNNING until the GitHub Actions runner sends final callback
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
