"""Abstract repository interface for BehavioralSignals."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType


class SignalRepository(ABC):
    """
    Abstract interface for BehavioralSignal persistence.

    Signals are append-only: they are never updated or deleted.
    Time-series queries over signals drive all deterministic scoring.
    """

    @abstractmethod
    async def save(self, signal: BehavioralSignal) -> BehavioralSignal:
        """Persist a new behavioral signal."""
        ...

    @abstractmethod
    async def save_batch(self, signals: list[BehavioralSignal]) -> list[BehavioralSignal]:
        """Persist multiple signals atomically (same DB transaction)."""
        ...

    @abstractmethod
    async def get_by_user_since(
        self,
        user_id: UUID,
        since: datetime,
        signal_types: list[SignalType] | None = None,
    ) -> list[BehavioralSignal]:
        """
        Return signals for a user since the given timestamp.

        Used by PlanningEngine for:
          - Burnout risk calculation (last 14 days)
          - Completion rate trend (last 7/14/30 days)
          - Overcommitment detection (last 7 days)
        """
        ...

    @abstractmethod
    async def get_completion_rate(
        self,
        user_id: UUID,
        since: datetime,
        until: datetime,
    ) -> float:
        """
        Compute the task completion rate for the given period.

        Returns: completed_tasks / (completed_tasks + skipped_tasks + overdue_tasks)
        Returns 1.0 if no tasks in the period (no penalty for inactivity).
        """
        ...

    @abstractmethod
    async def get_for_goal(
        self,
        goal_id: UUID,
        user_id: UUID,
        since: datetime,
    ) -> list[BehavioralSignal]:
        """Return signals associated with a specific goal."""
        ...
