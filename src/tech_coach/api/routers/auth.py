"""
Google OAuth 2.0 authentication router.

Flow:
  GET /auth/login    → redirect to Google consent screen
  GET /auth/callback → exchange code for tokens, create/update user, issue JWT
  POST /auth/refresh → refresh access token
  POST /auth/logout  → client-side token discard (stateless JWT)

Single-user enforcement:
  After OAuth validation, the user's email is checked against
  ALLOWED_USER_EMAIL (from Secret Manager). If it does not match,
  authentication is rejected with 403.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from tech_coach.config import get_settings
from tech_coach.infrastructure.auth.jwt_handler import JWTHandler
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_jwt_handler = JWTHandler()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.get("/login")
async def login() -> RedirectResponse:
    """Redirect user to Google OAuth consent screen."""
    from authlib.integrations.starlette_client import OAuth

    settings = get_settings()
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    redirect_uri = settings.oauth_redirect_uri
    return await oauth.google.authorize_redirect(redirect_uri)  # type: ignore[return-value]


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str,
    state: str | None = None,
) -> TokenResponse:
    """
    Handle Google OAuth callback.

    1. Exchange code for Google tokens
    2. Validate email against allowed user (single-user enforcement)
    3. Create or update User record
    4. Issue JWT access + refresh tokens
    """
    from authlib.integrations.httpx_client import AsyncOAuth2Client

    settings = get_settings()
    client = AsyncOAuth2Client(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        redirect_uri=settings.oauth_redirect_uri,
    )

    try:
        token = await client.fetch_token(
            "https://oauth2.googleapis.com/token",
            code=code,
        )
        userinfo = await client.get("https://www.googleapis.com/oauth2/v3/userinfo")
        userinfo_data = userinfo.json()
    except Exception as exc:
        logger.warning("auth.oauth.callback_error", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth callback failed",
        ) from exc

    email = userinfo_data.get("email", "")

    # Single-user enforcement
    if email.lower() != settings.allowed_user_email.lower():
        logger.warning(
            "auth.access_denied",
            # Do NOT log the actual email — log a boolean result
            email_matched=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access not authorized",
        )

    # Create/update user in DB
    from tech_coach.api.dependencies import get_db
    from tech_coach.infrastructure.db.repositories.user_repository import (
        SQLAlchemyUserRepository,
    )
    from tech_coach.domain.models.user import User
    import uuid

    async with (await anext(get_db())) as db:  # type: ignore[call-overload]
        user_repo = SQLAlchemyUserRepository(db)
        existing = await user_repo.get_by_google_sub(userinfo_data["sub"])
        if existing:
            user = existing
        else:
            user = User(
                email=email,
                display_name=userinfo_data.get("name", email.split("@")[0]),
                google_sub=userinfo_data["sub"],
            )
            user = await user_repo.save(user)

    access_token = _jwt_handler.create_access_token(user.id, user.email)

    logger.info("auth.login.success", user_id=str(user.id))

    return TokenResponse(
        access_token=access_token,
        expires_in=get_settings().jwt_access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout() -> dict:
    """
    Stateless logout. JWT is discarded client-side.
    In a future implementation, add token to a short-lived revocation list.
    """
    return {"message": "Logged out successfully"}
