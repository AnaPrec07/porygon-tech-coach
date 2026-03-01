"""Abstract repository interface for WeeklyPlans."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional
from uuid import UUID

from tech_coach.domain.models.weekly_plan import Task, TaskStatus, WeeklyPlan


class PlanRepository(ABC):

    @abstractmethod
    async def save(self, plan: WeeklyPlan) -> WeeklyPlan:
        ...

    @abstractmethod
    async def get_by_id(self, plan_id: UUID, user_id: UUID) -> Optional[WeeklyPlan]:
        ...

    @abstractmethod
    async def get_for_week(
        self, user_id: UUID, week_start: date
    ) -> Optional[WeeklyPlan]:
        """Return the plan for the given week start date (Monday)."""
        ...

    @abstractmethod
    async def get_recent(self, user_id: UUID, limit: int = 8) -> list[WeeklyPlan]:
        """Return recent plans ordered by week_start DESC."""
        ...

    @abstractmethod
    async def update_task_status(
        self,
        plan_id: UUID,
        task_id: UUID,
        user_id: UUID,
        status: TaskStatus,
        actual_minutes: Optional[int] = None,
    ) -> Task:
        """Update an individual task's status and actual time."""
        ...

    @abstractmethod
    async def get_completion_stats(
        self,
        user_id: UUID,
        weeks: int = 4,
    ) -> list[dict]:
        """
        Return per-week completion stats for the past N weeks.

        Returns list of:
          {"week_start": date, "planned": int, "completed": int, "rate": float}
        """
        ...
