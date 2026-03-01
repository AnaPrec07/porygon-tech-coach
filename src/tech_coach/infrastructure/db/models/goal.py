"""SQLAlchemy ORM model for Goals."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from tech_coach.infrastructure.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GoalORM(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Production-grade schema for user goals.

    Indexing strategy:
      - (user_id, status): primary filter pattern
      - (user_id, goal_type, status): filter by type
      - (parent_goal_id): decomposition tree traversal
      - (target_date): deadline queries
    """

    __tablename__ = "goals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    smart_criteria: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    progress_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    parent_goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    skill_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Relationships
    user = relationship("UserORM", back_populates="goals")
    children = relationship(
        "GoalORM",
        foreign_keys=[parent_goal_id],
        back_populates="parent",
        lazy="select",
    )
    parent = relationship(
        "GoalORM",
        foreign_keys=[parent_goal_id],
        back_populates="children",
        remote_side="GoalORM.id",
    )
    behavioral_signals = relationship("BehavioralSignalORM", back_populates="goal")

    __table_args__ = (
        Index("ix_goals_user_status", "user_id", "status"),
        Index("ix_goals_user_type_status", "user_id", "goal_type", "status"),
        Index("ix_goals_target_date", "target_date"),
    )
