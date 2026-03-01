"""Coaching session domain entity."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class SessionType(str, Enum):
    GOAL_SETTING = "goal_setting"
    WEEKLY_PLANNING = "weekly_planning"
    REFLECTION = "reflection"
    OPEN_COACHING = "open_coaching"
    SKILL_BUILDING = "skill_building"


class Message(BaseModel):
    """A single turn in a coaching session."""

    id: UUID = Field(default_factory=uuid4)
    role: str = Field(description="'user' or 'assistant'")
    content: str
    prompt_version: Optional[str] = Field(
        default=None,
        description="Prompt version used to generate this response (assistant only)",
    )
    token_usage: Optional[dict[str, int]] = Field(
        default=None,
        description="{'input_tokens': N, 'output_tokens': N} (assistant only)",
    )
    estimated_cost_usd: Optional[float] = Field(
        default=None,
        description="Estimated cost in USD for this response (assistant only)",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class CoachingSession(BaseModel):
    """
    A coaching session containing the full message history.

    When the session exceeds the active window (default: 10 messages),
    older messages are summarized and stored in summary_text. The
    summary is injected as compressed context in subsequent turns.

    Active window is managed by the application layer, not persisted here.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    session_type: SessionType
    status: SessionStatus = SessionStatus.ACTIVE
    goal_ids: list[UUID] = Field(
        default_factory=list,
        description="Goals discussed in this session",
    )
    messages: list[Message] = Field(default_factory=list)
    summary_text: Optional[str] = Field(
        default=None,
        description=(
            "LLM-generated summary of messages that fell outside the active window. "
            "Used as compressed context injection."
        ),
    )
    embedding: Optional[list[float]] = Field(
        default=None,
        description=(
            "Session-level embedding for semantic retrieval. "
            "Computed from summary_text or full content if short."
        ),
    )
    total_tokens_used: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds()

    @property
    def active_window_messages(self, window_size: int = 10) -> list[Message]:
        """Return the most recent N messages for context injection."""
        return self.messages[-window_size:]

    model_config = {"frozen": True}
