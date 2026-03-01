"""SQLAlchemy implementation of UserRepository."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from tech_coach.domain.models.user import User
from tech_coach.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    google_sub: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SQLAlchemyUserRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, user: User) -> User:
        result = await self._session.get(UserORM, user.id)
        if result is None:
            orm = UserORM(
                id=user.id,
                email=str(user.email),
                display_name=user.display_name,
                google_sub=user.google_sub,
                is_active=user.is_active,
            )
            self._session.add(orm)
        else:
            result.email = str(user.email)
            result.display_name = user.display_name
            result.is_active = user.is_active
        await self._session.flush()
        return user

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        result = await self._session.get(UserORM, user_id)
        return self._to_domain(result) if result else None

    async def get_by_google_sub(self, google_sub: str) -> Optional[User]:
        stmt = select(UserORM).where(UserORM.google_sub == google_sub)
        result = await self._session.scalar(stmt)
        return self._to_domain(result) if result else None

    async def get_by_email(self, email: str) -> Optional[User]:
        stmt = select(UserORM).where(UserORM.email == email)
        result = await self._session.scalar(stmt)
        return self._to_domain(result) if result else None

    def _to_domain(self, orm: UserORM) -> User:
        return User(
            id=orm.id,
            email=orm.email,  # type: ignore[arg-type]
            display_name=orm.display_name,
            google_sub=orm.google_sub,
            is_active=orm.is_active,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
