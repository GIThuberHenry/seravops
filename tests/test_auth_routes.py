from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.rate_limit import auth_rate_limiter
from app.core.security import create_access_token
from app.db import get_db
from app.main import create_app
from app.models import User
from app.models.enums import UserRole


@pytest.fixture
def app_with_db(session_factory):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    auth_rate_limiter.reset()
    yield
    auth_rate_limiter.reset()


@pytest.mark.asyncio
async def test_security_headers_present(app_with_db):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_db), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
        assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


@pytest.mark.asyncio
async def test_login_page_renders_with_google(app_with_db):
    with patch("app.routers.auth.google_auth_service.is_google_auth_configured", return_value=True):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db), base_url="http://test"
        ) as client:
            resp = await client.get("/login")
            assert resp.status_code == 200
            assert "Sign in with Google" in resp.text
            assert 'href="/login/google"' in resp.text


@pytest.mark.asyncio
async def test_login_page_renders_local_auth_when_enabled(app_with_db):
    with (
        patch("app.routers.auth.google_auth_service.is_google_auth_configured", return_value=False),
        patch("app.routers.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = Settings(enable_local_auth=True)
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db), base_url="http://test"
        ) as client:
            resp = await client.get("/login")
            assert resp.status_code == 200
            assert "Sign in with Google" not in resp.text
            assert 'name="username"' in resp.text


@pytest.mark.asyncio
async def test_login_page_hides_local_auth_when_disabled(app_with_db):
    with (
        patch("app.routers.auth.google_auth_service.is_google_auth_configured", return_value=True),
        patch("app.routers.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = Settings(
            enable_local_auth=False, google_client_id="id", google_client_secret="sec"
        )
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db), base_url="http://test"
        ) as client:
            resp = await client.get("/login")
            assert resp.status_code == 200
            assert "Sign in with Google" in resp.text
            assert 'name="username"' not in resp.text


@pytest.mark.asyncio
async def test_login_google_redirects_to_auth_url(app_with_db):
    with (
        patch("app.routers.auth.google_auth_service.is_google_auth_configured", return_value=True),
        patch("app.routers.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = Settings(
            google_client_id="dummy_client",
            google_client_secret="dummy_secret",
        )
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            resp = await client.get("/login/google")
            assert resp.status_code == 303
            assert "accounts.google.com" in resp.headers["location"]
            assert "oauth_state" in resp.cookies


@pytest.mark.asyncio
async def test_google_callback_csrf_mismatch(app_with_db):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_db),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        client.cookies.set("oauth_state", "real_state")
        resp = await client.get("/login/google/callback?code=abc&state=fake_state")
        assert resp.status_code == 303
        assert "/login?error=" in resp.headers["location"]
        assert "Invalid" in resp.headers["location"]


@pytest.mark.asyncio
async def test_google_callback_success(app_with_db, session_factory):
    async with session_factory() as session:
        invited_user = User(
            username="engineer",
            email="engineer@gmail.com",
            role=UserRole.DEVELOPER,
        )
        session.add(invited_user)
        await session.commit()

    with patch(
        "app.routers.auth.google_auth_service.exchange_code_for_user_info",
        new_callable=AsyncMock,
        return_value={"sub": "g-100", "email": "engineer@gmail.com", "name": "Engineer"},
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            client.cookies.set("oauth_state", "valid_state_123")
            resp = await client.get("/login/google/callback?code=valid_code&state=valid_state_123")
            assert resp.status_code == 303
            assert resp.headers["location"] == "/services"
            assert "access_token" in resp.cookies


@pytest.mark.asyncio
async def test_google_callback_uninvited_user_rejected(app_with_db):
    with patch(
        "app.routers.auth.google_auth_service.exchange_code_for_user_info",
        new_callable=AsyncMock,
        return_value={"sub": "g-uninvited", "email": "stranger@gmail.com", "name": "Stranger"},
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            client.cookies.set("oauth_state", "valid_state_123")
            resp = await client.get("/login/google/callback?code=valid_code&state=valid_state_123")
            assert resp.status_code == 303
            assert "/login?error=" in resp.headers["location"]
            assert "not" in resp.headers["location"] and "invited" in resp.headers["location"]
            assert "access_token" not in resp.cookies


@pytest.mark.asyncio
async def test_login_disabled_local_auth(app_with_db):
    with patch("app.routers.auth.get_settings") as mock_settings:
        mock_settings.return_value = Settings(enable_local_auth=False)
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db),
            base_url="http://test",
        ) as client:
            resp = await client.post("/login", data={"username": "admin", "password": "any"})
            assert resp.status_code == 400
            assert "Username/password login is disabled" in resp.text


@pytest.mark.asyncio
async def test_rate_limiter_triggers_429(app_with_db):
    with patch("app.routers.auth.google_auth_service.is_google_auth_configured", return_value=True):
        async with AsyncClient(
            transport=ASGITransport(app=app_with_db),
            base_url="http://test",
            follow_redirects=False,
        ) as client:
            # First 15 attempts succeed (303 redirect to Google)
            for _ in range(15):
                resp = await client.get("/login/google")
                assert resp.status_code == 303

            # 16th attempt should hit rate limit
            resp = await client.get("/login/google")
            assert resp.status_code == 429
            assert "Too many authentication attempts" in resp.text


@pytest.mark.asyncio
async def test_ip_whitelisting_enforcement(session_factory):
    app = create_app()

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    async with session_factory() as session:
        # Create user with restricted allowed_ips (192.168.1.0/24)
        user = User(
            username="whitelisted_user",
            email="whitelist@gmail.com",
            role=UserRole.ADMIN,
            allowed_ips="192.168.1.0/24, 10.0.0.5",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        token = create_access_token(user)

    # 1. Request from allowed IP (192.168.1.50 via X-Forwarded-For) -> 200
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "192.168.1.50"},
    ) as client:
        resp = await client.get("/services")
        assert resp.status_code == 200

    # 2. Request from forbidden IP (203.0.113.195 via X-Forwarded-For) -> 403
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}", "X-Forwarded-For": "203.0.113.195"},
    ) as client:
        resp = await client.get("/services")
        assert resp.status_code == 403
        assert "Access denied: IP address 203.0.113.195 is not authorized" in resp.text
