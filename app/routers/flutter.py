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


@router.post("/flutter/runs/{execution_id}/stop")
async def flutter_run_stop(
    execution_id: int,
    request: Request,
    user: Annotated[User, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    redirect_to: Annotated[str, Form()] = "",
) -> RedirectResponse:
    ok = await flutter_service.stop_flutter_execution(db, execution_id, user.username)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    target_url = redirect_to.strip() or f"/flutter/runs/{execution_id}"
    return RedirectResponse(target_url, status_code=status.HTTP_303_SEE_OTHER)


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
    pkg_id = app_entry.get("android_app_id") or bundle_id
    play_info = flutter_service.query_google_play_live(pkg_id) if pkg_id else {"configured": False}
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

    if play_info.get("found"):
        t_list = play_info.get("tracks") or []
        t_rows = []
        for t in t_list:
            b_cls = "badge-green" if t["track"] == "production" else "badge-blue"
            vc_str = ", ".join(
                f"code {vc} (#{b})" for vc, b in zip(t["version_codes"], t["builds"])
            )
            deliv = t.get("delivery_badge")
            if deliv == "LIVE_ON_STORE":
                deliv_pill = "<span class='badge badge-green'>🟢 LIVE ON PLAY STORE</span>"
            elif deliv == "IN_REVIEW":
                deliv_pill = "<span class='badge badge-yellow'>⏳ IN GOOGLE PLAY REVIEW</span>"
            else:
                deliv_pill = f"<span class='badge'>{t['status']}</span>"
            t_rows.append(
                f"<div style='display:flex; align-items:center; gap:8px; flex-wrap:wrap;'>"
                f"<span class='badge {b_cls}' style='min-width:95px; justify-content:center;'>{t['track']}</span>"
                f"<strong>{t['name'] or 'Release'}</strong>"
                f"<span class='mono muted text-xs'>({vc_str})</span>"
                f"{deliv_pill}"
                f"</div>"
            )
        pub_ver = play_info.get("public_version")
        pub_pill = (
            f"<span class='badge badge-green'>Public Store: v{pub_ver}</span>"
            if pub_ver
            else f"<span class='badge mono'>{play_info.get('package_name')}</span>"
        )
        t_html = "".join(t_rows) if t_rows else "<span class='muted'>No active track releases</span>"
        play_html = f"""
        <div style="margin-top:4px; padding:14px 16px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-sm); display:grid; gap:10px; font-size:.84rem;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div>🤖 <strong>Google Play Console Live Tracks</strong></div>
            {pub_pill}
          </div>
          <div style="display:grid; gap:7px;">
            {t_html}
          </div>
        </div>
        """
    elif play_info.get("configured"):
        p_msg = play_info.get("message") or play_info.get("error") or "Not found on Google Play"
        play_html = f"<div class='alert' style='margin-top:4px; background:var(--surface-2); border:1px solid var(--border); font-size:.82rem;'>🤖 <strong>Google Play Console:</strong> {p_msg}</div>"
    else:
        play_html = ""

    if asc_info.get("found"):
        vers = asc_info.get("versions") or []
        blds = asc_info.get("builds") or []
        v_badges = []
        for v in vers:
            st = v.get("state") or ""
            if st == "READY_FOR_SALE":
                v_badges.append(f"<span class='badge badge-green'>🟢 v{v['version_string']} · LIVE ON APP STORE</span>")
            elif "REVIEW" in st:
                v_badges.append(f"<span class='badge badge-yellow'>⏳ v{v['version_string']} · {st}</span>")
            else:
                v_badges.append(f"<span class='badge badge-blue'>v{v['version_string']} · {st}</span>")
        v_str = " ".join(v_badges) if v_badges else "<span class='muted'>None</span>"
        b_str = (
            " ".join(
                f"<span class='badge badge-blue'>#{b['version']} · {b['state']} ({b['uploaded_at']})</span>"
                for b in blds[:3]
            )
            if blds
            else "<span class='muted'>None</span>"
        )
        asc_html = f"""
        <div style="margin-top:14px; padding:14px 16px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-sm); display:grid; gap:10px; font-size:.84rem;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
            <div>🍏 <strong>App Store Connect Live Status</strong> · <span style="color:var(--text);">{asc_info.get('name')}</span></div>
            <span class="badge mono">{asc_info.get('bundle_id')} · ID {asc_info.get('app_id')}</span>
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span class="muted" style="min-width:125px;">📦 Store Versions:</span>
            {v_str}
          </div>
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span class="muted" style="min-width:125px;">✈️ TestFlight Builds:</span>
            {b_str}
          </div>
        </div>
        """
    elif asc_info.get("configured"):
        msg = asc_info.get("message") or asc_info.get("error") or "Not found on App Store Connect"
        asc_html = f"<div class='alert' style='margin-top:12px; background:var(--surface-2); border:1px solid var(--border); font-size:.82rem;'>🍏 <strong>App Store Connect:</strong> {msg}</div>"
    else:
        asc_html = "<div class='alert' style='margin-top:12px; background:var(--surface-2); border:1px solid var(--border); font-size:.82rem;'>🍏 <strong>App Store Connect:</strong> Live query ready when ASC_KEY_P8 is configured.</div>"

    html = f"""
    <div style="display:grid; gap:14px;">
      <div style="display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; padding:12px 16px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-sm);">
        <div>
          <div style="font-size:1.02rem; font-weight:700; color:var(--text);">{app_entry['folder']}</div>
          <div class="muted text-xs" style="margin-top:2px;">Company: <strong style="color:var(--text);">{app_entry.get('company_name') or 'N/A'}</strong> · Domain: <code>{app_entry.get('company_slug') or 'no-slug'}.shiftsoft.org</code></div>
        </div>
        <span class="badge badge-blue">Company ID #{app_entry.get('company_id') or '?'}</span>
      </div>

      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(250px, 1fr)); gap:12px; font-size:.84rem;">
        <div style="padding:14px 16px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-sm); display:grid; gap:7px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong>🤖 Android Config</strong>
            {'<span class="badge badge-green">✓ Ready</span>' if app_entry.get('android_ready') else '<span class="badge badge-red">⚠ Incomplete</span>'}
          </div>
          <div><span class="muted">Package:</span> <code class="mono">{app_entry.get('android_app_id') or 'N/A'}</code></div>
          <div><span class="muted">Version:</span> <strong class="mono">v{app_entry.get('android_version_name') or '?'}</strong> <span class="muted">(build {app_entry.get('android_build_num') or '?'} · code {app_entry.get('android_version_code') or '?'})</span></div>
          <div><span class="muted">Signing:</span> {'✅ Keystore' if app_entry.get('has_keystore') else '❌ Missing Keystore'} · {'✅ Firebase JSON' if app_entry.get('has_google_services') else '❌ Missing JSON'}</div>
          <div style="padding-top:4px; border-top:1px solid var(--border);"><span class="muted">Last CI:</span> {and_html}</div>
        </div>

        <div style="padding:14px 16px; background:var(--surface-2); border:1px solid var(--border); border-radius:var(--radius-sm); display:grid; gap:7px;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong>🍎 iOS Config</strong>
            {'<span class="badge badge-green">✓ Ready</span>' if app_entry.get('ios_ready') else '<span class="badge badge-yellow">⚠ Incomplete</span>'}
          </div>
          <div><span class="muted">Bundle ID:</span> <code class="mono">{app_entry.get('ios_bundle_id') or 'N/A'}</code></div>
          <div><span class="muted">Version:</span> <strong class="mono">v{app_entry.get('ios_version_name') or '?'}</strong> <span class="muted">(build {app_entry.get('ios_build_num') or '?'} · Team {app_entry.get('ios_team_id') or '?'})</span></div>
          <div><span class="muted">Xcode:</span> {'✅ Runner.xcodeproj' if app_entry.get('ios_ready') else '❌ Missing'} · {'✅ GoogleService-Info.plist' if app_entry.get('has_ios_plist') else '❌ Missing Plist'}</div>
          <div style="padding-top:4px; border-top:1px solid var(--border);"><span class="muted">Last CI:</span> {ios_html}</div>
        </div>
      </div>
      {play_html}
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
