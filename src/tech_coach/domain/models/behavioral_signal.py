"""
Behavioral signal domain entity.

Behavioral signals are the raw observations from which the planning engine
derives burnout risk, focus scores, and drift detection. They are never
set by LLM output; only by deterministic rules from user activity.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    # Task completion signals
    TASK_COMPLETED = "task_completed"
    TASK_SKIPPED = "task_skipped"
    TASK_OVERDUE = "task_overdue"

    # Session signals
    SESSION_STARTED = "session_started"
    SESSION_COMPLETED = "session_completed"
    SESSION_ABANDONED = "session_abandoned"

    # Planning signals
    PLAN_ACCEPTED = "plan_accepted"
    PLAN_MODIFIED = "plan_modified"
    PLAN_REJECTED = "plan_rejected"

    # Goal signals
    GOAL_PROGRESS_UPDATED = "goal_progress_updated"
    GOAL_STAGNANT = "goal_stagnant"          # No progress in >14 days
    GOAL_ABANDONED = "goal_abandoned"

    # Reflection signals
    REFLECTION_SUBMITTED = "reflection_submitted"
    REFLECTION_SKIPPED = "reflection_skipped"

    # Derived / computed signals
    BURNOUT_RISK_HIGH = "burnout_risk_high"
    OVERCOMMITMENT_DETECTED = "overcommitment_detected"
    DRIFT_DETECTED = "drift_detected"


class BehavioralSignal(BaseModel):
    """
    A discrete behavioral observation tied to a user's coaching journey.

    Signals feed into the PlanningEngine for deterministic scoring.
    The LLM may *interpret* signals in a coaching session, but never
    creates or modifies them.

    metadata: flexible dict for signal-specific context. For example:
      - TASK_COMPLETED: {"task_id": ..., "planned_minutes": 30, "actual_minutes": 45}
      - GOAL_STAGNANT: {"goal_id": ..., "days_since_progress": 16}
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    signal_type: SignalType
    goal_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    intensity: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Signal intensity [0, 1]. Higher means stronger signal. "
            "Example: task 2h overdue = 1.0, task 10m overdue = 0.1"
        ),
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}
