"""Behavioral signals API router — read access for frontend analytics."""

from __future__ import annotations

import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tech_coach.api.dependencies import get_current_user, get_signal_repository
from tech_coach.domain.models.behavioral_signal import SignalType
from tech_coach.domain.models.user import User
from tech_coach.domain.repositories.signal_repository import SignalRepository

router = APIRouter(prefix="/signals")


@router.get("/recent")
async def get_recent_signals(
    days: int = 14,
    current_user: User = Depends(get_current_user),
    signal_repo: SignalRepository = Depends(get_signal_repository),
) -> list[dict]:
    """Return signals from the last N days for the authenticated user."""
    since = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    signals = await signal_repo.get_by_user_since(current_user.id, since)
    return [
        {
            "id": str(s.id),
            "signal_type": s.signal_type.value,
            "intensity": s.intensity,
            "goal_id": str(s.goal_id) if s.goal_id else None,
            "recorded_at": s.recorded_at.isoformat(),
        }
        for s in signals
    ]


@router.get("/completion-rate")
async def get_completion_rate(
    days: int = 14,
    current_user: User = Depends(get_current_user),
    signal_repo: SignalRepository = Depends(get_signal_repository),
) -> dict:
    """Return task completion rate for the specified period."""
    until = datetime.datetime.utcnow()
    since = until - datetime.timedelta(days=days)
    rate = await signal_repo.get_completion_rate(current_user.id, since, until)
    return {"completion_rate": round(rate, 4), "period_days": days}
