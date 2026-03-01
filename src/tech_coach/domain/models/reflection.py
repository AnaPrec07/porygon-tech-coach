"""Reflection domain entity."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ReflectionTemplate(BaseModel):
    """
    Structured reflection template.

    The LLM generates the initial template; users fill in each field.
    All fields are optional to reduce friction (ADHD-aware design).
    """

    wins: Optional[str] = Field(
        default=None,
        description="What went well this week?",
        max_length=2000,
    )
    challenges: Optional[str] = Field(
        default=None,
        description="What was difficult or blocked progress?",
        max_length=2000,
    )
    insights: Optional[str] = Field(
        default=None,
        description="What did you learn about yourself or your goals?",
        max_length=2000,
    )
    next_week_focus: Optional[str] = Field(
        default=None,
        description="What is the single most important focus for next week?",
        max_length=1000,
    )
    energy_level: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="Energy/mood rating for the week (1=depleted, 5=excellent)",
    )
    completion_satisfaction: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="Satisfaction with task completion (1=very unsatisfied, 5=very satisfied)",
    )

    model_config = {"frozen": True}


class Reflection(BaseModel):
    """
    A weekly reflection record.

    Reflections are the primary input for behavioral signal extraction.
    The LLM analyzes the content to suggest signals (e.g., burnout risk
    indicators), but the deterministic engine validates and persists them.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    week_start: date
    plan_id: Optional[UUID] = Field(
        default=None,
        description="WeeklyPlan being reflected on",
    )
    content: ReflectionTemplate
    raw_text: Optional[str] = Field(
        default=None,
        description="Free-form additional notes",
        max_length=5000,
    )
    llm_analysis_summary: Optional[str] = Field(
        default=None,
        description=(
            "LLM-generated summary of key themes. Informational only. "
            "Never used to automatically update goal status or plans."
        ),
    )
    extracted_signal_ids: list[UUID] = Field(
        default_factory=list,
        description="BehavioralSignal IDs derived from this reflection",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}
