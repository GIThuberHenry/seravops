import base64
import hashlib
import hmac
import json
import re
import shlex
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
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
CATALOG_FILE = Path(__file__).with_name("flutter_catalog.json")

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
    "176. IKA PETRA",
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


def _extract_meta_from_logs(logs: list[ExecutionLog]) -> dict[str, Any]:
    for log in logs:
        if "Triggering Flutter CI/CD:" in log.message:
            client_m = re.search(r"client='([^']+)'", log.message)
            plat_m = re.search(r"platform='([^']+)'", log.message)
            act_m = re.search(r"action='([^']+)'", log.message)
            trk_m = re.search(r"track='([^']+)'", log.message)
            bmp_m = re.search(r"bump_version=(True|False)", log.message)
            return {
                "client": client_m.group(1) if client_m else "",
                "platform": plat_m.group(1) if plat_m else "",
                "action": act_m.group(1) if act_m else "",
                "track": trk_m.group(1) if trk_m else "",
                "bump_version": bmp_m.group(1) == "True" if bmp_m else False,
            }
    return {}


def _format_duration(started_at: datetime | None, finished_at: datetime | None) -> str:
    if not started_at:
        return "Queued"
    start_utc = started_at if started_at.tzinfo else started_at.replace(tzinfo=UTC)
    end_utc = (
        (finished_at if finished_at.tzinfo else finished_at.replace(tzinfo=UTC))
        if finished_at
        else datetime.now(UTC)
    )
    secs = max(0, int((end_utc - start_utc).total_seconds()))
    mins, rem = divmod(secs, 60)
    if mins > 0:
        return f"{mins}m {rem:02d}s"
    return f"{rem}s"


