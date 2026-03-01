"""SQLAlchemy ORM model for CoachingSessions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tech_coach.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CoachingSessionORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Coaching session schema with pgvector support for semantic search.

    The `embedding` column uses pgvector for semantic retrieval of past sessions.
    This enables the LLM to receive relevant historical context when coaching.

    Indexing:
      - (user_id, session_type, started_at): timeline queries
      - (user_id, status): active session lookup
      - embedding: HNSW index for ANN search (created in migration)
    """

    __tablename__ = "coaching_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    goal_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # pgvector: 768-dim embeddings from text-embedding-004
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(768),
        nullable=True,
        comment="Session embedding for semantic retrieval via pgvector",
    )

    total_tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("UserORM", back_populates="sessions")
    evaluation_logs = relationship("EvaluationLogORM", back_populates="session")

    __table_args__ = (
        Index("ix_sessions_user_type_started", "user_id", "session_type", "started_at"),
        Index("ix_sessions_user_status", "user_id", "status"),
        # HNSW vector index is created in migration with:
        # CREATE INDEX ON coaching_sessions USING hnsw (embedding vector_cosine_ops)
        # WITH (m = 16, ef_construction = 64);
    )
