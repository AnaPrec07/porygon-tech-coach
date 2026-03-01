"""JWT creation and validation for session management."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from jose import JWTError, jwt

from tech_coach.config import get_settings
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)


class TokenError(Exception):
    """Raised when a token is invalid, expired, or tampered."""


class JWTHandler:

    def __init__(self) -> None:
        self._settings = get_settings()

    def create_access_token(self, user_id: UUID, email: str) -> str:
        """
        Create a short-lived access token.

        Payload:
          sub: user_id (UUID string)
          email: user email (for display only — authoritative identity is sub)
          type: "access"
          exp: expiry timestamp

        Note: email is included for UI convenience but must never be used
        as the authoritative user identifier. Always use sub (user_id).
        """
        now = datetime.utcnow()
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "email": email,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(
                minutes=self._settings.jwt_access_token_expire_minutes
            ),
        }
        return jwt.encode(
            payload,
            self._settings.app_secret_key.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
        )

    def create_refresh_token(self, user_id: UUID) -> str:
        now = datetime.utcnow()
        payload: dict[str, Any] = {
            "sub": str(user_id),
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(days=self._settings.jwt_refresh_token_expire_days),
        }
        return jwt.encode(
            payload,
            self._settings.app_secret_key.get_secret_value(),
            algorithm=self._settings.jwt_algorithm,
        )

    def decode_access_token(self, token: str) -> dict[str, Any]:
        """
        Validate and decode an access token.

        Raises TokenError on any validation failure.
        Never logs the token itself.
        """
        try:
            payload = jwt.decode(
                token,
                self._settings.app_secret_key.get_secret_value(),
                algorithms=[self._settings.jwt_algorithm],
            )
        except JWTError as exc:
            logger.warning("jwt.validation.failed", error_type=type(exc).__name__)
            raise TokenError(f"Invalid token: {exc}") from exc

        if payload.get("type") != "access":
            raise TokenError("Token type must be 'access'")

        return payload

    def extract_user_id(self, token: str) -> UUID:
        """Decode token and return user_id (sub). Raises TokenError on failure."""
        payload = self.decode_access_token(token)
        try:
            return UUID(payload["sub"])
        except (KeyError, ValueError) as exc:
            raise TokenError("Token missing valid 'sub' claim") from exc
