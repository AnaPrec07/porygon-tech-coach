"""
SQLAlchemy ORM models for EvaluationLog and PromptVersion.

These tables are the backbone of the evaluation-driven development workflow.
Every LLM call produces an EvaluationLog record. PromptVersion tracks all
deployed prompt versions with their evaluation scores.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tech_coach.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PromptVersionORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Tracks all prompt versions with their evaluation outcomes.

    A prompt version is promoted to 'production' only after:
      1. Offline eval score >= threshold (EVAL_PASS_THRESHOLD)
      2. Guardrail evaluation passes
      3. Manual review (for MAJOR version bumps)

    Indexing:
      - (prompt_name, version): lookup by name + version
      - (is_production): active production prompt lookup
    """

    __tablename__ = "prompt_versions"

    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256 of the system prompt content for change detection",
    )
    eval_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eval_passed: Mapped[Optional[bool]] = mapped_column(nullable=True)
    is_production: Mapped[bool] = mapped_column(nullable=False, default=False)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    deprecated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    evaluation_logs = relationship("EvaluationLogORM", back_populates="prompt_version")

    __table_args__ = (
        Index("ix_prompt_versions_name_version", "prompt_name", "version", unique=True),
        Index("ix_prompt_versions_production", "is_production"),
    )


class EvaluationLogORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One record per LLM call. Analytics-ready.

    This table answers:
      - What is the average latency per prompt version?
      - What is the token cost breakdown by prompt name?
      - Which sessions had low eval scores (indicating degraded quality)?
      - What is the error rate by model version?

    Indexing:
      - (user_id, created_at): per-user cost analysis
      - (prompt_version_id, created_at): per-version quality tracking
      - (trace_id): join with Cloud Trace
      - (session_id): session-level cost rollup
    """

    __tablename__ = "evaluation_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coaching_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Identity
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)

    # Usage metrics
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False)

    # Quality signals
    eval_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(nullable=False, default=False)
    error_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Context (no PII — content hashes only)
    input_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256 of input context for deduplication and caching",
    )
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Relationships
    prompt_version_record = relationship("PromptVersionORM", back_populates="evaluation_logs")
    session = relationship("CoachingSessionORM", back_populates="evaluation_logs")

    __table_args__ = (
        Index("ix_eval_logs_user_created", "user_id", "created_at"),
        Index("ix_eval_logs_prompt_version_created", "prompt_version_id", "created_at"),
        Index("ix_eval_logs_trace_id", "trace_id"),
        Index("ix_eval_logs_session_id", "session_id"),
    )
