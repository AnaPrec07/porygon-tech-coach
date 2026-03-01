"""Goals API router."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from tech_coach.api.dependencies import (
    get_current_user,
    get_goal_repository,
    get_llm_client,
)
from tech_coach.domain.models.goal import Goal, GoalPriority, GoalStatus, GoalType, SMARTCriteria
from tech_coach.domain.models.user import User
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.infrastructure.llm.vertex_client import LLMServiceError, VertexAIClient
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/goals")


# --- Request / Response schemas ---

class CreateGoalRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=2000)
    goal_type: GoalType
    priority: GoalPriority = GoalPriority.MEDIUM
    target_date: str  # ISO date string


class RefineGoalRequest(BaseModel):
    goal_id: UUID
    user_context: str = Field(
        default="",
        max_length=1000,
        description="Optional context to help the AI refine the goal",
    )


class GoalResponse(BaseModel):
    id: UUID
    title: str
    description: str
    goal_type: str
    status: str
    priority: int
    target_date: str
    progress_score: float
    smart_criteria: dict | None
    parent_goal_id: UUID | None


# --- Routes ---

@router.get("/", response_model=list[GoalResponse])
async def list_goals(
    status: GoalStatus | None = None,
    goal_type: GoalType | None = None,
    current_user: User = Depends(get_current_user),
    repo: GoalRepository = Depends(get_goal_repository),
) -> list[GoalResponse]:
    if status:
        goals = await repo.get_by_status(current_user.id, status)
    else:
        goals = await repo.get_active_by_user(current_user.id, goal_type)
    return [_to_response(g) for g in goals]


@router.post("/", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    body: CreateGoalRequest,
    current_user: User = Depends(get_current_user),
    repo: GoalRepository = Depends(get_goal_repository),
) -> GoalResponse:
    from datetime import date as date_type
    target = date_type.fromisoformat(body.target_date)
    goal = Goal(
        user_id=current_user.id,
        title=body.title,
        description=body.description,
        goal_type=body.goal_type,
        priority=body.priority,
        target_date=target,
    )
    saved = await repo.save(goal)
    return _to_response(saved)


@router.post("/{goal_id}/refine-smart", response_model=GoalResponse)
async def refine_goal_smart(
    goal_id: UUID,
    body: RefineGoalRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    repo: GoalRepository = Depends(get_goal_repository),
    llm_client: VertexAIClient = Depends(get_llm_client),
) -> GoalResponse:
    """
    Use LLM to suggest SMART criteria for a goal.

    The LLM suggests; the user approves. SMART criteria are not persisted
    until the user confirms (see PATCH /{goal_id}/smart).
    """
    goal = await repo.get_by_id(goal_id, current_user.id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")

    prompt_messages = [
        {
            "role": "user",
            "content": (
                f"Goal title: {goal.title}\n"
                f"Description: {goal.description}\n"
                f"Type: {goal.goal_type.value}\n"
                f"Target date: {goal.target_date.isoformat()}\n"
                + (f"Additional context: {body.user_context}" if body.user_context else "")
                + "\n\nPlease refine this goal into SMART criteria."
            ),
        }
    ]

    try:
        response = await llm_client.generate(
            prompt_name="goal_refinement",
            messages=prompt_messages,
            user_id=str(current_user.id),
            trace_id=request.state.trace_id,
        )
        smart_data = response.parsed_content
        smart = SMARTCriteria(**smart_data)
        updated_goal = goal.model_copy(update={"smart_criteria": smart})
    except (LLMServiceError, Exception) as exc:
        logger.warning(
            "goal.refine.failed",
            goal_id=str(goal_id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI refinement temporarily unavailable. Please try again.",
        ) from exc

    saved = await repo.save(updated_goal)
    return _to_response(saved)


@router.patch("/{goal_id}/activate", response_model=GoalResponse)
async def activate_goal(
    goal_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: GoalRepository = Depends(get_goal_repository),
) -> GoalResponse:
    goal = await repo.get_by_id(goal_id, current_user.id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    try:
        activated = goal.activate()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = await repo.save(activated)
    return _to_response(saved)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: GoalRepository = Depends(get_goal_repository),
) -> None:
    goal = await repo.get_by_id(goal_id, current_user.id)
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    await repo.delete(goal_id, current_user.id)


# --- Helpers ---

def _to_response(goal: Goal) -> GoalResponse:
    return GoalResponse(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        goal_type=goal.goal_type.value,
        status=goal.status.value,
        priority=goal.priority.value,
        target_date=goal.target_date.isoformat(),
        progress_score=goal.progress_score,
        smart_criteria=goal.smart_criteria.model_dump() if goal.smart_criteria else None,
        parent_goal_id=goal.parent_goal_id,
    )
