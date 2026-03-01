"""
FastAPI dependency injection.

All shared resources (DB session, current user, repositories, use cases)
are provided through FastAPI's dependency injection system.

Design:
  - DB session is request-scoped (new session per request, committed on success)
  - Current user is extracted from JWT on every authenticated request
  - Repositories are instantiated per-request (lightweight, stateless)
  - Use cases are instantiated per-request using provided repositories
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from tech_coach.domain.models.user import User
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.domain.repositories.plan_repository import PlanRepository
from tech_coach.domain.repositories.session_repository import SessionRepository
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.infrastructure.auth.jwt_handler import JWTHandler, TokenError
from tech_coach.infrastructure.db.repositories.goal_repository import (
    SQLAlchemyGoalRepository,
)
from tech_coach.infrastructure.db.repositories.plan_repository import (
    SQLAlchemyPlanRepository,
)
from tech_coach.infrastructure.db.repositories.session_repository import (
    SQLAlchemySessionRepository,
)
from tech_coach.infrastructure.db.repositories.signal_repository import (
    SQLAlchemySignalRepository,
)
from tech_coach.infrastructure.db.session import get_db_session
from tech_coach.infrastructure.llm.vertex_client import VertexAIClient

security = HTTPBearer()
_jwt_handler = JWTHandler()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped async database session."""
    async with get_db_session() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Extract and validate the authenticated user from JWT.

    Raises 401 if token is invalid or expired.
    Raises 403 if user is not authorized (single-user mode).

    The User object is the authoritative identity for all downstream logic.
    user_id from this object must be passed to all repository calls.
    """
    try:
        user_id = _jwt_handler.extract_user_id(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    from tech_coach.infrastructure.db.repositories.user_repository import (
        SQLAlchemyUserRepository,
    )

    user_repo = SQLAlchemyUserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


def get_llm_client(request: Request) -> VertexAIClient:
    """Return the application-lifetime LLM client from app state."""
    return request.app.state.llm_client


# --- Repository dependencies ---

def get_goal_repository(db: AsyncSession = Depends(get_db)) -> GoalRepository:
    return SQLAlchemyGoalRepository(db)


def get_plan_repository(db: AsyncSession = Depends(get_db)) -> PlanRepository:
    return SQLAlchemyPlanRepository(db)


def get_session_repository(db: AsyncSession = Depends(get_db)) -> SessionRepository:
    return SQLAlchemySessionRepository(db)


def get_signal_repository(db: AsyncSession = Depends(get_db)) -> SignalRepository:
    return SQLAlchemySignalRepository(db)
