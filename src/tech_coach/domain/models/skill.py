"""Skill domain entity."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SkillLevel(str, Enum):
    NOVICE = "novice"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"


class SkillCategory(str, Enum):
    TECHNICAL = "technical"
    LEADERSHIP = "leadership"
    COMMUNICATION = "communication"
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    SOFT_SKILL = "soft_skill"
    TOOL_PROFICIENCY = "tool_proficiency"


class LearningResource(BaseModel):
    """A curated learning resource suggested by LLM, reviewed by user."""

    title: str
    url: Optional[str] = None
    resource_type: str = Field(
        description="book, course, video, article, podcast, project"
    )
    estimated_hours: Optional[float] = None
    notes: Optional[str] = None

    model_config = {"frozen": True}


class Skill(BaseModel):
    """
    A skill being developed as part of the coaching journey.

    Skills link to Goals (a goal may develop one or more skills) and
    to Projects (a project may be the primary vehicle for skill development).
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=1000)
    category: SkillCategory
    current_level: SkillLevel = SkillLevel.NOVICE
    target_level: SkillLevel
    progress_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Deterministic progress score [0, 1]",
    )
    learning_resources: list[LearningResource] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None, max_length=2000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}
