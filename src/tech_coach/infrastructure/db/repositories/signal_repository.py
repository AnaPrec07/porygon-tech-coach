"""SQLAlchemy implementation of SignalRepository."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, String, desc, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.infrastructure.db.base import Base, UUIDPrimaryKeyMixin


class BehavioralSignalORM(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "behavioral_signals"

    from sqlalchemy import DateTime
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    goal_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("goals.id", ondelete="SET NULL"), nullable=True
    )
    session_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("coaching_sessions.id", ondelete="SET NULL"), nullable=True
    )
    plan_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    intensity: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        __import__("sqlalchemy").DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        __import__("sqlalchemy").DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_signals_user_recorded", "user_id", "recorded_at"),
        Index("ix_signals_user_type", "user_id", "signal_type"),
    )


class SQLAlchemySignalRepository(SignalRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, signal: BehavioralSignal) -> BehavioralSignal:
        orm = BehavioralSignalORM(
            id=signal.id,
            user_id=signal.user_id,
            signal_type=signal.signal_type.value,
            goal_id=signal.goal_id,
            session_id=signal.session_id,
            plan_id=signal.plan_id,
            intensity=signal.intensity,
            metadata=signal.metadata,
            recorded_at=signal.recorded_at,
        )
        self._session.add(orm)
        await self._session.flush()
        return signal

    async def save_batch(self, signals: list[BehavioralSignal]) -> list[BehavioralSignal]:
        for signal in signals:
            await self.save(signal)
        return signals

    async def get_by_user_since(
        self,
        user_id: UUID,
        since: datetime,
        signal_types: list[SignalType] | None = None,
    ) -> list[BehavioralSignal]:
        stmt = select(BehavioralSignalORM).where(
            BehavioralSignalORM.user_id == user_id,
            BehavioralSignalORM.recorded_at >= since,
        )
        if signal_types:
            stmt = stmt.where(
                BehavioralSignalORM.signal_type.in_([s.value for s in signal_types])
            )
        stmt = stmt.order_by(desc(BehavioralSignalORM.recorded_at))
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def get_completion_rate(
        self, user_id: UUID, since: datetime, until: datetime
    ) -> float:
        completed = await self._session.scalar(
            select(func.count()).where(
                BehavioralSignalORM.user_id == user_id,
                BehavioralSignalORM.signal_type == SignalType.TASK_COMPLETED.value,
                BehavioralSignalORM.recorded_at.between(since, until),
            )
        )
        missed = await self._session.scalar(
            select(func.count()).where(
                BehavioralSignalORM.user_id == user_id,
                BehavioralSignalORM.signal_type.in_([
                    SignalType.TASK_SKIPPED.value,
                    SignalType.TASK_OVERDUE.value,
                ]),
                BehavioralSignalORM.recorded_at.between(since, until),
            )
        )
        total = (completed or 0) + (missed or 0)
        return (completed or 0) / total if total > 0 else 1.0

    async def get_for_goal(
        self, goal_id: UUID, user_id: UUID, since: datetime
    ) -> list[BehavioralSignal]:
        stmt = select(BehavioralSignalORM).where(
            BehavioralSignalORM.goal_id == goal_id,
            BehavioralSignalORM.user_id == user_id,
            BehavioralSignalORM.recorded_at >= since,
        )
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    def _to_domain(self, orm: BehavioralSignalORM) -> BehavioralSignal:
        return BehavioralSignal(
            id=orm.id,
            user_id=orm.user_id,
            signal_type=SignalType(orm.signal_type),
            goal_id=orm.goal_id,
            session_id=orm.session_id,
            plan_id=orm.plan_id,
            intensity=orm.intensity,
            metadata=orm.metadata or {},
            recorded_at=orm.recorded_at,
        )
