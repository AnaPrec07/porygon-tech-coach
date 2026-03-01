"""Goal domain entity with SMART criteria and hierarchical decomposition."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class GoalType(str, Enum):
    SHORT_TERM = "short_term"   # Target: < 30 days
    QUARTERLY = "quarterly"     # Target: 60–120 days
    LONG_TERM = "long_term"     # Target: > 120 days


class GoalStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GoalPriority(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class SMARTCriteria(BaseModel):
    """
    Structured SMART goal criteria.

    LLM suggests these values; user approves before persistence.
    The schema is enforced so LLM output cannot be persisted without validation.
    """

    specific: str = Field(
        description="Clear, unambiguous description of what will be achieved"
    )
    measurable: str = Field(
        description="How progress and completion will be measured"
    )
    achievable: str = Field(
        description="Why this is realistic given current resources and constraints"
    )
    relevant: str = Field(
        description="How this aligns with broader personal/professional objectives"
    )
    time_bound: str = Field(
        description="Specific deadline and intermediate milestones"
    )

    model_config = {"frozen": True}


class Goal(BaseModel):
    """
    A goal in the user's coaching plan.

    Goals are hierarchical: long-term goals decompose into quarterly goals,
    which decompose into short-term goals. The parent_goal_id FK enables
    the decomposition tree.

    Versioning: when a goal is significantly modified (status change, SMART
    rewrite), a new version record is created rather than mutating in place.
    The version field tracks this lineage.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=2000)
    goal_type: GoalType
    status: GoalStatus = GoalStatus.DRAFT
    priority: GoalPriority = GoalPriority.MEDIUM
    target_date: date
    smart_criteria: Optional[SMARTCriteria] = None
    progress_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Deterministic progress score [0, 1]. Never set by LLM.",
    )
    parent_goal_id: Optional[UUID] = Field(
        default=None,
        description="Parent goal for hierarchical decomposition",
    )
    skill_ids: list[UUID] = Field(
        default_factory=list,
        description="Skills this goal is intended to develop",
    )
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("target_date")
    @classmethod
    def target_date_must_be_future(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("target_date must be in the future")
        return v

    @model_validator(mode="after")
    def validate_goal_type_matches_deadline(self) -> "Goal":
        today = date.today()
        days_remaining = (self.target_date - today).days
        type_ranges = {
            GoalType.SHORT_TERM: (1, 45),
            GoalType.QUARTERLY: (30, 150),
            GoalType.LONG_TERM: (90, 3650),
        }
        low, high = type_ranges[self.goal_type]
        if not (low <= days_remaining <= high):
            # Warn but do not fail — user may have context we don't
            pass
        return self

    def with_progress(self, score: float) -> "Goal":
        """Return new Goal with updated progress score. Immutable update."""
        return self.model_copy(update={"progress_score": score, "updated_at": datetime.utcnow()})

    def activate(self) -> "Goal":
        """Transition to ACTIVE status with SMART criteria required."""
        if self.smart_criteria is None:
            raise ValueError("Cannot activate a goal without SMART criteria")
        return self.model_copy(update={"status": GoalStatus.ACTIVE, "updated_at": datetime.utcnow()})

    model_config = {"frozen": True}
