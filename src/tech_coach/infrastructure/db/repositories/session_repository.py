"""SQLAlchemy implementation of SessionRepository with pgvector semantic search."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tech_coach.domain.models.coaching_session import CoachingSession, Message, SessionType
from tech_coach.domain.repositories.session_repository import SessionRepository
from tech_coach.infrastructure.db.models.coaching_session import CoachingSessionORM


class SQLAlchemySessionRepository(SessionRepository):

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, session: CoachingSession) -> CoachingSession:
        result = await self._session.get(CoachingSessionORM, session.id)
        orm_dict = self._to_orm_dict(session)
        if result is None:
            orm = CoachingSessionORM(id=session.id, user_id=session.user_id, **orm_dict)
            self._session.add(orm)
        else:
            for k, v in orm_dict.items():
                setattr(result, k, v)
        await self._session.flush()
        return session

    async def get_by_id(self, session_id: UUID, user_id: UUID) -> Optional[CoachingSession]:
        stmt = select(CoachingSessionORM).where(
            CoachingSessionORM.id == session_id,
            CoachingSessionORM.user_id == user_id,
        )
        result = await self._session.scalar(stmt)
        return self._to_domain(result) if result else None

    async def get_recent(
        self,
        user_id: UUID,
        limit: int = 10,
        session_type: Optional[SessionType] = None,
    ) -> list[CoachingSession]:
        stmt = (
            select(CoachingSessionORM)
            .where(CoachingSessionORM.user_id == user_id)
            .order_by(desc(CoachingSessionORM.started_at))
            .limit(limit)
        )
        if session_type:
            stmt = stmt.where(CoachingSessionORM.session_type == session_type.value)
        results = (await self._session.scalars(stmt)).all()
        return [self._to_domain(r) for r in results]

    async def search_semantic(
        self,
        user_id: UUID,
        query_embedding: list[float],
        limit: int = 5,
        min_similarity: float = 0.7,
    ) -> list[CoachingSession]:
        """
        pgvector cosine similarity search over session embeddings.

        Uses the <=> operator (cosine distance). Lower distance = higher similarity.
        Distance threshold: 1 - min_similarity (cosine distance).
        """
        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        stmt = text(
            """
            SELECT id FROM coaching_sessions
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
              AND (embedding <=> :embedding::vector) < :threshold
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
            """
        ).bindparams(
            user_id=str(user_id),
            embedding=embedding_str,
            threshold=1.0 - min_similarity,
            limit=limit,
        )
        rows = (await self._session.execute(stmt)).fetchall()
        sessions = []
        for row in rows:
            s = await self._session.get(CoachingSessionORM, row[0])
            if s:
                sessions.append(self._to_domain(s))
        return sessions

    async def update_summary(
        self,
        session_id: UUID,
        user_id: UUID,
        summary_text: str,
        embedding: list[float],
    ) -> CoachingSession:
        result = await self._session.get(CoachingSessionORM, session_id)
        if result is None or result.user_id != user_id:
            raise ValueError(f"Session {session_id} not found")
        result.summary_text = summary_text
        result.embedding = embedding
        await self._session.flush()
        return self._to_domain(result)

    def _to_orm_dict(self, session: CoachingSession) -> dict:
        return {
            "session_type": session.session_type.value,
            "status": session.status.value,
            "goal_ids": [str(gid) for gid in session.goal_ids],
            "messages": [m.model_dump(mode="json") for m in session.messages],
            "summary_text": session.summary_text,
            "embedding": session.embedding,
            "total_tokens_used": session.total_tokens_used,
            "total_cost_usd": session.total_cost_usd,
            "metadata": session.metadata,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "updated_at": session.updated_at,
        }

    def _to_domain(self, orm: CoachingSessionORM) -> CoachingSession:
        from tech_coach.domain.models.coaching_session import SessionStatus
        messages = [Message(**m) for m in (orm.messages or [])]
        return CoachingSession(
            id=orm.id,
            user_id=orm.user_id,
            session_type=SessionType(orm.session_type),
            status=SessionStatus(orm.status),
            goal_ids=[UUID(gid) for gid in (orm.goal_ids or [])],
            messages=messages,
            summary_text=orm.summary_text,
            embedding=orm.embedding,
            total_tokens_used=orm.total_tokens_used,
            total_cost_usd=orm.total_cost_usd,
            metadata=orm.metadata or {},
            started_at=orm.started_at,
            ended_at=orm.ended_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )
