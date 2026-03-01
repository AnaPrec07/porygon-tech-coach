"""Weekly plans API router."""

from __future__ import annotations

import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from tech_coach.api.dependencies import (
    get_current_user,
    get_goal_repository,
    get_llm_client,
    get_plan_repository,
    get_signal_repository,
)
from tech_coach.application.use_cases.generate_weekly_plan import (
    GenerateWeeklyPlan,
    GenerateWeeklyPlanInput,
)
from tech_coach.domain.models.user import User
from tech_coach.domain.models.weekly_plan import TaskStatus
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.domain.repositories.plan_repository import PlanRepository
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.domain.services.planning_engine import PlanningEngine
from tech_coach.infrastructure.llm.vertex_client import VertexAIClient
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/plans")


class GeneratePlanRequest(BaseModel):
    week_start: str = Field(description="ISO date string for Monday of the week")
    capacity_hours: float = Field(ge=1.0, le=80.0)
    regenerate: bool = False


class UpdateTaskRequest(BaseModel):
    status: TaskStatus
    actual_minutes: int | None = None


@router.post("/generate", status_code=status.HTTP_201_CREATED)
async def generate_plan(
    body: GeneratePlanRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    goal_repo: GoalRepository = Depends(get_goal_repository),
    plan_repo: PlanRepository = Depends(get_plan_repository),
    signal_repo: SignalRepository = Depends(get_signal_repository),
    llm_client: VertexAIClient = Depends(get_llm_client),
) -> dict:
    week_start = datetime.date.fromisoformat(body.week_start)
    use_case = GenerateWeeklyPlan(
        goal_repository=goal_repo,
        plan_repository=plan_repo,
        signal_repository=signal_repo,
        llm_client=llm_client,
        planning_engine=PlanningEngine(),
    )
    try:
        result = await use_case.execute(
            GenerateWeeklyPlanInput(
                user_id=current_user.id,
                week_start=week_start,
                capacity_hours=body.capacity_hours,
                trace_id=request.state.trace_id,
                regenerate=body.regenerate,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = result.plan
    return {
        "plan_id": str(plan.id),
        "week_start": plan.week_start.isoformat(),
        "week_end": plan.week_end.isoformat(),
        "task_count": result.total_tasks,
        "adjusted_capacity_hours": result.adjusted_capacity_hours,
        "burnout_risk_level": result.burnout_risk_level,
        "overcommitted": result.overcommitted,
        "overcommitment_ratio": result.overcommitment_ratio,
        "is_llm_assisted": result.is_llm_assisted,
        "tasks": [t.model_dump(mode="json") for t in plan.tasks],
        "goal_allocations": plan.goal_allocations,
    }


@router.get("/")
async def get_current_plan(
    week_start: str | None = None,
    current_user: User = Depends(get_current_user),
    plan_repo: PlanRepository = Depends(get_plan_repository),
) -> dict:
    if week_start:
        d = datetime.date.fromisoformat(week_start)
    else:
        today = datetime.date.today()
        d = today - datetime.timedelta(days=today.weekday())

    plan = await plan_repo.get_for_week(current_user.id, d)
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan for this week. Generate one first.")

    return {
        "plan_id": str(plan.id),
        "week_start": plan.week_start.isoformat(),
        "week_end": plan.week_end.isoformat(),
        "capacity_hours": plan.capacity_hours,
        "burnout_risk_at_creation": plan.burnout_risk_at_creation,
        "focus_score": plan.focus_score,
        "tasks": [t.model_dump(mode="json") for t in plan.tasks],
        "goal_allocations": plan.goal_allocations,
        "completion_rate": plan.completion_rate,
    }


@router.patch("/{plan_id}/tasks/{task_id}")
async def update_task(
    plan_id: UUID,
    task_id: UUID,
    body: UpdateTaskRequest,
    current_user: User = Depends(get_current_user),
    plan_repo: PlanRepository = Depends(get_plan_repository),
    signal_repo: SignalRepository = Depends(get_signal_repository),
) -> dict:
    from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType

    task = await plan_repo.update_task_status(
        plan_id=plan_id,
        task_id=task_id,
        user_id=current_user.id,
        status=body.status,
        actual_minutes=body.actual_minutes,
    )

    # Emit behavioral signal for completed/skipped tasks
    signal_map = {
        TaskStatus.COMPLETED: SignalType.TASK_COMPLETED,
        TaskStatus.SKIPPED: SignalType.TASK_SKIPPED,
    }
    if body.status in signal_map:
        signal = BehavioralSignal(
            user_id=current_user.id,
            signal_type=signal_map[body.status],
            goal_id=task.goal_id,
            plan_id=plan_id,
            intensity=1.0,
            metadata={
                "task_id": str(task_id),
                "estimated_minutes": task.estimated_minutes,
                "actual_minutes": body.actual_minutes,
            },
        )
        await signal_repo.save(signal)

    return {"task_id": str(task_id), "status": body.status.value}


@router.get("/history")
async def plan_history(
    weeks: int = 8,
    current_user: User = Depends(get_current_user),
    plan_repo: PlanRepository = Depends(get_plan_repository),
) -> list[dict]:
    stats = await plan_repo.get_completion_stats(current_user.id, weeks=weeks)
    return [
        {
            "week_start": s["week_start"].isoformat(),
            "planned": s["planned"],
            "completed": s["completed"],
            "rate": s["rate"],
        }
        for s in stats
    ]
