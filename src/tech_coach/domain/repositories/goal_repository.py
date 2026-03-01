"""Abstract repository interface for Goals."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional
from uuid import UUID

from tech_coach.domain.models.goal import Goal, GoalStatus, GoalType


class GoalRepository(ABC):
    """
    Abstract interface for Goal persistence.

    Concrete implementations live in infrastructure.db.repositories.
    This interface belongs to the domain layer — it defines WHAT is
    needed without specifying HOW it's implemented.

    All methods are async to support async DB drivers (asyncpg).
    """

    @abstractmethod
    async def save(self, goal: Goal) -> Goal:
        """Persist a new goal or replace an existing one (upsert by id)."""
        ...

    @abstractmethod
    async def get_by_id(self, goal_id: UUID, user_id: UUID) -> Optional[Goal]:
        """Fetch a goal by ID, scoped to the authenticated user."""
        ...

    @abstractmethod
    async def get_active_by_user(
        self,
        user_id: UUID,
        goal_type: Optional[GoalType] = None,
    ) -> list[Goal]:
        """Return all active goals for a user, optionally filtered by type."""
        ...

    @abstractmethod
    async def get_by_status(
        self,
        user_id: UUID,
        status: GoalStatus,
    ) -> list[Goal]:
        """Return goals filtered by status, scoped to user."""
        ...

    @abstractmethod
    async def get_stagnant(
        self,
        user_id: UUID,
        no_progress_since: date,
    ) -> list[Goal]:
        """
        Return active goals with no progress update since the given date.
        Used by the planning engine for stagnation detection.
        """
        ...

    @abstractmethod
    async def get_children(self, parent_goal_id: UUID, user_id: UUID) -> list[Goal]:
        """Return child goals in the decomposition hierarchy."""
        ...

    @abstractmethod
    async def update_progress(
        self, goal_id: UUID, user_id: UUID, progress_score: float
    ) -> Goal:
        """
        Update the progress score only.
        Progress score is always computed deterministically — never from LLM output.
        """
        ...

    @abstractmethod
    async def delete(self, goal_id: UUID, user_id: UUID) -> None:
        """Soft-delete a goal (mark as abandoned, do not physically delete)."""
        ...
