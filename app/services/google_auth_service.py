import secrets
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User
from app.models.enums import UserRole

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def is_google_auth_configured() -> bool:
    settings = get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def generate_state_token() -> str:
    return secrets.token_urlsafe(32)


def get_redirect_uri(request: Request) -> str:
    settings = get_settings()
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    # Default to building the URL from the incoming request base_url
    return str(request.base_url).rstrip("/") + "/login/google/callback"


def build_authorization_url(redirect_uri: str, state: str) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_user_info(code: str, redirect_uri: str) -> dict:
    settings = get_settings()
    data = {
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(GOOGLE_TOKEN_URL, data=data)
        if token_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Google token exchange failed: {token_response.text}",
            )
        tokens = token_response.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing access_token from Google OAuth response",
            )

        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to fetch Google user profile: {userinfo_response.text}",
            )
        return userinfo_response.json()


def validate_email_allowed(email: str) -> bool:
    settings = get_settings()
    allowed_emails = {
        e.strip().lower() for e in settings.google_allowed_emails.split(",") if e.strip()
    }
    if allowed_emails and email.lower() not in allowed_emails:
        return False

    allowed_domains = {
        d.strip().lower() for d in settings.google_allowed_domains.split(",") if d.strip()
    }
    if allowed_domains:
        domain = email.lower().split("@")[-1]
        if domain not in allowed_domains:
            return False

    return True


async def get_or_create_google_user(db: AsyncSession, user_info: dict) -> User:
    settings = get_settings()
    google_id = str(user_info.get("sub", ""))
    email = str(user_info.get("email", "")).strip().lower()

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google account did not provide an email address",
        )

    if not validate_email_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your email domain or account is not authorized to access Seravops",
        )

    is_initial_admin = (
        bool(settings.initial_admin_email) and email == settings.initial_admin_email.strip().lower()
    )

    # 1. Check by google_id
    if google_id:
        user = await db.scalar(select(User).where(User.google_id == google_id))
        if user:
            if not user.email:
                user.email = email
            if is_initial_admin and user.role != UserRole.ADMIN:
                user.role = UserRole.ADMIN
            await db.commit()
            await db.refresh(user)
            return user

    # 2. Check by email (e.g. pre-registered/invited by admin)
    user = await db.scalar(select(User).where(User.email == email))
    if user:
        if google_id and not user.google_id:
            user.google_id = google_id
        if is_initial_admin and user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
        await db.commit()
        await db.refresh(user)
        return user

    # 3. Check by username matching email (for backward-compatibility)
    user = await db.scalar(select(User).where(User.username == email))
    if user:
        user.email = email
        if google_id and not user.google_id:
            user.google_id = google_id
        if is_initial_admin and user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
        await db.commit()
        await db.refresh(user)
        return user

    # 4. Bootstrap initial admin if matching initial_admin_email
    if is_initial_admin:
        new_admin = User(
            username=email,
            email=email,
            google_id=google_id or None,
            password_hash=None,
            role=UserRole.ADMIN,
        )
        db.add(new_admin)
        await db.commit()
        await db.refresh(new_admin)
        return new_admin

    # 5. User does not exist and was not invited: check auto-provisioning
    if not settings.google_auto_provision:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Your email has not been invited by an administrator.",
        )

    # Determine unique username
    username_candidate = email
    existing = await db.scalar(select(User).where(User.username == username_candidate))
    if existing:
        username_candidate = f"{email}_{secrets.token_hex(3)}"

    try:
        default_role = UserRole(settings.google_default_role)
    except ValueError:
        default_role = UserRole.DEVELOPER

    new_user = User(
        username=username_candidate,
        email=email,
        google_id=google_id or None,
        password_hash=None,
        role=default_role,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user
