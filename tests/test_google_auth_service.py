from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.models import User
from app.models.enums import UserRole
from app.services import google_auth_service


def test_is_google_auth_configured():
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(google_client_id="", google_client_secret="")
        assert not google_auth_service.is_google_auth_configured()

        mock_settings.return_value = Settings(
            google_client_id="my-id", google_client_secret="my-secret"
        )
        assert google_auth_service.is_google_auth_configured()


def test_generate_state_token():
    s1 = google_auth_service.generate_state_token()
    s2 = google_auth_service.generate_state_token()
    assert len(s1) >= 32
    assert s1 != s2


def test_build_authorization_url():
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            google_client_id="test-client-id", google_client_secret="test-secret"
        )
        url = google_auth_service.build_authorization_url(
            "http://localhost:7372/callback", "state123"
        )
        assert "accounts.google.com" in url
        assert "client_id=test-client-id" in url
        assert "state=state123" in url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A7372%2Fcallback" in url


def test_validate_email_allowed():
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        # Open to all
        mock_settings.return_value = Settings(google_allowed_domains="", google_allowed_emails="")
        assert google_auth_service.validate_email_allowed("user@example.com")
        assert google_auth_service.validate_email_allowed("any@corp.org")

        # Restrict domains
        mock_settings.return_value = Settings(
            google_allowed_domains="company.com, partner.org", google_allowed_emails=""
        )
        assert google_auth_service.validate_email_allowed("alice@company.com")
        assert google_auth_service.validate_email_allowed("bob@partner.org")
        assert not google_auth_service.validate_email_allowed("evil@gmail.com")

        # Restrict specific emails
        mock_settings.return_value = Settings(
            google_allowed_domains="", google_allowed_emails="admin@gmail.com"
        )
        assert google_auth_service.validate_email_allowed("admin@gmail.com")
        assert not google_auth_service.validate_email_allowed("other@gmail.com")


@pytest.mark.asyncio
async def test_get_or_create_google_user_initial_admin(session_factory):
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            initial_admin_email="superadmin@gmail.com",
            google_auto_provision=False,
            google_allowed_domains="",
            google_allowed_emails="",
        )
        async with session_factory() as session:
            user_info = {
                "sub": "g-superadmin",
                "email": "superadmin@gmail.com",
                "name": "Super Admin",
            }
            user = await google_auth_service.get_or_create_google_user(session, user_info)
            assert user.id is not None
            assert user.email == "superadmin@gmail.com"
            assert user.google_id == "g-superadmin"
            assert user.role == UserRole.ADMIN
            assert user.password_hash is None


@pytest.mark.asyncio
async def test_get_or_create_google_user_invited(session_factory):
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            initial_admin_email="",
            google_auto_provision=False,
            google_allowed_domains="",
            google_allowed_emails="",
        )
        async with session_factory() as session:
            # Pre-registered / invited by admin
            invited = User(
                username="colleague",
                email="colleague@gmail.com",
                role=UserRole.DEVELOPER,
                password_hash=None,
            )
            session.add(invited)
            await session.commit()

            user_info = {
                "sub": "g-colleague-123",
                "email": "colleague@gmail.com",
                "name": "Colleague",
            }
            user = await google_auth_service.get_or_create_google_user(session, user_info)
            assert user.id == invited.id
            assert user.google_id == "g-colleague-123"
            assert user.role == UserRole.DEVELOPER


@pytest.mark.asyncio
async def test_get_or_create_google_user_uninvited_rejected(session_factory):
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            initial_admin_email="admin@gmail.com",
            google_auto_provision=False,
            google_allowed_domains="",
            google_allowed_emails="",
        )
        async with session_factory() as session:
            user_info = {
                "sub": "g-stranger-456",
                "email": "stranger@gmail.com",
                "name": "Stranger",
            }
            with pytest.raises(HTTPException) as exc_info:
                await google_auth_service.get_or_create_google_user(session, user_info)
            assert exc_info.value.status_code == 403
            assert "not been invited" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_or_create_google_user_auto_provision_enabled(session_factory):
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            initial_admin_email="",
            google_auto_provision=True,
            google_allowed_domains="",
            google_allowed_emails="",
        )
        async with session_factory() as session:
            user_info = {
                "sub": "google-12345",
                "email": "developer@gmail.com",
                "name": "Dev Person",
            }
            user = await google_auth_service.get_or_create_google_user(session, user_info)
            assert user.id is not None
            assert user.email == "developer@gmail.com"
            assert user.google_id == "google-12345"
            assert user.role == UserRole.DEVELOPER
            assert user.password_hash is None


@pytest.mark.asyncio
async def test_get_or_create_google_user_existing_google_id(session_factory):
    async with session_factory() as session:
        existing = User(
            username="existing_dev",
            email="dev@gmail.com",
            google_id="google-9999",
            role=UserRole.DEVELOPER,
        )
        session.add(existing)
        await session.commit()

        user_info = {
            "sub": "google-9999",
            "email": "dev@gmail.com",
            "name": "Existing Dev",
        }
        user = await google_auth_service.get_or_create_google_user(session, user_info)
        assert user.id == existing.id
        assert user.username == "existing_dev"


@pytest.mark.asyncio
async def test_get_or_create_google_user_domain_blocked(session_factory):
    with patch("app.services.google_auth_service.get_settings") as mock_settings:
        mock_settings.return_value = Settings(google_allowed_domains="company.com")
        async with session_factory() as session:
            user_info = {"sub": "google-111", "email": "stranger@gmail.com"}
            with pytest.raises(HTTPException) as exc_info:
                await google_auth_service.get_or_create_google_user(session, user_info)
            assert exc_info.value.status_code == 403
