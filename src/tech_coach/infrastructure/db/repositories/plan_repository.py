"""SQLAlchemy implementation of PlanRepository."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text, desc, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from tech_coach.domain.models.weekly_plan import (
    CognitiveLoad, Task, TaskStatus, WeeklyPlan,
)
from tech_coach.domain.repositories.plan_repository import PlanRepository
from tech_coach.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WeeklyPlanORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "weekly_plans"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    capacity_hours: Mapped[float] = mapped_column(Float, nullable=False)
    goal_allocations: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    burnout_risk_at_creation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    focus_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    completion_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SQLAlchemyPlanRepository(PlanRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, plan: WeeklyPlan) -> WeeklyPlan:
        result = await self._session.get(WeeklyPlanORM, plan.id)
        orm_dict = self._to_orm_dict(plan)
        if result is None:
            orm = WeeklyPlanORM(id=plan.id, user_id=plan.user_id, **orm_dict)
            self._session.add(orm)
        else:
            for k, v in orm_dict.items():
                setattr(result, k, v)
        await self._session.flush()
        return plan

    async def get_by_id(self, plan_id: UUID, user_id: UUID) -> Optional[WeeklyPlan]:
        stmt = select(WeeklyPlanORM).where(
            WeeklyPlanORM.id == plan_id, WeeklyPlanORM.user_id == user_id
        )
        result = await self._session.scalar(stmt)
        return self._to_domain(result) if result else None

    async def get_for_week(self, user_id: UUID, week_start: date) -> Optional[WeeklyPlan]:
        stmt = select(WeeklyPlanORM).where(
            WeeklyPlanORM.user_id == user_id,
            WeeklyPlanORM.week_start == week_start,
        )
        result = await self._session.scalar(stmt)
        return self._to_domain(result) if result else None

    async def get_recent(self, user_id: UUID, limit: int = 8) -> list[WeeklyPlan]:
        stmt = (
            select(WeeklyPlanORM)
            .where(WeeklyPlanORM.user_id == user_id)
            .order_by(desc(WeeklyPlanORM.week_start))
            .limit(limit)
        )
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def update_task_status(
        self,
        plan_id: UUID,
        task_id: UUID,
        user_id: UUID,
        status: TaskStatus,
        actual_minutes: Optional[int] = None,
    ) -> Task:
        result = await self._session.get(WeeklyPlanORM, plan_id)
        if result is None or result.user_id != user_id:
            raise ValueError(f"Plan {plan_id} not found")

        tasks = list(result.tasks or [])
        updated_task = None
        for i, t in enumerate(tasks):
            if t.get("id") == str(task_id):
                tasks[i]["status"] = status.value
                if actual_minutes is not None:
                    tasks[i]["actual_minutes"] = actual_minutes
                updated_task = Task(**tasks[i])
                break

        if updated_task is None:
            raise ValueError(f"Task {task_id} not found in plan {plan_id}")

        result.tasks = tasks
        await self._session.flush()
        return updated_task

    async def get_completion_stats(
        self, user_id: UUID, weeks: int = 4
    ) -> list[dict]:
        stmt = (
            select(WeeklyPlanORM)
            .where(WeeklyPlanORM.user_id == user_id)
            .order_by(desc(WeeklyPlanORM.week_start))
            .limit(weeks)
        )
        plans = (await self._session.scalars(stmt)).all()
        stats = []
        for plan in plans:
            tasks = plan.tasks or []
            total = len(tasks)
            completed = sum(1 for t in tasks if t.get("status") == "completed")
            rate = completed / total if total > 0 else 0.0
            stats.append({
                "week_start": plan.week_start,
                "planned": total,
                "completed": completed,
                "rate": round(rate, 4),
            })
        return stats

    def _to_orm_dict(self, plan: WeeklyPlan) -> dict:
        return {
            "week_start": plan.week_start,
            "week_end": plan.week_end,
            "tasks": [t.model_dump(mode="json") for t in plan.tasks],
            "capacity_hours": plan.capacity_hours,
            "goal_allocations": plan.goal_allocations,
            "burnout_risk_at_creation": plan.burnout_risk_at_creation,
            "focus_score": plan.focus_score,
            "llm_summary": plan.llm_summary,
            "completion_rate": plan.completion_rate,
            "version": plan.version,
            "updated_at": plan.updated_at,
        }

    def _to_domain(self, orm: WeeklyPlanORM) -> WeeklyPlan:
        tasks = []
        for t in (orm.tasks or []):
            try:
                tasks.append(Task(**t))
            except Exception:
                pass
        return WeeklyPlan(
            id=orm.id,
            user_id=orm.user_id,
            week_start=orm.week_start,
            week_end=orm.week_end,
            tasks=tasks,
            capacity_hours=orm.capacity_hours,
            goal_allocations=orm.goal_allocations or {},
            burnout_risk_at_creation=orm.burnout_risk_at_creation,
            focus_score=orm.focus_score,
            llm_summary=orm.llm_summary,
            completion_rate=orm.completion_rate,
            version=orm.version,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
