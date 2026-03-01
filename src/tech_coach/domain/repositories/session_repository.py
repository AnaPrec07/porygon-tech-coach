"""Abstract repository interface for CoachingSessions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from tech_coach.domain.models.coaching_session import CoachingSession, SessionType


class SessionRepository(ABC):

    @abstractmethod
    async def save(self, session: CoachingSession) -> CoachingSession:
        ...

    @abstractmethod
    async def get_by_id(self, session_id: UUID, user_id: UUID) -> Optional[CoachingSession]:
        ...

    @abstractmethod
    async def get_recent(
        self,
        user_id: UUID,
        limit: int = 10,
        session_type: Optional[SessionType] = None,
    ) -> list[CoachingSession]:
        """Return recent sessions ordered by started_at DESC."""
        ...

    @abstractmethod
    async def search_semantic(
        self,
        user_id: UUID,
        query_embedding: list[float],
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> list[CoachingSession]:
        """
        Vector similarity search over session embeddings (pgvector).

        Used to inject semantically relevant past sessions as context.
        Only sessions with non-null embedding are searched.
        """
        ...

    @abstractmethod
    async def update_summary(
        self,
        session_id: UUID,
        user_id: UUID,
        summary_text: str,
        embedding: list[float],
    ) -> CoachingSession:
        """Update the session summary and its embedding after window overflow."""
        ...
