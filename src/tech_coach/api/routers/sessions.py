"""Coaching sessions API router."""

from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from tech_coach.api.dependencies import (
    get_current_user,
    get_goal_repository,
    get_llm_client,
    get_session_repository,
    get_signal_repository,
)
from tech_coach.application.use_cases.send_coaching_message import (
    SendCoachingMessage,
    SendMessageInput,
)
from tech_coach.domain.models.coaching_session import CoachingSession, SessionType
from tech_coach.domain.models.user import User
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.domain.repositories.session_repository import SessionRepository
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.domain.services.planning_engine import PlanningEngine
from tech_coach.infrastructure.llm.vertex_client import VertexAIClient
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/sessions")


class StartSessionRequest(BaseModel):
    session_type: SessionType
    goal_ids: list[UUID] = []


class SendMessageRequest(BaseModel):
    content: str


class MessageResponse(BaseModel):
    session_id: UUID
    message_id: UUID
    response: str
    is_fallback: bool
    token_usage: dict[str, int]
    estimated_cost_usd: float


@router.post("/", status_code=status.HTTP_201_CREATED)
async def start_session(
    body: StartSessionRequest,
    current_user: User = Depends(get_current_user),
    repo: SessionRepository = Depends(get_session_repository),
) -> dict:
    from datetime import datetime
    session = CoachingSession(
        user_id=current_user.id,
        session_type=body.session_type,
        goal_ids=body.goal_ids,
        started_at=datetime.utcnow(),
    )
    saved = await repo.save(session)
    return {"session_id": str(saved.id), "session_type": saved.session_type.value}


@router.post("/{session_id}/messages", response_model=MessageResponse)
async def send_message(
    session_id: UUID,
    body: SendMessageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    session_repo: SessionRepository = Depends(get_session_repository),
    goal_repo: GoalRepository = Depends(get_goal_repository),
    signal_repo: SignalRepository = Depends(get_signal_repository),
    llm_client: VertexAIClient = Depends(get_llm_client),
) -> MessageResponse:
    use_case = SendCoachingMessage(
        session_repository=session_repo,
        goal_repository=goal_repo,
        signal_repository=signal_repo,
        llm_client=llm_client,
        planning_engine=PlanningEngine(),
    )

    try:
        result = await use_case.execute(
            SendMessageInput(
                session_id=session_id,
                user_id=current_user.id,
                content=body.content,
                trace_id=request.state.trace_id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return MessageResponse(
        session_id=result.session_id,
        message_id=result.message_id,
        response=result.response_content,
        is_fallback=result.is_fallback,
        token_usage=result.token_usage,
        estimated_cost_usd=result.estimated_cost_usd,
    )


@router.patch("/{session_id}/end", status_code=status.HTTP_200_OK)
async def end_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: SessionRepository = Depends(get_session_repository),
) -> dict:
    from datetime import datetime
    session = await repo.get_by_id(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    updated = session.model_copy(
        update={"status": "completed", "ended_at": datetime.utcnow()}
    )
    await repo.save(updated)
    return {
        "session_id": str(session_id),
        "status": "completed",
        "total_cost_usd": updated.total_cost_usd,
        "total_tokens": updated.total_tokens_used,
    }


@router.get("/{session_id}")
async def get_session(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
    repo: SessionRepository = Depends(get_session_repository),
) -> dict:
    session = await repo.get_by_id(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": str(session.id),
        "session_type": session.session_type.value,
        "status": session.status.value,
        "message_count": len(session.messages),
        "total_cost_usd": session.total_cost_usd,
        "started_at": session.started_at.isoformat(),
    }
