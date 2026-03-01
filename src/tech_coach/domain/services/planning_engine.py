"""
Planning Engine — purely deterministic, zero LLM calls.

This module implements all algorithmic logic for the coaching platform.
It has NO imports from infrastructure or LLM layers.

The planning engine:
  1. Calculates burnout risk from behavioral signals
  2. Calculates focus scores per goal
  3. Allocates weekly time budget across goals
  4. Prioritizes tasks using an urgency × importance matrix
  5. Enforces ADHD-aware constraints (MIT limits, cognitive load balancing)
  6. Computes progress scores for goals from task completion data

Design contract:
  - All methods are synchronous (pure computation, no I/O)
  - All methods are deterministic given the same inputs
  - No global state
  - Inputs are domain entities; outputs are domain entities or primitives
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple
from uuid import UUID

from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType
from tech_coach.domain.models.goal import Goal, GoalPriority, GoalStatus
from tech_coach.domain.models.weekly_plan import CognitiveLoad, Task, TaskStatus


# ---------------------------------------------------------------------------
# Value objects for engine outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BurnoutRiskScore:
    """
    Burnout risk assessment for a user at a point in time.

    value: 0.0 (no risk) to 1.0 (critical risk)
    factors: human-readable list of contributing factors for transparency
    """

    value: float
    factors: list[str]
    computed_at: datetime

    @property
    def level(self) -> str:
        if self.value < 0.25:
            return "low"
        if self.value < 0.5:
            return "moderate"
        if self.value < 0.75:
            return "high"
        return "critical"


@dataclass(frozen=True)
class FocusScore:
    """Focus score for a specific goal."""

    goal_id: UUID
    value: float
    recency_component: float
    completion_component: float
    deadline_pressure_component: float


class TimeAllocation(NamedTuple):
    goal_id: UUID
    allocated_hours: float
    priority_weight: float


@dataclass(frozen=True)
class WeeklyPlanContext:
    """
    All deterministic inputs needed to generate a weekly plan.
    Passed to the application layer which combines with LLM-suggested tasks.
    """

    burnout_risk: BurnoutRiskScore
    goal_allocations: list[TimeAllocation]
    capacity_hours: float
    adjusted_capacity_hours: float  # capacity after burnout reduction
    mit_limit_per_day: int
    active_goals: list[Goal]


@dataclass(frozen=True)
class ProgressUpdate:
    """Result of recalculating a goal's progress score."""

    goal_id: UUID
    new_score: float
    completed_tasks: int
    total_tasks: int
    completion_rate: float


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BURNOUT_WINDOW_DAYS = 14
COMPLETION_RATE_WINDOW_DAYS = 14
STAGNATION_THRESHOLD_DAYS = 14
MAX_ACTIVE_GOALS_PER_WEEK = 3          # ADHD constraint: focus on 3 goals max
MAX_MIT_PER_DAY = 3                    # ADHD constraint: 3 Most Important Tasks per day
BURNOUT_CAPACITY_REDUCTION_MAX = 0.35  # Max capacity reduction due to burnout
MIN_WEEKLY_HOURS = 1.0
DEEP_WORK_BLOCK_MINUTES = 90           # Preferred deep work session length


# ---------------------------------------------------------------------------
# Planning Engine
# ---------------------------------------------------------------------------