def build_pipeline_view(execution: RecipeExecution) -> dict[str, Any]:
    meta = _extract_meta_from_logs(execution.logs)
    platform = str(meta.get("platform") or "android").lower()
    action = str(meta.get("action") or "build_only").lower()
    track = str(meta.get("track") or "internal").lower()
    client = str(meta.get("client") or "Unknown Client")
    bump_version = bool(meta.get("bump_version", False))
    exec_status = execution.status.value

    if platform == "ios":
        step_defs = [
            (
                1,
                "Prepare Client Configuration",
                f"Copies publish/{client}, aligns version numbers & iOS Xcode settings",
            ),
            (
                2,
                "Install Flutter & CocoaPods",
                "Sets up Flutter 3.44.4 SDK, resolves pubspec packages & runs pod install",
            ),
            (
                3,
                "Configure Signing & Build IPA"
                if action == "build_and_publish"
                else "Compile iOS Release App",
                "Provisions Apple Distribution certificate & compiles release archive",
            ),
            (
                4,
                "Publish to Apple TestFlight"
                if action == "build_and_publish"
                else "Finalize iOS Artifact",
                "Uploads signed .ipa to App Store Connect / TestFlight via Fastlane",
            ),
        ]
    else:
        step_defs = [
            (
                1,
                "Prepare Client Configuration",
                f"Copies publish/{client}, aligns Gradle wrapper, keystore & Dart config",
            ),
            (
                2,
                "Setup Java 17 & Flutter 3.44.4",
                "Initializes Zulu JDK 17, restores Gradle cache & Flutter SDK",
            ),
            (
                3,
                "Resolve Flutter Dependencies",
                "Runs flutter pub get & applies compatibility shims",
            ),
            (
                4,
                "Compile Signed App Bundle (.aab)"
                if action == "build_and_publish"
                else "Compile Signed APK (.apk)",
                "Compiles release binary signed with client keystore",
            ),
            (
                5,
                f"Publish to Google Play ({track.title()})"
                if action == "build_and_publish"
                else "Upload Signed Artifact",
                "Uploads release bundle to Google Play Store via Fastlane",
            ),
        ]

    total_steps = len(step_defs)
    steps: list[dict[str, Any]] = [
        {
            "number": num,
            "total": total_steps,
            "title": title,
            "subtitle": subtitle,
            "status": "pending",
            "detail": "",
            "logs": [],
        }
        for num, title, subtitle in step_defs
    ]

    app_id = ""
    version_name = ""
    version_code = ""
    github_run_url = ""
    current_idx = -1
    stderr_lines: list[str] = []

    for log in execution.logs:
        msg = log.message.strip()
        if not msg:
            continue

        m_url = re.search(r"https://github\.com/[^\s]+/actions/runs/\d+", msg)
        if m_url:
            github_run_url = m_url.group(0)

        m_app = re.search(r"ApplicationId:\s*([^\s]+)", msg)
        if m_app:
            app_id = m_app.group(1)

        m_vn = re.search(r"Version Name:\s*([^\s]+)", msg)
        if m_vn:
            version_name = m_vn.group(1)

        m_vc = re.search(r"Version Code:\s*([^\s]+)", msg)
        if m_vc:
            version_code = m_vc.group(1)

        m_step = re.search(r"\[(\d+)/(\d+)\]\s*(.+)", msg)
        if m_step:
            s_num = int(m_step.group(1))
            idx = max(0, min(total_steps - 1, s_num - 1))
            if "⏳" in msg or log.stream == LogStream.SYSTEM:
                for prev in range(idx):
                    if steps[prev]["status"] in {"pending", "running"}:
                        steps[prev]["status"] = "success"
                steps[idx]["status"] = "running"
                current_idx = idx
            elif "✅" in msg:
                steps[idx]["status"] = "success"
                current_idx = idx

        if "✅ Signed release" in msg or "✅ Release IPA" in msg or "✅ iOS Release build" in msg:
            idx = 2 if platform == "ios" else 3
            if idx < total_steps:
                steps[idx]["status"] = "success"
        elif "✅ Published to" in msg:
            steps[-1]["status"] = "success"

        if current_idx >= 0 and log.stream in {LogStream.STDOUT, LogStream.STDERR}:
            steps[current_idx]["logs"].append(msg)
        if log.stream == LogStream.STDERR and "❌" not in msg:
            stderr_lines.append(msg)

    if app_id or version_name:
        steps[0]["detail"] = f"{app_id} · v{version_name} ({version_code})"
        if current_idx > 0 or exec_status == "success":
            steps[0]["status"] = "success"

    if action == "build_only" and exec_status == "success":
        for s in steps:
            s["status"] = "success"

    if exec_status == "success":
        for s in steps:
            s["status"] = "success"
        progress_pct = 100
        current_step_title = "Pipeline Completed Successfully"
        summary_message = (
            f"Published v{version_name} ({version_code}) to "
            f"{'Apple TestFlight' if platform == 'ios' else f'Google Play ({track})'}"
            if action == "build_and_publish"
            else f"Release build v{version_name} ({version_code}) completed"
        )
    elif exec_status == "failed":
        target_idx = current_idx if current_idx >= 0 else 0
        steps[target_idx]["status"] = "failed"
        done_count = sum(1 for s in steps if s["status"] == "success")
        progress_pct = max(10, int((done_count / total_steps) * 100))
        current_step_title = f"Failed at Step {target_idx + 1}: {steps[target_idx]['title']}"
        summary_message = current_step_title
    elif exec_status == "running":
        done_count = sum(1 for s in steps if s["status"] == "success")
        active_idx = current_idx if current_idx >= 0 else 0
        if steps[active_idx]["status"] == "pending":
            steps[active_idx]["status"] = "running"
        progress_pct = max(12, min(95, int(((done_count + 0.5) / total_steps) * 100)))
        current_step_title = f"Step {active_idx + 1}/{total_steps}: {steps[active_idx]['title']}"
        summary_message = current_step_title
    else:
        progress_pct = 5
        current_step_title = "Queued — Waiting for Cloud Runner"
        summary_message = current_step_title

    return {
        "id": execution.id,
        "status": exec_status,
        "client": client,
        "platform": platform,
        "action": action,
        "track": track,
        "bump_version": bump_version,
        "app_id": app_id,
        "version_name": version_name,
        "version_code": version_code,
        "github_run_url": github_run_url,
        "duration": _format_duration(execution.started_at, execution.finished_at),
        "progress_pct": progress_pct,
        "current_step_title": current_step_title,
        "summary_message": summary_message,
        "error_output": "\n".join(stderr_lines[-25:]),
        "steps": steps,
    }


