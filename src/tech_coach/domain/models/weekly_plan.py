"""Weekly plan and task domain entities."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    DEFERRED = "deferred"


class CognitiveLoad(str, Enum):
    """
    Used for ADHD-aware scheduling: alternate high/low load tasks.
    """
    DEEP_WORK = "deep_work"       # Requires sustained focus (>45 min)
    MEDIUM = "medium"              # Structured work (15–45 min)
    ADMIN = "admin"                # Low-cognitive overhead (<15 min)


class Task(BaseModel):
    """
    An atomic unit of work within a weekly plan.

    Tasks are generated with LLM assistance but finalized by the
    deterministic planning engine. LLM suggests title, description,
    estimated_minutes; the engine validates and assigns day/slot.
    """

    id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=1000)
    estimated_minutes: int = Field(ge=5, le=480)
    actual_minutes: Optional[int] = Field(default=None, ge=0)
    cognitive_load: CognitiveLoad = CognitiveLoad.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    scheduled_day: int = Field(
        ge=0,
        le=6,
        description="Day of week: 0=Monday, 6=Sunday",
    )
    order_in_day: int = Field(
        ge=0,
        description="Display order within scheduled day",
    )
    is_mit: bool = Field(
        default=False,
        description=(
            "Most Important Task flag. ADHD constraint: max 3 MITs per day. "
            "Set by planning engine, not LLM."
        ),
    )

    model_config = {"frozen": True}

    def complete(self, actual_minutes: int) -> "Task":
        return self.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "actual_minutes": actual_minutes,
            }
        )


class WeeklyPlan(BaseModel):
    """
    A structured weekly plan tying goals to concrete tasks with time allocation.

    capacity_hours: user-declared available hours for the week (excludes meetings,
    personal obligations). Used by planning engine as the hard budget constraint.

    total_planned_minutes: deterministic sum of task estimated_minutes.
    Must be <= capacity_hours * 60 (enforced by model validator).

    llm_summary: AI-generated narrative of the week's intent. Informational
    only — does not affect plan logic.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    week_start: date = Field(description="Monday of the plan week")
    week_end: date = Field(description="Sunday of the plan week")
    tasks: list[Task] = Field(default_factory=list)
    capacity_hours: float = Field(
        ge=1.0,
        le=80.0,
        description="User-declared weekly available hours",
    )
    goal_allocations: dict[str, float] = Field(
        default_factory=dict,
        description="goal_id -> allocated_hours, from planning engine",
    )
    burnout_risk_at_creation: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Burnout risk score at time of plan creation",
    )
    focus_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Aggregate focus score for the week",
    )
    llm_summary: Optional[str] = Field(
        default=None,
        description="AI-generated narrative (informational only)",
    )
    completion_rate: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Computed at week end: completed tasks / total tasks",
    )
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def validate_week_dates(self) -> "WeeklyPlan":
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")
        if (self.week_end - self.week_start).days != 6:
            raise ValueError("week_end must be exactly 6 days after week_start")
        return self

    @property
    def total_planned_minutes(self) -> int:
        return sum(t.estimated_minutes for t in self.tasks)

    @property
    def mit_count_by_day(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for task in self.tasks:
            if task.is_mit:
                counts[task.scheduled_day] = counts.get(task.scheduled_day, 0) + 1
        return counts

    model_config = {"frozen": True}
