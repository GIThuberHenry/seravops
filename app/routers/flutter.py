from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import require_auth
from app.db import get_db
from app.models import User
from app.services import flutter_service, recipe_service

router = APIRouter(tags=["flutter"])
templates = Jinja2Templates(directory=get_settings().template_dir)


class CallbackPayload(BaseModel):
    token: str
    logs: list[dict[str, Any]] = []
    status: str | None = None


async def _build_flutter_dashboard_context(
    db: AsyncSession, user: User
) -> dict[str, Any]:
    recipe = await flutter_service.get_or_create_flutter_recipe(db)
    executions = await flutter_service.list_flutter_executions(db, recipe.id, limit=25)
    active_executions = [
        ex for ex in executions if ex["status"].value in {"pending", "running"}
    ]
    catalog, catalog_stats = flutter_service.build_enriched_catalog(executions)
    client_names = [c["folder"] for c in catalog] or flutter_service.FLUTTER_CLIENTS
    return {
        "current_user": user,
        "clients": client_names,
        "executions": executions,
        "active_executions": active_executions,
        "catalog": catalog,
        "catalog_stats": catalog_stats,
        "github_repo": get_settings().github_repo,
    }


@router.get("/flutter", response_class=HTMLResponse)
async def flutter_page(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    ctx = await _build_flutter_dashboard_context(db, user)
    return templates.TemplateResponse(request, "flutter/index.html", ctx)


@router.get("/flutter/overview-partial", response_class=HTMLResponse)
async def flutter_overview_partial(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    ctx = await _build_flutter_dashboard_context(db, user)
    return templates.TemplateResponse(request, "flutter/_overview.html", ctx)


@router.post("/flutter/catalog/refresh")
async def flutter_refresh_catalog(
    user: Annotated[User, Depends(require_auth)],
) -> RedirectResponse:
    await flutter_service.refresh_catalog_from_server2()
    return RedirectResponse("/flutter", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/flutter/runs/{execution_id}", response_class=HTMLResponse)
async def flutter_run_detail(
    execution_id: int,
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> HTMLResponse:
    execution = await recipe_service.get_execution(db, execution_id)
    if not execution:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    pipeline = flutter_service.build_pipeline_view(execution)
    context = {
        "execution": execution,
        "pipeline": pipeline,
        "current_user": user,
        "github_repo": get_settings().github_repo,
    }
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(request, "flutter/_run_status.html", context)
    return templates.TemplateResponse(request, "flutter/run.html", context)


@router.get("/api/flutter/store-status", response_class=HTMLResponse)
async def flutter_store_status(
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[str, Query()] = "",
) -> HTMLResponse:
    recipe = await flutter_service.get_or_create_flutter_recipe(db)
    executions = await flutter_service.list_flutter_executions(db, recipe.id, limit=25)
    catalog, _ = flutter_service.build_enriched_catalog(executions)
    app_entry = next((c for c in catalog if c["folder"] == client), None)
    if not app_entry:
        return HTMLResponse(
            f"<div class='alert alert-error'>Client '{client}' not found in catalog.</div>"
        )

    bundle_id = app_entry.get("ios_bundle_id") or app_entry.get("android_app_id") or ""
    asc_info = flutter_service.query_app_store_live(bundle_id) if bundle_id else {"configured": False}

    # Render a clean inline status card
    last_and = app_entry.get("last_android")
    last_ios = app_entry.get("last_ios")

    and_html = (
        f"<a href='/flutter/runs/{last_and['id']}' class='badge badge-green'>#{last_and['id']} {last_and['status']} ({last_and.get('track') or 'build'}) · {last_and['started_at']}</a>"
        if last_and
        else "<span class='muted'>No CI build triggered yet</span>"
    )
    ios_html = (
        f"<a href='/flutter/runs/{last_ios['id']}' class='badge badge-blue'>#{last_ios['id']} {last_ios['status']} ({last_ios.get('track') or 'build'}) · {last_ios['started_at']}</a>"
        if last_ios
        else "<span class='muted'>No CI build triggered yet</span>"
    )

    if asc_info.get("found"):
        vers = asc_info.get("versions") or []
        blds = asc_info.get("builds") or []
        v_str = (
            ", ".join(f"<b>v{v['version_string']}</b> ({v['state']})" for v in vers)
            if vers
            else "None"
        )
        b_str = (
            ", ".join(f"<b>#{b['version']}</b> ({b['state']} · {b['uploaded_at']})" for b in blds[:3])
            if blds
            else "None"
        )
        asc_html = (
            f"<div style='margin-top:8px; display:grid; gap:4px; font-size:.84rem;'>"
            f"<div>🍏 <strong>App Store Connect:</strong> {asc_info.get('name')} (<code>{asc_info.get('bundle_id')}</code> · ID {asc_info.get('app_id')})</div>"
            f"<div>📦 <strong>Store Versions:</strong> {v_str}</div>"
            f"<div>✈️ <strong>TestFlight Builds:</strong> {b_str}</div>"
            f"</div>"
        )
    elif asc_info.get("configured"):
        msg = asc_info.get("message") or asc_info.get("error") or "Not found on App Store Connect"
        asc_html = f"<div class='muted' style='margin-top:6px; font-size:.82rem;'>🍏 App Store Connect: {msg}</div>"
    else:
        asc_html = "<div class='muted' style='margin-top:6px; font-size:.82rem;'>🍏 App Store Connect live query: check repo metadata above</div>"

    html = f"""
    <div style="padding:14px 16px; background:var(--surface-3); border:1px solid var(--border-2); border-radius:var(--radius-sm); margin-top:8px;">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:8px;">
        <strong>🔍 Live Inspection: {app_entry['folder']} ({app_entry.get('company_name') or 'N/A'})</strong>
        <span class="badge">Company ID #{app_entry.get('company_id') or '?'} · {app_entry.get('company_slug') or 'no-slug'}.shiftsoft.org</span>
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px; font-size:.84rem;">
        <div>
          <div class="muted">🤖 Android Repo & CI</div>
          <div>Package: <code>{app_entry.get('android_app_id') or 'N/A'}</code></div>
          <div>Version: <strong>v{app_entry.get('android_version_name') or '?'}</strong> (build {app_entry.get('android_build_num') or '?'})</div>
          <div>Keystore: {'✅ Present' if app_entry.get('has_keystore') else '❌ Missing'} · Firebase: {'✅' if app_entry.get('has_google_services') else '❌'}</div>
          <div style="margin-top:4px;">Last CI: {and_html}</div>
        </div>
        <div>
          <div class="muted">🍎 iOS Repo & CI</div>
          <div>Bundle ID: <code>{app_entry.get('ios_bundle_id') or 'N/A'}</code> (Team {app_entry.get('ios_team_id') or '?'})</div>
          <div>Version: <strong>v{app_entry.get('ios_version_name') or '?'}</strong> (build {app_entry.get('ios_build_num') or '?'})</div>
          <div>Xcodeproj: {'✅ Ready' if app_entry.get('ios_ready') else '❌ Incomplete'} · Plist: {'✅' if app_entry.get('has_ios_plist') else '❌'}</div>
          <div style="margin-top:4px;">Last CI: {ios_html}</div>
        </div>
      </div>
      {asc_html}
    </div>
    """
    return HTMLResponse(html)


@router.post("/flutter/trigger")
async def flutter_trigger(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    client: Annotated[str, Form()] = "001. ShiftMMS",
    platform: Annotated[str, Form()] = "android",
    action: Annotated[str, Form()] = "build_only",
    track: Annotated[str, Form()] = "internal",
    bump_version: Annotated[str, Form()] = "false",
    version_name: Annotated[str, Form()] = "",
) -> RedirectResponse:
    execution = await flutter_service.create_flutter_execution(db, user)
    background_tasks.add_task(
        flutter_service.run_flutter_trigger,
        execution.id,
        client.strip(),
        platform.strip(),
        action.strip(),
        track.strip(),
        bump_version.lower() in {"true", "1", "yes", "on"},
        version_name.strip(),
    )
    return RedirectResponse(
        f"/flutter/runs/{execution.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/api/flutter/executions/{execution_id}/callback")
async def flutter_execution_callback(
    execution_id: int,
    payload: CallbackPayload,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> JSONResponse:
    if not flutter_service.verify_callback_token(execution_id, payload.token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid callback token"
        )
    ok = await flutter_service.append_callback_logs(
        db, execution_id, payload.logs, payload.status
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found"
        )
    return JSONResponse({"ok": True})
