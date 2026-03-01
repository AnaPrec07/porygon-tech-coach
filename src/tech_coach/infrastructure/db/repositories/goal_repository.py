"""SQLAlchemy implementation of GoalRepository."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from tech_coach.domain.models.goal import Goal, GoalPriority, GoalStatus, GoalType, SMARTCriteria
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.infrastructure.db.models.goal import GoalORM


class SQLAlchemyGoalRepository(GoalRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, goal: Goal) -> Goal:
        result = await self._session.get(GoalORM, goal.id)
        if result is None:
            orm = self._to_orm(goal)
            self._session.add(orm)
        else:
            for field, value in self._to_orm_dict(goal).items():
                setattr(result, field, value)
        await self._session.flush()
        return goal

    async def get_by_id(self, goal_id: UUID, user_id: UUID) -> Optional[Goal]:
        stmt = select(GoalORM).where(
            GoalORM.id == goal_id,
            GoalORM.user_id == user_id,
        )
        result = await self._session.scalar(stmt)
        return self._to_domain(result) if result else None

    async def get_active_by_user(
        self,
        user_id: UUID,
        goal_type: Optional[GoalType] = None,
    ) -> list[Goal]:
        stmt = select(GoalORM).where(
            GoalORM.user_id == user_id,
            GoalORM.status == GoalStatus.ACTIVE.value,
        )
        if goal_type:
            stmt = stmt.where(GoalORM.goal_type == goal_type.value)
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def get_by_status(self, user_id: UUID, status: GoalStatus) -> list[Goal]:
        stmt = select(GoalORM).where(
            GoalORM.user_id == user_id,
            GoalORM.status == status.value,
        )
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def get_stagnant(self, user_id: UUID, no_progress_since: date) -> list[Goal]:
        stmt = select(GoalORM).where(
            GoalORM.user_id == user_id,
            GoalORM.status == GoalStatus.ACTIVE.value,
            GoalORM.updated_at < datetime.combine(no_progress_since, datetime.min.time()),
        )
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def get_children(self, parent_goal_id: UUID, user_id: UUID) -> list[Goal]:
        stmt = select(GoalORM).where(
            GoalORM.parent_goal_id == parent_goal_id,
            GoalORM.user_id == user_id,
        )
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def update_progress(
        self, goal_id: UUID, user_id: UUID, progress_score: float
    ) -> Goal:
        stmt = (
            update(GoalORM)
            .where(GoalORM.id == goal_id, GoalORM.user_id == user_id)
            .values(progress_score=progress_score, updated_at=datetime.utcnow())
            .returning(GoalORM)
        )
        result = await self._session.scalar(stmt)
        if result is None:
            raise ValueError(f"Goal {goal_id} not found")
        return self._to_domain(result)

    async def delete(self, goal_id: UUID, user_id: UUID) -> None:
        stmt = (
            update(GoalORM)
            .where(GoalORM.id == goal_id, GoalORM.user_id == user_id)
            .values(status=GoalStatus.ABANDONED.value, updated_at=datetime.utcnow())
        )
        await self._session.execute(stmt)

    def _to_orm(self, goal: Goal) -> GoalORM:
        return GoalORM(**self._to_orm_dict(goal), id=goal.id, user_id=goal.user_id)

    def _to_orm_dict(self, goal: Goal) -> dict:
        return {
            "title": goal.title,
            "description": goal.description,
            "goal_type": goal.goal_type.value,
            "status": goal.status.value,
            "priority": goal.priority.value,
            "target_date": goal.target_date,
            "smart_criteria": goal.smart_criteria.model_dump() if goal.smart_criteria else None,
            "progress_score": goal.progress_score,
            "parent_goal_id": goal.parent_goal_id,
            "skill_ids": [str(sid) for sid in goal.skill_ids],
            "version": goal.version,
            "updated_at": goal.updated_at,
        }

    def _to_domain(self, orm: GoalORM) -> Goal:
        smart = None
        if orm.smart_criteria:
            smart = SMARTCriteria(**orm.smart_criteria)
        return Goal(
            id=orm.id,
            user_id=orm.user_id,
            title=orm.title,
            description=orm.description,
            goal_type=GoalType(orm.goal_type),
            status=GoalStatus(orm.status),
            priority=GoalPriority(orm.priority),
            target_date=orm.target_date,
            smart_criteria=smart,
            progress_score=orm.progress_score,
            parent_goal_id=orm.parent_goal_id,
            skill_ids=[UUID(sid) for sid in (orm.skill_ids or [])],
            version=orm.version,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