class PlanningEngine:
    """
    Deterministic planning engine.

    Stateless: all state is passed as arguments. Thread-safe.
    """

    # -------------------------------------------------------------------
    # Burnout Risk
    # -------------------------------------------------------------------

    def calculate_burnout_risk(
        self,
        signals: list[BehavioralSignal],
        since: date,
    ) -> BurnoutRiskScore:
        """
        Composite burnout risk heuristic from behavioral signals.

        Components:
          1. Completion rate decline (0–0.4 weight)
             - Declining task completion over the window signals fatigue
          2. Overcommitment ratio (0–0.3 weight)
             - Planned time significantly exceeds capacity
          3. Session gap (0–0.2 weight)
             - Days since last coaching session (isolation signal)
          4. Skip streak (0–0.1 weight)
             - Consecutive days of skipped tasks

        All weights sum to 1.0. Final score is in [0, 1].
        """
        if not signals:
            return BurnoutRiskScore(
                value=0.0,
                factors=[],
                computed_at=datetime.utcnow(),
            )

        factors: list[str] = []
        components: dict[str, float] = {}

        window_start = datetime.combine(since, datetime.min.time())

        # --- Component 1: Completion rate trend ---
        completion_rate = self._completion_rate_from_signals(signals, window_start)
        trend_score = self._completion_trend_score(signals, window_start)
        completion_component = trend_score * 0.4
        components["completion_trend"] = completion_component
        if trend_score > 0.5:
            factors.append(
                f"Task completion declining (rate: {completion_rate:.0%})"
            )

        # --- Component 2: Overcommitment ---
        overcommit_score = self._overcommitment_score(signals)
        overcommit_component = min(overcommit_score, 1.0) * 0.3
        components["overcommitment"] = overcommit_component
        if overcommit_score > 0.5:
            factors.append("Planned hours significantly exceed capacity")

        # --- Component 3: Session gap ---
        gap_days = self._days_since_last_session(signals)
        gap_score = min(gap_days / 21.0, 1.0)  # Normalize to 21-day max
        gap_component = gap_score * 0.2
        components["session_gap"] = gap_component
        if gap_days > 7:
            factors.append(f"No coaching session in {gap_days} days")

        # --- Component 4: Skip streak ---
        skip_streak = self._skip_streak(signals)
        skip_component = min(skip_streak / 5.0, 1.0) * 0.1
        components["skip_streak"] = skip_component
        if skip_streak >= 3:
            factors.append(f"{skip_streak} consecutive days skipping tasks")

        total = sum(components.values())
        total = max(0.0, min(1.0, total))  # Clamp to [0, 1]

        return BurnoutRiskScore(
            value=round(total, 3),
            factors=factors,
            computed_at=datetime.utcnow(),
        )

    def _completion_rate_from_signals(
        self,
        signals: list[BehavioralSignal],
        since: datetime,
    ) -> float:
        completed = sum(
            1
            for s in signals
            if s.signal_type == SignalType.TASK_COMPLETED and s.recorded_at >= since
        )
        missed = sum(
            1
            for s in signals
            if s.signal_type in (SignalType.TASK_SKIPPED, SignalType.TASK_OVERDUE)
            and s.recorded_at >= since
        )
        total = completed + missed
        if total == 0:
            return 1.0
        return completed / total

    def _completion_trend_score(
        self,
        signals: list[BehavioralSignal],
        since: datetime,
    ) -> float:
        """
        Score 0.0 (improving) to 1.0 (strongly declining).
        Splits the window into two halves and compares completion rates.
        """
        midpoint = since + timedelta(days=BURNOUT_WINDOW_DAYS // 2)
        now = datetime.utcnow()

        early_rate = self._completion_rate_from_signals(
            [s for s in signals if since <= s.recorded_at < midpoint], since
        )
        late_rate = self._completion_rate_from_signals(
            [s for s in signals if midpoint <= s.recorded_at <= now], midpoint
        )

        decline = early_rate - late_rate
        if decline <= 0:
            return 0.0
        return min(decline / 0.5, 1.0)  # 50% drop = full score

    def _overcommitment_score(self, signals: list[BehavioralSignal]) -> float:
        """
        Score based on PLAN_MODIFIED and OVERCOMMITMENT_DETECTED signals.
        """
        overcommit_signals = [
            s for s in signals
            if s.signal_type == SignalType.OVERCOMMITMENT_DETECTED
        ]
        plan_rejected = [
            s for s in signals
            if s.signal_type == SignalType.PLAN_REJECTED
        ]
        weight = sum(s.intensity for s in overcommit_signals)
        weight += len(plan_rejected) * 0.5
        return min(weight / 3.0, 1.0)

    def _days_since_last_session(self, signals: list[BehavioralSignal]) -> int:
        session_signals = [
            s for s in signals
            if s.signal_type in (
                SignalType.SESSION_COMPLETED, SignalType.SESSION_STARTED
            )
        ]
        if not session_signals:
            return BURNOUT_WINDOW_DAYS  # Max penalty
        latest = max(s.recorded_at for s in session_signals)
        return (datetime.utcnow() - latest).days

    def _skip_streak(self, signals: list[BehavioralSignal]) -> int:
        """Count consecutive days ending today where all tasks were skipped."""
        skip_signals = sorted(
            [s for s in signals if s.signal_type == SignalType.TASK_SKIPPED],
            key=lambda s: s.recorded_at,
            reverse=True,
        )
        complete_signals = {
            s.recorded_at.date()
            for s in signals
            if s.signal_type == SignalType.TASK_COMPLETED
        }

        streak = 0
        check_date = date.today()
        for _ in range(14):
            day_skips = [s for s in skip_signals if s.recorded_at.date() == check_date]
            if day_skips and check_date not in complete_signals:
                streak += 1
            else:
                break
            check_date -= timedelta(days=1)
        return streak

    # -------------------------------------------------------------------
    # Focus Scoring
    # -------------------------------------------------------------------

    def calculate_focus_score(
        self,
        goal: Goal,
        signals: list[BehavioralSignal],
        today: date | None = None,
    ) -> FocusScore:
        """
        Focus score for a goal: how much attention should it receive.

        Components:
          1. Deadline pressure (0.4 weight): proximity to target_date
          2. Completion momentum (0.35 weight): recent completion rate on goal tasks
          3. Goal recency (0.25 weight): how recently the goal was updated

        Score in [0, 1]. Higher = should receive more focus.
        """
        today = today or date.today()

        # Deadline pressure: sigmoid around 30 days to deadline
        days_remaining = (goal.target_date - today).days
        if days_remaining <= 0:
            deadline_component = 1.0
        else:
            # Pressure increases nonlinearly as deadline approaches
            deadline_component = 1.0 / (1.0 + math.exp((days_remaining - 30) / 10))
        deadline_component = round(deadline_component * 0.4, 4)

        # Completion momentum: goal-specific task completion in last 7 days
        goal_signals = [s for s in signals if s.goal_id == goal.id]
        recent_completed = sum(
            1 for s in goal_signals
            if s.signal_type == SignalType.TASK_COMPLETED
            and (datetime.utcnow() - s.recorded_at).days <= 7
        )
        recent_missed = sum(
            1 for s in goal_signals
            if s.signal_type in (SignalType.TASK_SKIPPED, SignalType.TASK_OVERDUE)
            and (datetime.utcnow() - s.recorded_at).days <= 7
        )
        total_recent = recent_completed + recent_missed
        momentum = recent_completed / total_recent if total_recent > 0 else 0.5
        completion_component = round(momentum * 0.35, 4)

        # Recency: days since goal was last updated
        days_since_update = (
            datetime.utcnow() - goal.updated_at
        ).days
        recency = 1.0 / (1.0 + days_since_update / 7.0)
        recency_component = round(recency * 0.25, 4)

        value = deadline_component + completion_component + recency_component

        return FocusScore(
            goal_id=goal.id,
            value=round(value, 4),
            recency_component=recency_component,
            completion_component=completion_component,
            deadline_pressure_component=deadline_component,
        )

    # -------------------------------------------------------------------
    # Time Allocation
    # -------------------------------------------------------------------

    def allocate_weekly_time(
        self,
        goals: list[Goal],
        capacity_hours: float,
        burnout_risk: BurnoutRiskScore,
        signals: list[BehavioralSignal],
        today: date | None = None,
    ) -> WeeklyPlanContext:
        """
        Allocate the weekly time budget across active goals.

        Algorithm:
          1. Reduce capacity by burnout risk factor
          2. Limit to MAX_ACTIVE_GOALS_PER_WEEK by priority + focus score
          3. Weight each goal by (priority^2 × focus_score)
          4. Distribute adjusted_capacity proportionally
          5. Enforce minimum allocation (don't spread too thin)

        Returns WeeklyPlanContext with all deterministic inputs for plan generation.
        """
        today = today or date.today()

        # Step 1: Burnout capacity reduction
        reduction = burnout_risk.value * BURNOUT_CAPACITY_REDUCTION_MAX
        adjusted_capacity = max(
            MIN_WEEKLY_HOURS,
            capacity_hours * (1.0 - reduction),
        )

        # Step 2: Rank active goals
        active_goals = [g for g in goals if g.status == GoalStatus.ACTIVE]
        focus_scores = {
            g.id: self.calculate_focus_score(g, signals, today)
            for g in active_goals
        }

        # Composite score: priority² × focus
        def composite_score(goal: Goal) -> float:
            return (goal.priority.value ** 2) * focus_scores[goal.id].value

        ranked = sorted(active_goals, key=composite_score, reverse=True)
        selected = ranked[:MAX_ACTIVE_GOALS_PER_WEEK]

        # Step 3: Compute weights
        total_weight = sum(composite_score(g) for g in selected)
        if total_weight == 0:
            equal_share = adjusted_capacity / max(len(selected), 1)
            allocations = [
                TimeAllocation(
                    goal_id=g.id,
                    allocated_hours=round(equal_share, 2),
                    priority_weight=1.0 / max(len(selected), 1),
                )
                for g in selected
            ]
        else:
            allocations = []
            for goal in selected:
                weight = composite_score(goal) / total_weight
                hours = round(weight * adjusted_capacity, 2)
                allocations.append(
                    TimeAllocation(
                        goal_id=goal.id,
                        allocated_hours=hours,
                        priority_weight=round(weight, 4),
                    )
                )

        # ADHD: high burnout → reduce MIT limit to avoid overwhelm
        mit_limit = MAX_MIT_PER_DAY
        if burnout_risk.value >= 0.75:
            mit_limit = 2
        elif burnout_risk.value >= 0.5:
            mit_limit = MAX_MIT_PER_DAY  # Keep at 3 but flag in coaching

        return WeeklyPlanContext(
            burnout_risk=burnout_risk,
            goal_allocations=allocations,
            capacity_hours=capacity_hours,
            adjusted_capacity_hours=round(adjusted_capacity, 2),
            mit_limit_per_day=mit_limit,
            active_goals=selected,
        )

    # -------------------------------------------------------------------
    # Task Prioritization
    # -------------------------------------------------------------------

    def prioritize_tasks(
        self,
        tasks: list[Task],
        goal_priorities: dict[UUID, GoalPriority],
        mit_limit_per_day: int = MAX_MIT_PER_DAY,
    ) -> list[Task]:
        """
        Priority matrix prioritization with ADHD-aware MIT constraints.

        Urgency = inverse of estimated_minutes (shorter tasks bubble up for quick wins)
        Importance = goal priority × (1 + is_deep_work)
        Score = urgency_weight * urgency + importance_weight * importance

        MIT selection: top tasks by score up to mit_limit_per_day per scheduled_day.
        Remaining tasks sorted by score within each day.
        """
        URGENCY_WEIGHT = 0.3
        IMPORTANCE_WEIGHT = 0.7

        def urgency(task: Task) -> float:
            # Normalize: 5min = 1.0, 480min = ~0.01
            return 1.0 / (1.0 + math.log1p(task.estimated_minutes / 30.0))

        def importance(task: Task) -> float:
            goal_pri = goal_priorities.get(task.goal_id, GoalPriority.MEDIUM).value
            deep_bonus = 1.3 if task.cognitive_load == CognitiveLoad.DEEP_WORK else 1.0
            return (goal_pri / 4.0) * deep_bonus  # Normalize to [0.25, 1.3]

        def score(task: Task) -> float:
            return URGENCY_WEIGHT * urgency(task) + IMPORTANCE_WEIGHT * importance(task)

        # Group by day
        days: dict[int, list[Task]] = {}
        for task in tasks:
            days.setdefault(task.scheduled_day, []).append(task)

        result: list[Task] = []
        for day_tasks in days.values():
            sorted_tasks = sorted(day_tasks, key=score, reverse=True)
            mit_count = 0
            final_tasks: list[Task] = []
            for i, task in enumerate(sorted_tasks):
                is_mit = mit_count < mit_limit_per_day and i < mit_limit_per_day
                if is_mit:
                    mit_count += 1
                final_tasks.append(
                    task.model_copy(update={"is_mit": is_mit, "order_in_day": i})
                )
            result.extend(final_tasks)

        return result

    # -------------------------------------------------------------------
    # Cognitive Load Balancing
    # -------------------------------------------------------------------

    def balance_cognitive_load(self, tasks: list[Task]) -> list[Task]:
        """
        Reorder tasks within each day to alternate cognitive load.

        Pattern: DEEP_WORK → MEDIUM → ADMIN → DEEP_WORK → ...
        ADHD principle: place deep work early in the day (order_in_day 0–1),
        admin tasks in the afternoon (order_in_day 3+).

        This does not change which tasks are scheduled, only their order.
        """
        def load_order(task: Task) -> int:
            load_priority = {
                CognitiveLoad.DEEP_WORK: 0,
                CognitiveLoad.MEDIUM: 1,
                CognitiveLoad.ADMIN: 2,
            }
            return load_priority[task.cognitive_load]

        days: dict[int, list[Task]] = {}
        for task in tasks:
            days.setdefault(task.scheduled_day, []).append(task)

        result: list[Task] = []
        for day, day_tasks in sorted(days.items()):
            # Interleave: sort by (load_order, score) to alternate
            sorted_day = sorted(day_tasks, key=lambda t: (load_order(t), t.order_in_day))
            reordered = [
                t.model_copy(update={"order_in_day": i})
                for i, t in enumerate(sorted_day)
            ]
            result.extend(reordered)

        return result

    # -------------------------------------------------------------------
    # Progress Scoring
    # -------------------------------------------------------------------

    def calculate_goal_progress(
        self,
        goal: Goal,
        tasks: list[Task],
    ) -> ProgressUpdate:
        """
        Deterministic goal progress from task completion data.

        progress = (weighted_completed_minutes) / (total_estimated_minutes)

        Weighting: completed tasks count at 1.0, in-progress at 0.5, others at 0.
        Time-based to avoid gaming with many trivial tasks.
        """
        goal_tasks = [t for t in tasks if t.goal_id == goal.id]

        if not goal_tasks:
            return ProgressUpdate(
                goal_id=goal.id,
                new_score=goal.progress_score,
                completed_tasks=0,
                total_tasks=0,
                completion_rate=0.0,
            )

        total_estimated = sum(t.estimated_minutes for t in goal_tasks)
        if total_estimated == 0:
            return ProgressUpdate(
                goal_id=goal.id,
                new_score=0.0,
                completed_tasks=0,
                total_tasks=len(goal_tasks),
                completion_rate=0.0,
            )

        weighted_done = sum(
            t.estimated_minutes
            for t in goal_tasks
            if t.status == TaskStatus.COMPLETED
        )
        weighted_in_progress = sum(
            t.estimated_minutes * 0.5
            for t in goal_tasks
            if t.status == TaskStatus.IN_PROGRESS
        )

        completed_count = sum(1 for t in goal_tasks if t.status == TaskStatus.COMPLETED)
        completion_rate = completed_count / len(goal_tasks)

        new_score = min(
            1.0,
            (weighted_done + weighted_in_progress) / total_estimated,
        )

        return ProgressUpdate(
            goal_id=goal.id,
            new_score=round(new_score, 4),
            completed_tasks=completed_count,
            total_tasks=len(goal_tasks),
            completion_rate=round(completion_rate, 4),
        )

    # -------------------------------------------------------------------
    # Stagnation Detection
    # -------------------------------------------------------------------

    def detect_stagnant_goals(
        self,
        goals: list[Goal],
        signals: list[BehavioralSignal],
        today: date | None = None,
    ) -> list[Goal]:
        """
        Identify active goals with no meaningful progress signal in the past
        STAGNATION_THRESHOLD_DAYS days.

        A goal is stagnant if:
          - Status is ACTIVE
          - No TASK_COMPLETED signal referencing this goal in the threshold window
          - No GOAL_PROGRESS_UPDATED signal in the threshold window
        """
        today = today or date.today()
        threshold = datetime.utcnow() - timedelta(days=STAGNATION_THRESHOLD_DAYS)

        active_goals = [g for g in goals if g.status == GoalStatus.ACTIVE]
        stagnant: list[Goal] = []

        for goal in active_goals:
            goal_signals = [
                s for s in signals
                if s.goal_id == goal.id and s.recorded_at >= threshold
            ]
            progress_signals = [
                s for s in goal_signals
                if s.signal_type in (
                    SignalType.TASK_COMPLETED,
                    SignalType.GOAL_PROGRESS_UPDATED,
                )
            ]
            if not progress_signals:
                stagnant.append(goal)

        return stagnant

    # -------------------------------------------------------------------
    # Overcommitment Detection
    # -------------------------------------------------------------------

    def detect_overcommitment(
        self,
        planned_minutes: int,
        capacity_hours: float,
    ) -> tuple[bool, float]:
        """
        Returns (is_overcommitted, overcommitment_ratio).

        overcommitment_ratio = planned_minutes / (capacity_hours * 60)
        Threshold: > 1.2 (20% over capacity) triggers overcommitment signal.
        """
        capacity_minutes = capacity_hours * 60
        ratio = planned_minutes / max(capacity_minutes, 1.0)
        return ratio > 1.2, round(ratio, 3)