async def list_flutter_executions(
    db: AsyncSession, recipe_id: int, limit: int = 25
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
        pipeline = build_pipeline_view(ex)
        results.append(
            {
                "id": ex.id,
                "status": ex.status,
                "triggered_by": ex.triggered_by,
                "started_at": ex.started_at,
                "finished_at": ex.finished_at,
                "meta": meta,
                "pipeline": pipeline,
            }
        )
    return results


def load_static_catalog() -> list[dict[str, Any]]:
    if CATALOG_FILE.is_file():
        try:
            return json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("flutter_catalog_load_failed", error=str(exc))
    return [
        {
            "folder": c,
            "company_id": None,
            "company_name": c,
            "company_slug": "",
            "dart_version": "",
            "dart_build": None,
            "android_ready": True,
            "android_app_id": "",
            "android_version_name": "",
            "android_version_code": None,
            "android_build_num": None,
            "has_keystore": True,
            "has_google_services": True,
            "ios_ready": True,
            "ios_bundle_id": "",
            "ios_version_name": "",
            "ios_build_num": "",
            "ios_team_id": "",
            "has_ios_plist": True,
        }
        for c in FLUTTER_CLIENTS
    ]


def build_enriched_catalog(executions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    raw_catalog = load_static_catalog()
    last_android_by_client: dict[str, dict[str, Any]] = {}
    last_ios_by_client: dict[str, dict[str, Any]] = {}

    for ex in executions:
        meta = ex.get("meta") or {}
        pipe = ex.get("pipeline") or {}
        c_name = str(meta.get("client") or "").strip()
        plat = str(meta.get("platform") or "").lower()
        if not c_name:
            continue
        summary = {
            "id": ex["id"],
            "status": ex["status"].value,
            "action": meta.get("action", ""),
            "track": meta.get("track", ""),
            "started_at": ex["started_at"].strftime("%Y-%m-%d %H:%M") if ex.get("started_at") else "queued",
            "version": pipe.get("version_name") or "",
            "build": pipe.get("version_code") or "",
        }
        if plat in {"android", "both"} and c_name not in last_android_by_client:
            last_android_by_client[c_name] = summary
        if plat in {"ios", "both"} and c_name not in last_ios_by_client:
            last_ios_by_client[c_name] = summary

    enriched: list[dict[str, Any]] = []
    for item in raw_catalog:
        folder = item["folder"]
        entry = dict(item)
        entry["last_android"] = last_android_by_client.get(folder)
        entry["last_ios"] = last_ios_by_client.get(folder)
        if entry["last_android"] and entry["last_android"].get("version"):
            entry["android_version_name"] = entry["last_android"]["version"]
        if entry["last_ios"] and entry["last_ios"].get("version"):
            entry["ios_version_name"] = entry["last_ios"]["version"]
        enriched.append(entry)

    # Sort so recently built or active clients appear nicely or preserve folder order
    stats = {
        "total": len(enriched),
        "android_ready": sum(1 for c in enriched if c.get("android_ready")),
        "ios_ready": sum(1 for c in enriched if c.get("ios_ready")),
        "active_runs": sum(
            1 for ex in executions if ex["status"].value in {"pending", "running"}
        ),
    }
    return enriched, stats


def query_app_store_live(bundle_id: str) -> dict[str, Any]:
    """Query Apple App Store Connect API for live App Store version and TestFlight builds."""
    settings = get_settings()
    key_id = settings.asc_key_id.strip()
    issuer_id = settings.asc_issuer_id.strip()
    raw_p8 = settings.asc_key_p8.strip()
    if not key_id or not issuer_id or not raw_p8 or not bundle_id:
        return {"configured": False, "error": "App Store Connect API key not configured on server"}

    try:
        import jwt  # PyJWT

        p8_pem = raw_p8 if "BEGIN PRIVATE KEY" in raw_p8 else base64.b64decode(raw_p8).decode("utf-8")
        now = int(time.time())
        token = jwt.encode(
            {"iss": issuer_id, "iat": now - 60, "exp": now + 600, "aud": "appstoreconnect-v1"},
            p8_pem,
            algorithm="ES256",
            headers={"kid": key_id, "typ": "JWT"},
        )

        def _get(path: str) -> dict[str, Any]:
            req = urllib.request.Request(
                f"https://api.appstoreconnect.apple.com{path}",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))

        apps_res = _get(f"/v1/apps?filter[bundleId]={urllib.parse.quote(bundle_id)}")
        apps = apps_res.get("data") or []
        if not apps:
            return {
                "configured": True,
                "found": False,
                "bundle_id": bundle_id,
                "message": f"No app found in App Store Connect with bundleId '{bundle_id}'",
            }

        app_obj = apps[0]
        app_id = app_obj["id"]
        app_attr = app_obj.get("attributes") or {}

        builds_res = _get(f"/v1/builds?filter[app]={app_id}&limit=5")
        builds = []
        for b in builds_res.get("data") or []:
            ba = b.get("attributes") or {}
            builds.append(
                {
                    "version": ba.get("version"),
                    "uploaded_at": (ba.get("uploadedDate") or "")[:16].replace("T", " "),
                    "state": ba.get("processingState"),
                    "expired": ba.get("expired", False),
                }
            )

        vers_res = _get(f"/v1/apps/{app_id}/appStoreVersions?limit=3")
        versions = []
        for v in vers_res.get("data") or []:
            va = v.get("attributes") or {}
            versions.append(
                {
                    "version_string": va.get("versionString"),
                    "state": va.get("appStoreState"),
                    "platform": va.get("platform"),
                }
            )

        return {
            "configured": True,
            "found": True,
            "app_id": app_id,
            "name": app_attr.get("name"),
            "bundle_id": app_attr.get("bundleId"),
            "sku": app_attr.get("sku"),
            "versions": versions,
            "builds": builds,
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")[:300]
        return {"configured": True, "found": False, "error": f"Apple API HTTP {exc.code}: {body}"}
    except Exception as exc:
        return {"configured": True, "found": False, "error": str(exc)}


async def refresh_catalog_from_server2() -> int:
    """Scan /root/projects/ss-flutter/publish on server_2 via SSH and update flutter_catalog.json."""
    settings = get_settings()
    target = settings.server("server_2")
    py_cmd = (
        "python3 - << 'PYEOF'\n"
        "import os, re, json, glob\n"
        "pub_root = '/root/projects/ss-flutter/publish'\n"
        "if not os.path.isdir(pub_root):\n"
        "    pub_root = '/home/osb/ss-flutter/publish'\n"
        "clients = []\n"
        "if os.path.isdir(pub_root):\n"
        "    for entry in sorted(os.listdir(pub_root)):\n"
        "        c_dir = os.path.join(pub_root, entry)\n"
        "        if not os.path.isdir(c_dir): continue\n"
        "        info = {'folder': entry, 'company_id': None, 'company_name': '', 'company_slug': '', 'dart_version': '', 'dart_build': None, 'android_ready': False, 'android_app_id': '', 'android_version_name': '', 'android_version_code': None, 'android_build_num': None, 'has_keystore': False, 'has_google_services': False, 'ios_ready': False, 'ios_bundle_id': '', 'ios_version_name': '', 'ios_build_num': '', 'ios_team_id': '', 'has_ios_plist': False}\n"
        "        dart_cfg = os.path.join(c_dir, 'lib/settings/companies/active/configuration.dart')\n"
        "        if os.path.isfile(dart_cfg):\n"
        "            txt = open(dart_cfg, encoding='utf-8', errors='ignore').read()\n"
        "            m_id = re.search(r'int\\s+companyId\\s*=\\s*(\\d+)', txt)\n"
        "            m_co = re.search(r'String\\s+company\\s*=\\s*[\"\\x27]([^\"\\x27]+)[\"\\x27]', txt)\n"
        "            m_sl = re.search(r'String\\s+serverProdCompany\\s*=\\s*[\"\\x27]([^\"\\x27]+)[\"\\x27]', txt)\n"
        "            m_bv = re.search(r'String\\s+buildVersion\\s*=\\s*[\"\\x27]([^\"\\x27]+)[\"\\x27]', txt)\n"
        "            m_bc = re.search(r'int\\s+buildCode\\s*=\\s*(\\d+)', txt)\n"
        "            if m_id: info['company_id'] = int(m_id.group(1))\n"
        "            if m_co: info['company_name'] = m_co.group(1)\n"
        "            if m_sl: info['company_slug'] = m_sl.group(1)\n"
        "            if m_bv: info['dart_version'] = m_bv.group(1)\n"
        "            if m_bc: info['dart_build'] = int(m_bc.group(1))\n"
        "        gradle_p = os.path.join(c_dir, 'android/app/build.gradle')\n"
        "        if os.path.isfile(gradle_p):\n"
        "            g_txt = open(gradle_p, encoding='utf-8', errors='ignore').read()\n"
        "            m_aid = re.search(r'\\bapplicationId\\s*=?\\s*[\"\\x27]([^\"\\x27\\n]+)[\"\\x27]', g_txt)\n"
        "            m_vn = re.search(r'\\bversionName\\s*=?\\s*[\"\\x27]([^\"\\x27\\n]+)[\"\\x27]', g_txt)\n"
        "            m_vc1 = re.search(r'\\bversionCode\\s*=?\\s*1048576\\s*\\+\\s*(\\d+)', g_txt)\n"
        "            m_vc2 = re.search(r'\\bversionCode\\s*=?\\s*(\\d+)', g_txt)\n"
        "            if m_aid: info['android_app_id'] = m_aid.group(1)\n"
        "            if m_vn: info['android_version_name'] = m_vn.group(1)\n"
        "            if m_vc1:\n"
        "                info['android_build_num'] = int(m_vc1.group(1))\n"
        "                info['android_version_code'] = 1048576 + int(m_vc1.group(1))\n"
        "            elif m_vc2:\n"
        "                info['android_version_code'] = int(m_vc2.group(1))\n"
        "                info['android_build_num'] = int(m_vc2.group(1))\n"
        "        key_prop = os.path.join(c_dir, 'android/key.properties')\n"
        "        ks_files = glob.glob(os.path.join(c_dir, 'android/app/*.keystore')) + glob.glob(os.path.join(c_dir, 'android/app/*.jks'))\n"
        "        info['has_keystore'] = os.path.isfile(key_prop) and len(ks_files) > 0\n"
        "        info['has_google_services'] = os.path.isfile(os.path.join(c_dir, 'android/app/google-services.json'))\n"
        "        info['android_ready'] = bool(info['android_app_id'] and info['has_keystore'])\n"
        "        pbx_p = os.path.join(c_dir, 'ios/Runner.xcodeproj/project.pbxproj')\n"
        "        if os.path.isfile(pbx_p):\n"
        "            p_txt = open(pbx_p, encoding='utf-8', errors='ignore').read()\n"
        "            m_bid = re.search(r'PRODUCT_BUNDLE_IDENTIFIER\\s*=\\s*([^;\\s]+)\\s*;', p_txt)\n"
        "            m_mv = re.search(r'MARKETING_VERSION\\s*=\\s*([^;\\s]+)\\s*;', p_txt)\n"
        "            m_cpv = re.search(r'CURRENT_PROJECT_VERSION\\s*=\\s*([^;\\s]+)\\s*;', p_txt)\n"
        "            m_tm = re.search(r'DEVELOPMENT_TEAM\\s*=\\s*([^;\\s]+)\\s*;', p_txt)\n"
        "            if m_bid: info['ios_bundle_id'] = m_bid.group(1).strip('\"')\n"
        "            if m_mv and 'FLUTTER' not in m_mv.group(1): info['ios_version_name'] = m_mv.group(1).strip('\"')\n"
        "            if m_cpv and 'FLUTTER' not in m_cpv.group(1): info['ios_build_num'] = m_cpv.group(1).strip('\"')\n"
        "            if m_tm: info['ios_team_id'] = m_tm.group(1).strip('\"')\n"
        "        if not info['ios_version_name']: info['ios_version_name'] = info['android_version_name'] or info['dart_version']\n"
        "        if not info['ios_build_num'] and info['android_build_num']: info['ios_build_num'] = str(info['android_build_num'])\n"
        "        info['has_ios_plist'] = os.path.isfile(os.path.join(c_dir, 'ios/Runner/GoogleService-Info.plist')) or os.path.isfile(os.path.join(c_dir, 'ios/GoogleService-Info.plist'))\n"
        "        info['ios_ready'] = bool(info['ios_bundle_id'] and os.path.isfile(pbx_p))\n"
        "        clients.append(info)\n"
        "print('CATALOG_JSON_START')\n"
        "print(json.dumps(clients))\n"
        "print('CATALOG_JSON_END')\n"
        "PYEOF"
    )
    out_lines: list[str] = []

    async def _collect(stream: str, msg: str) -> None:
        if stream == "stdout":
            out_lines.append(msg)

    res = await ssh_service.execute(py_cmd, target, _collect)
    full_out = "\n".join(out_lines)
    if res.exit_code == 0 and "CATALOG_JSON_START" in full_out:
        raw_json = full_out.split("CATALOG_JSON_START", 1)[1].split("CATALOG_JSON_END", 1)[0].strip()
        parsed = json.loads(raw_json)
        if parsed:
            CATALOG_FILE.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            return len(parsed)
    return len(load_static_catalog())


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
