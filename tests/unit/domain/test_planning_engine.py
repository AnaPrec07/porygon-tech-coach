"""Unit tests for the PlanningEngine.

These tests cover the core deterministic logic that must never break.
No mocks, no external dependencies — pure function inputs/outputs.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType
from tech_coach.domain.models.goal import Goal, GoalPriority, GoalStatus, GoalType
from tech_coach.domain.models.weekly_plan import CognitiveLoad, Task, TaskStatus
from tech_coach.domain.services.planning_engine import (
    BURNOUT_WINDOW_DAYS,
    MAX_ACTIVE_GOALS_PER_WEEK,
    PlanningEngine,
)

USER_ID = uuid.uuid4()
engine = PlanningEngine()


def make_goal(
    priority: GoalPriority = GoalPriority.MEDIUM,
    status: GoalStatus = GoalStatus.ACTIVE,
    target_days: int = 60,
) -> Goal:
    return Goal(
        user_id=USER_ID,
        title=f"Goal-{uuid.uuid4().hex[:6]}",
        description="Test goal",
        goal_type=GoalType.QUARTERLY,
        priority=priority,
        status=status,
        target_date=date.today() + timedelta(days=target_days),
    )


def make_signal(signal_type: SignalType, days_ago: int = 0) -> BehavioralSignal:
    return BehavioralSignal(
        user_id=USER_ID,
        signal_type=signal_type,
        recorded_at=datetime.utcnow() - timedelta(days=days_ago),
    )


class TestBurnoutRisk:

    def test_no_signals_returns_zero_risk(self) -> None:
        result = engine.calculate_burnout_risk([], since=date.today() - timedelta(days=14))
        assert result.value == 0.0
        assert result.level == "low"
        assert result.factors == []

    def test_all_completed_tasks_low_risk(self) -> None:
        signals = [make_signal(SignalType.TASK_COMPLETED, days_ago=i) for i in range(10)]
        result = engine.calculate_burnout_risk(
            signals, since=date.today() - timedelta(days=14)
        )
        assert result.value < 0.3

    def test_all_skipped_tasks_high_risk(self) -> None:
        signals = [make_signal(SignalType.TASK_SKIPPED, days_ago=i) for i in range(10)]
        result = engine.calculate_burnout_risk(
            signals, since=date.today() - timedelta(days=14)
        )
        assert result.value > 0.3

    def test_overcommitment_signals_increase_risk(self) -> None:
        signals = [
            make_signal(SignalType.OVERCOMMITMENT_DETECTED, days_ago=i)
            for i in range(5)
        ]
        result = engine.calculate_burnout_risk(
            signals, since=date.today() - timedelta(days=14)
        )
        assert result.value > 0.0

    def test_burnout_risk_is_clamped_to_one(self) -> None:
        signals = (
            [make_signal(SignalType.TASK_SKIPPED, days_ago=i) for i in range(14)]
            + [make_signal(SignalType.OVERCOMMITMENT_DETECTED, days_ago=i) for i in range(14)]
            + [make_signal(SignalType.SESSION_ABANDONED, days_ago=30)]
        )
        result = engine.calculate_burnout_risk(
            signals, since=date.today() - timedelta(days=14)
        )
        assert 0.0 <= result.value <= 1.0

    def test_level_labels(self) -> None:
        from dataclasses import dataclass
        from tech_coach.domain.services.planning_engine import BurnoutRiskScore

        assert BurnoutRiskScore(0.1, [], datetime.utcnow()).level == "low"
        assert BurnoutRiskScore(0.3, [], datetime.utcnow()).level == "moderate"
        assert BurnoutRiskScore(0.6, [], datetime.utcnow()).level == "high"
        assert BurnoutRiskScore(0.8, [], datetime.utcnow()).level == "critical"


class TestWeeklyTimeAllocation:

    def test_returns_max_active_goals(self) -> None:
        goals = [make_goal() for _ in range(6)]
        from tech_coach.domain.services.planning_engine import BurnoutRiskScore
        burnout = BurnoutRiskScore(0.0, [], datetime.utcnow())

        ctx = engine.allocate_weekly_time(goals, 40.0, burnout, [])
        assert len(ctx.active_goals) <= MAX_ACTIVE_GOALS_PER_WEEK

    def test_burnout_reduces_capacity(self) -> None:
        goals = [make_goal()]
        from tech_coach.domain.services.planning_engine import BurnoutRiskScore
        high_burnout = BurnoutRiskScore(0.9, [], datetime.utcnow())
        no_burnout = BurnoutRiskScore(0.0, [], datetime.utcnow())

        ctx_high = engine.allocate_weekly_time(goals, 40.0, high_burnout, [])
        ctx_low = engine.allocate_weekly_time(goals, 40.0, no_burnout, [])

        assert ctx_high.adjusted_capacity_hours < ctx_low.adjusted_capacity_hours

    def test_allocations_sum_within_capacity(self) -> None:
        goals = [make_goal() for _ in range(3)]
        from tech_coach.domain.services.planning_engine import BurnoutRiskScore
        burnout = BurnoutRiskScore(0.0, [], datetime.utcnow())

        ctx = engine.allocate_weekly_time(goals, 20.0, burnout, [])
        total_allocated = sum(a.allocated_hours for a in ctx.goal_allocations)
        assert total_allocated <= ctx.adjusted_capacity_hours + 0.1  # float tolerance

    def test_critical_burnout_reduces_mit_limit(self) -> None:
        goals = [make_goal()]
        from tech_coach.domain.services.planning_engine import BurnoutRiskScore
        critical_burnout = BurnoutRiskScore(0.8, [], datetime.utcnow())

        ctx = engine.allocate_weekly_time(goals, 40.0, critical_burnout, [])
        assert ctx.mit_limit_per_day <= 2


class TestTaskPrioritization:

    def make_task(
        self,
        goal_id: uuid.UUID,
        estimated_minutes: int = 30,
        cognitive_load: CognitiveLoad = CognitiveLoad.MEDIUM,
        scheduled_day: int = 0,
    ) -> Task:
        return Task(
            goal_id=goal_id,
            title=f"Task {estimated_minutes}m",
            estimated_minutes=estimated_minutes,
            cognitive_load=cognitive_load,
            scheduled_day=scheduled_day,
            order_in_day=0,
        )

    def test_mit_count_per_day_does_not_exceed_limit(self) -> None:
        goal_id = uuid.uuid4()
        tasks = [self.make_task(goal_id, scheduled_day=0) for _ in range(6)]
        goal_priorities = {goal_id: GoalPriority.HIGH}

        result = engine.prioritize_tasks(tasks, goal_priorities, mit_limit_per_day=3)
        mit_count = sum(1 for t in result if t.is_mit and t.scheduled_day == 0)
        assert mit_count <= 3

    def test_high_priority_goal_tasks_become_mit(self) -> None:
        high_goal = uuid.uuid4()
        low_goal = uuid.uuid4()
        tasks = (
            [self.make_task(high_goal, scheduled_day=0) for _ in range(2)]
            + [self.make_task(low_goal, scheduled_day=0) for _ in range(4)]
        )
        priorities = {high_goal: GoalPriority.CRITICAL, low_goal: GoalPriority.LOW}

        result = engine.prioritize_tasks(tasks, priorities, mit_limit_per_day=2)
        mit_tasks = [t for t in result if t.is_mit]
        mit_goals = {t.goal_id for t in mit_tasks}
        assert high_goal in mit_goals


class TestProgressCalculation:

    def test_no_tasks_returns_unchanged_score(self) -> None:
        goal = make_goal()
        result = engine.calculate_goal_progress(goal, [])
        assert result.new_score == goal.progress_score
        assert result.total_tasks == 0

    def test_all_completed_returns_max_score(self) -> None:
        goal = make_goal()
        tasks = [
            Task(
                goal_id=goal.id,
                title="Task",
                estimated_minutes=30,
                cognitive_load=CognitiveLoad.MEDIUM,
                scheduled_day=0,
                order_in_day=0,
                status=TaskStatus.COMPLETED,
            )
            for _ in range(3)
        ]
        result = engine.calculate_goal_progress(goal, tasks)
        assert result.new_score == 1.0
        assert result.completion_rate == 1.0

    def test_partial_completion_returns_proportional_score(self) -> None:
        goal = make_goal()
        completed = Task(
            goal_id=goal.id,
            title="Done",
            estimated_minutes=60,
            cognitive_load=CognitiveLoad.DEEP_WORK,
            scheduled_day=0,
            order_in_day=0,
            status=TaskStatus.COMPLETED,
        )
        pending = Task(
            goal_id=goal.id,
            title="Pending",
            estimated_minutes=60,
            cognitive_load=CognitiveLoad.MEDIUM,
            scheduled_day=1,
            order_in_day=0,
            status=TaskStatus.PENDING,
        )
        result = engine.calculate_goal_progress(goal, [completed, pending])
        assert 0.4 < result.new_score < 0.6  # Approximately 50%


class TestStagnationDetection:

    def test_goal_with_no_recent_signals_is_stagnant(self) -> None:
        goal = make_goal()
        # Only old signals
        old_signal = BehavioralSignal(
            user_id=USER_ID,
            goal_id=goal.id,
            signal_type=SignalType.TASK_COMPLETED,
            recorded_at=datetime.utcnow() - timedelta(days=20),
        )
        stagnant = engine.detect_stagnant_goals([goal], [old_signal])
        assert goal in stagnant

    def test_goal_with_recent_progress_is_not_stagnant(self) -> None:
        goal = make_goal()
        recent_signal = BehavioralSignal(
            user_id=USER_ID,
            goal_id=goal.id,
            signal_type=SignalType.TASK_COMPLETED,
            recorded_at=datetime.utcnow() - timedelta(days=2),
        )
        stagnant = engine.detect_stagnant_goals([goal], [recent_signal])
        assert goal not in stagnant

    def test_non_active_goals_not_included(self) -> None:
        paused_goal = make_goal(status=GoalStatus.PAUSED)
        stagnant = engine.detect_stagnant_goals([paused_goal], [])
        assert paused_goal not in stagnant


class TestOvercommitmentDetection:

    def test_within_capacity_not_overcommitted(self) -> None:
        is_over, ratio = engine.detect_overcommitment(1200, 25.0)  # 20h planned, 25h capacity
        assert not is_over
        assert ratio < 1.0

    def test_significantly_over_capacity_is_overcommitted(self) -> None:
        is_over, ratio = engine.detect_overcommitment(2400, 25.0)  # 40h planned, 25h capacity
        assert is_over
        assert ratio > 1.2

    def test_exactly_at_threshold_is_not_overcommitted(self) -> None:
        # 1.2 threshold: 24h planned in 20h capacity = 1.2 ratio
        is_over, ratio = engine.detect_overcommitment(1440, 20.0)
        assert not is_over  # Exactly at threshold is not over
        assert abs(ratio - 1.2) < 0.01
