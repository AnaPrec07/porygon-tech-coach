"""Reflections API router."""

from __future__ import annotations

import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from tech_coach.api.dependencies import (
    get_current_user,
    get_llm_client,
    get_signal_repository,
)
from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType
from tech_coach.domain.models.reflection import Reflection, ReflectionTemplate
from tech_coach.domain.models.user import User
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.infrastructure.llm.vertex_client import LLMServiceError, VertexAIClient
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/reflections")

# In-memory store for v1 simplicity. Replace with DB repository in v1.1.
_reflections: dict[str, Reflection] = {}


class CreateReflectionRequest(BaseModel):
    week_start: str
    wins: str | None = Field(default=None, max_length=2000)
    challenges: str | None = Field(default=None, max_length=2000)
    insights: str | None = Field(default=None, max_length=2000)
    next_week_focus: str | None = Field(default=None, max_length=1000)
    energy_level: int | None = Field(default=None, ge=1, le=5)
    completion_satisfaction: int | None = Field(default=None, ge=1, le=5)
    raw_text: str | None = Field(default=None, max_length=5000)
    plan_id: UUID | None = None


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_reflection(
    body: CreateReflectionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    signal_repo: SignalRepository = Depends(get_signal_repository),
    llm_client: VertexAIClient = Depends(get_llm_client),
) -> dict:
    week_start = datetime.date.fromisoformat(body.week_start)

    reflection = Reflection(
        user_id=current_user.id,
        week_start=week_start,
        plan_id=body.plan_id,
        content=ReflectionTemplate(
            wins=body.wins,
            challenges=body.challenges,
            insights=body.insights,
            next_week_focus=body.next_week_focus,
            energy_level=body.energy_level,
            completion_satisfaction=body.completion_satisfaction,
        ),
        raw_text=body.raw_text,
    )

    # Emit reflection submitted signal
    await signal_repo.save(
        BehavioralSignal(
            user_id=current_user.id,
            signal_type=SignalType.REFLECTION_SUBMITTED,
            metadata={"week_start": body.week_start, "has_raw_text": bool(body.raw_text)},
        )
    )

    # LLM analysis (best-effort — does not fail the endpoint)
    analysis_summary = None
    try:
        reflection_text = _build_reflection_text(body)
        if reflection_text:
            llm_response = await llm_client.generate(
                prompt_name="reflection_analysis",
                messages=[{"role": "user", "content": reflection_text}],
                user_id=str(current_user.id),
                trace_id=request.state.trace_id,
            )
            analysis_summary = llm_response.parsed_content.get("summary", "")
    except (LLMServiceError, KeyError):
        pass  # Analysis is optional

    reflection = reflection.model_copy(update={"llm_analysis_summary": analysis_summary})
    _reflections[str(reflection.id)] = reflection

    return {
        "reflection_id": str(reflection.id),
        "week_start": week_start.isoformat(),
        "analysis_summary": analysis_summary,
    }


@router.get("/")
async def list_reflections(
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    user_reflections = [
        r for r in _reflections.values() if r.user_id == current_user.id
    ]
    return [
        {
            "id": str(r.id),
            "week_start": r.week_start.isoformat(),
            "energy_level": r.content.energy_level,
            "completion_satisfaction": r.content.completion_satisfaction,
            "has_analysis": bool(r.llm_analysis_summary),
        }
        for r in sorted(user_reflections, key=lambda r: r.week_start, reverse=True)
    ]


def _build_reflection_text(body: CreateReflectionRequest) -> str:
    parts = []
    if body.wins:
        parts.append(f"Wins: {body.wins}")
    if body.challenges:
        parts.append(f"Challenges: {body.challenges}")
    if body.insights:
        parts.append(f"Insights: {body.insights}")
    if body.raw_text:
        parts.append(f"Additional notes: {body.raw_text}")
    return "\n\n".join(parts)
