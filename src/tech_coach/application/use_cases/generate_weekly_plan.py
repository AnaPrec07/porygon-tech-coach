"""
Use case: Generate a weekly plan combining deterministic engine + LLM suggestions.

Flow:
  1. [DETERMINISTIC] Calculate burnout risk from recent signals
  2. [DETERMINISTIC] Run PlanningEngine.allocate_weekly_time() for goal allocations
  3. [DETERMINISTIC] Detect overcommitment vs user-declared capacity
  4. [LLM] Generate task suggestions per goal within allocated hours
  5. [DETERMINISTIC] Validate LLM tasks: schema, time budget, MIT constraints
  6. [DETERMINISTIC] Run prioritize_tasks() + balance_cognitive_load()
  7. Persist WeeklyPlan with all artifacts
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from tech_coach.domain.models.weekly_plan import Task, WeeklyPlan
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.domain.repositories.plan_repository import PlanRepository
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.domain.services.planning_engine import PlanningEngine, WeeklyPlanContext
from tech_coach.infrastructure.llm.vertex_client import LLMServiceError, VertexAIClient
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GenerateWeeklyPlanInput:
    user_id: UUID
    week_start: date          # Must be a Monday
    capacity_hours: float     # User-declared available hours
    trace_id: str
    regenerate: bool = False  # If True, replace existing plan for this week


@dataclass
class GenerateWeeklyPlanOutput:
    plan: WeeklyPlan
    overcommitted: bool
    overcommitment_ratio: float
    burnout_risk_level: str
    adjusted_capacity_hours: float
    active_goal_count: int
    total_tasks: int
    is_llm_assisted: bool


class GenerateWeeklyPlan:

    def __init__(
        self,
        goal_repository: GoalRepository,
        plan_repository: PlanRepository,
        signal_repository: SignalRepository,
        llm_client: VertexAIClient,
        planning_engine: PlanningEngine,
    ) -> None:
        self._goals = goal_repository
        self._plans = plan_repository
        self._signals = signal_repository
        self._llm = llm_client
        self._engine = planning_engine

    async def execute(self, input_data: GenerateWeeklyPlanInput) -> GenerateWeeklyPlanOutput:
        week_end = input_data.week_start + timedelta(days=6)

        # Check for existing plan
        if not input_data.regenerate:
            existing = await self._plans.get_for_week(
                input_data.user_id, input_data.week_start
            )
            if existing is not None:
                raise ValueError(
                    f"A plan already exists for week {input_data.week_start}. "
                    "Use regenerate=True to replace it."
                )

        # --- Step 1 & 2: Deterministic context ---
        since = datetime.utcnow() - timedelta(days=14)
        signals = await self._signals.get_by_user_since(input_data.user_id, since)
        active_goals = await self._goals.get_active_by_user(input_data.user_id)

        burnout_risk = self._engine.calculate_burnout_risk(
            signals, since.date()
        )
        plan_context: WeeklyPlanContext = self._engine.allocate_weekly_time(
            goals=active_goals,
            capacity_hours=input_data.capacity_hours,
            burnout_risk=burnout_risk,
            signals=signals,
        )

        logger.info(
            "plan.generation.context_built",
            trace_id=input_data.trace_id,
            user_id=str(input_data.user_id),
            burnout_risk=burnout_risk.value,
            burnout_level=burnout_risk.level,
            adjusted_capacity=plan_context.adjusted_capacity_hours,
            active_goals=len(plan_context.active_goals),
        )

        # --- Step 3–5: LLM task generation ---
        tasks: list[Task] = []
        is_llm_assisted = False

        try:
            llm_tasks = await self._generate_tasks_from_llm(
                plan_context=plan_context,
                week_start=input_data.week_start,
                user_id=input_data.user_id,
                trace_id=input_data.trace_id,
            )
            is_llm_assisted = True
        except LLMServiceError as exc:
            logger.warning(
                "plan.generation.llm_fallback",
                trace_id=input_data.trace_id,
                error_type=exc.error_type,
            )
            llm_tasks = self._generate_fallback_tasks(plan_context)

        # --- Step 6: Validate and prioritize ---
        goal_priorities = {g.id: g.priority for g in plan_context.active_goals}
        prioritized_tasks = self._engine.prioritize_tasks(
            tasks=llm_tasks,
            goal_priorities=goal_priorities,
            mit_limit_per_day=plan_context.mit_limit_per_day,
        )
        balanced_tasks = self._engine.balance_cognitive_load(prioritized_tasks)

        # --- Overcommitment check ---
        total_planned_minutes = sum(t.estimated_minutes for t in balanced_tasks)
        is_overcommitted, overcommitment_ratio = self._engine.detect_overcommitment(
            total_planned_minutes, plan_context.adjusted_capacity_hours
        )

        if is_overcommitted:
            logger.warning(
                "plan.generation.overcommitment",
                trace_id=input_data.trace_id,
                ratio=overcommitment_ratio,
                planned_minutes=total_planned_minutes,
            )

        # --- Build and persist ---
        goal_allocations = {
            str(alloc.goal_id): alloc.allocated_hours
            for alloc in plan_context.goal_allocations
        }

        plan = WeeklyPlan(
            user_id=input_data.user_id,
            week_start=input_data.week_start,
            week_end=week_end,
            tasks=balanced_tasks,
            capacity_hours=input_data.capacity_hours,
            goal_allocations=goal_allocations,
            burnout_risk_at_creation=burnout_risk.value,
            focus_score=sum(
                self._engine.calculate_focus_score(g, signals).value
                for g in plan_context.active_goals
            ) / max(len(plan_context.active_goals), 1),
        )

        saved_plan = await self._plans.save(plan)

        return GenerateWeeklyPlanOutput(
            plan=saved_plan,
            overcommitted=is_overcommitted,
            overcommitment_ratio=overcommitment_ratio,
            burnout_risk_level=burnout_risk.level,
            adjusted_capacity_hours=plan_context.adjusted_capacity_hours,
            active_goal_count=len(plan_context.active_goals),
            total_tasks=len(balanced_tasks),
            is_llm_assisted=is_llm_assisted,
        )

    async def _generate_tasks_from_llm(
        self,
        plan_context: WeeklyPlanContext,
        week_start: date,
        user_id: UUID,
        trace_id: str,
    ) -> list[Task]:
        """
        Ask LLM to suggest concrete tasks per goal within the time allocation.

        The LLM receives: goal titles, allocated hours, capacity, burnout context.
        It returns a structured list of tasks per goal (validated against JSON schema).
        """
        goals_context = []
        for alloc in plan_context.goal_allocations:
            goal = next(
                (g for g in plan_context.active_goals if g.id == alloc.goal_id), None
            )
            if goal:
                goals_context.append(
                    f"Goal: {goal.title}\n"
                    f"  Type: {goal.goal_type.value}\n"
                    f"  Allocated hours this week: {alloc.allocated_hours:.1f}h\n"
                    f"  Current progress: {goal.progress_score:.0%}"
                )

        prompt_content = (
            f"Week of {week_start.isoformat()}. "
            f"Available capacity: {plan_context.adjusted_capacity_hours:.1f} hours "
            f"(adjusted from {plan_context.capacity_hours:.1f}h due to "
            f"{plan_context.burnout_risk.level} burnout risk).\n\n"
            f"Goals and allocations:\n" + "\n\n".join(goals_context) + "\n\n"
            f"ADHD constraint: maximum {plan_context.mit_limit_per_day} MIT tasks per day. "
            f"Keep tasks concrete and bounded (max 90 minutes each). "
            f"Suggest 2-4 tasks per goal. Return as structured JSON."
        )

        response = await self._llm.generate(
            prompt_name="weekly_plan_generation",
            messages=[{"role": "user", "content": prompt_content}],
            user_id=str(user_id),
            trace_id=trace_id,
        )

        return self._parse_llm_tasks(
            response.parsed_content, plan_context, week_start
        )

    def _parse_llm_tasks(
        self,
        llm_data: dict,
        plan_context: WeeklyPlanContext,
        week_start: date,
    ) -> list[Task]:
        """
        Parse and validate LLM-suggested tasks.

        Enforcement:
          - Each task must reference a known goal_id
          - estimated_minutes must be in [5, 90] (capped at 90 for ADHD)
          - Tasks exceeding goal time allocation are trimmed
        """
        from tech_coach.domain.models.weekly_plan import CognitiveLoad

        tasks: list[Task] = []
        allocated_hours = {
            alloc.goal_id: alloc.allocated_hours
            for alloc in plan_context.goal_allocations
        }
        goal_id_map = {g.title: g.id for g in plan_context.active_goals}
        used_minutes: dict[UUID, int] = {gid: 0 for gid in allocated_hours}

        day_counter = 0
        for task_data in llm_data.get("tasks", []):
            goal_title = task_data.get("goal_title", "")
            goal_id = goal_id_map.get(goal_title)
            if goal_id is None:
                continue

            estimated_minutes = min(
                max(task_data.get("estimated_minutes", 30), 5), 90
            )
            budget_minutes = int(allocated_hours.get(goal_id, 0) * 60)

            if used_minutes[goal_id] + estimated_minutes > budget_minutes + 30:
                continue  # Skip if significantly over budget

            load_str = task_data.get("cognitive_load", "medium").lower()
            cognitive_load_map = {
                "deep_work": CognitiveLoad.DEEP_WORK,
                "medium": CognitiveLoad.MEDIUM,
                "admin": CognitiveLoad.ADMIN,
            }
            cognitive_load = cognitive_load_map.get(load_str, CognitiveLoad.MEDIUM)

            task = Task(
                goal_id=goal_id,
                title=task_data.get("title", "Task"),
                description=task_data.get("description", ""),
                estimated_minutes=estimated_minutes,
                cognitive_load=cognitive_load,
                scheduled_day=day_counter % 5,  # Mon–Fri distribution
                order_in_day=len([t for t in tasks if t.scheduled_day == day_counter % 5]),
            )
            tasks.append(task)
            used_minutes[goal_id] = used_minutes.get(goal_id, 0) + estimated_minutes
            day_counter += 1

        return tasks

    def _generate_fallback_tasks(self, plan_context: WeeklyPlanContext) -> list[Task]:
        """
        Rule-based fallback when LLM is unavailable.

        Generates one placeholder task per active goal.
        """
        from tech_coach.domain.models.weekly_plan import CognitiveLoad

        tasks: list[Task] = []
        for i, goal in enumerate(plan_context.active_goals):
            allocated = next(
                (a.allocated_hours for a in plan_context.goal_allocations if a.goal_id == goal.id),
                1.0,
            )
            tasks.append(
                Task(
                    goal_id=goal.id,
                    title=f"Work on: {goal.title}",
                    description=(
                        "Focus block for this goal. "
                        "AI-assisted task breakdown unavailable — plan manually."
                    ),
                    estimated_minutes=min(int(allocated * 60), 90),
                    cognitive_load=CognitiveLoad.DEEP_WORK,
                    scheduled_day=i % 5,
                    order_in_day=0,
                )
            )
        return tasks
