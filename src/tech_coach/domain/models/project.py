"""Project domain entity for skill-building projects."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ProjectStatus(str, Enum):
    IDEA = "idea"
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Project(BaseModel):
    """
    A skill-building project that operationalizes goal achievement.

    Projects are suggested by the LLM as concrete vehicles for skill development,
    but users create/approve them explicitly. The planning engine references
    project tasks when generating weekly plans.
    """

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=3000)
    status: ProjectStatus = ProjectStatus.IDEA
    goal_ids: list[UUID] = Field(
        default_factory=list,
        description="Goals this project contributes to",
    )
    skill_ids: list[UUID] = Field(
        default_factory=list,
        description="Skills this project develops",
    )
    target_start: Optional[date] = None
    target_end: Optional[date] = None
    github_url: Optional[str] = None
    progress_notes: Optional[str] = Field(default=None, max_length=5000)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}
