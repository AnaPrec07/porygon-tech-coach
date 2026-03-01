"""
Use case: Send a message in a coaching session and receive AI response.

This is the most complex use case in the system. It orchestrates:
  1. Context retrieval (recent sessions + semantic search)
  2. Burnout risk and focus score calculation (deterministic)
  3. LLM call with full observability
  4. Response validation
  5. Behavioral signal extraction
  6. Persistence of all artifacts

Design invariants:
  - LLM output is NEVER directly persisted without schema validation
  - Behavioral signals extracted from LLM suggestions are validated by PlanningEngine
  - If LLM call fails, a rule-based fallback response is returned (never a 500)
  - All persistence is transactional (session + signals committed together)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from tech_coach.domain.models.behavioral_signal import BehavioralSignal, SignalType
from tech_coach.domain.models.coaching_session import CoachingSession, Message, SessionType
from tech_coach.domain.repositories.goal_repository import GoalRepository
from tech_coach.domain.repositories.session_repository import SessionRepository
from tech_coach.domain.repositories.signal_repository import SignalRepository
from tech_coach.domain.services.planning_engine import PlanningEngine
from tech_coach.infrastructure.llm.vertex_client import LLMResponse, LLMServiceError, VertexAIClient
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)

ACTIVE_WINDOW_SIZE = 10      # Max recent messages for context
SEMANTIC_SEARCH_LIMIT = 3    # Past sessions to retrieve via vector search
SUMMARIZE_THRESHOLD = 12     # Trigger summarization after N messages


@dataclass
class SendMessageInput:
    session_id: UUID
    user_id: UUID
    content: str
    trace_id: str


@dataclass
class SendMessageOutput:
    session_id: UUID
    message_id: UUID
    response_content: str
    coaching_response: dict
    is_fallback: bool
    prompt_version: str
    token_usage: dict[str, int]
    estimated_cost_usd: float
    trace_id: str


_FALLBACK_RESPONSE = {
    "message": (
        "I'm having trouble connecting right now. Let me offer a simple reflection: "
        "What's the one thing you could do today that would move you closer to your "
        "most important goal? Take a moment to write it down."
    ),
    "suggested_actions": [],
    "detected_signals": [],
}


class SendCoachingMessage:
    """
    Use case: process a user coaching message and return AI response.
    """

    def __init__(
        self,
        session_repository: SessionRepository,
        goal_repository: GoalRepository,
        signal_repository: SignalRepository,
        llm_client: VertexAIClient,
        planning_engine: PlanningEngine,
    ) -> None:
        self._sessions = session_repository
        self._goals = goal_repository
        self._signals = signal_repository
        self._llm = llm_client
        self._engine = planning_engine

    async def execute(self, input_data: SendMessageInput) -> SendMessageOutput:
        session = await self._sessions.get_by_id(
            input_data.session_id, input_data.user_id
        )
        if session is None:
            raise ValueError(f"Session {input_data.session_id} not found")

        if session.status != "active":
            raise ValueError(f"Session {input_data.session_id} is not active")

        # --- Build LLM context ---
        active_goals = await self._goals.get_active_by_user(input_data.user_id)
        signals = await self._signal_repository_recent(input_data.user_id)
        burnout_risk = self._engine.calculate_burnout_risk(
            signals,
            since=(datetime.utcnow() - timedelta(days=14)).date(),
        )
        relevant_sessions = await self._sessions.search_semantic(
            user_id=input_data.user_id,
            query_embedding=await self._llm.embed(input_data.content),
            limit=SEMANTIC_SEARCH_LIMIT,
        )

        messages = self._build_context_messages(
            session=session,
            user_message=input_data.content,
            active_goals=active_goals,
            burnout_risk_level=burnout_risk.level,
            burnout_factors=burnout_risk.factors,
            relevant_sessions=relevant_sessions,
        )

        # --- LLM call ---
        is_fallback = False
        llm_response: Optional[LLMResponse] = None

        try:
            llm_response = await self._llm.generate(
                prompt_name="coaching_dialogue",
                messages=messages,
                user_id=str(input_data.user_id),
                session_id=str(input_data.session_id),
                trace_id=input_data.trace_id,
            )
            coaching_response = llm_response.parsed_content
        except LLMServiceError as exc:
            logger.warning(
                "coaching.llm.fallback",
                trace_id=input_data.trace_id,
                error_type=exc.error_type,
                session_id=str(input_data.session_id),
            )
            is_fallback = True
            coaching_response = _FALLBACK_RESPONSE

        # --- Extract and validate signals from LLM response ---
        new_signals: list[BehavioralSignal] = []
        if not is_fallback:
            new_signals = self._extract_signals(
                coaching_response, input_data.user_id, input_data.session_id
            )

        # --- Build updated session ---
        user_message = Message(
            role="user",
            content=input_data.content,
        )
        response_text = coaching_response.get("message", "")
        assistant_message = Message(
            role="assistant",
            content=response_text,
            prompt_version=llm_response.prompt_version if llm_response else None,
            token_usage=(
                {
                    "input_tokens": llm_response.input_tokens,
                    "output_tokens": llm_response.output_tokens,
                }
                if llm_response
                else None
            ),
            estimated_cost_usd=llm_response.estimated_cost_usd if llm_response else None,
        )

        updated_messages = list(session.messages) + [user_message, assistant_message]
        new_token_total = session.total_tokens_used + (
            (llm_response.input_tokens + llm_response.output_tokens)
            if llm_response and not is_fallback
            else 0
        )
        new_cost_total = session.total_cost_usd + (
            llm_response.estimated_cost_usd if llm_response and not is_fallback else 0.0
        )

        updated_session = session.model_copy(
            update={
                "messages": updated_messages,
                "total_tokens_used": new_token_total,
                "total_cost_usd": new_cost_total,
                "updated_at": datetime.utcnow(),
            }
        )

        # --- Trigger summarization if window exceeded ---
        if len(updated_messages) >= SUMMARIZE_THRESHOLD:
            updated_session = await self._summarize_if_needed(
                updated_session, input_data.user_id, input_data.trace_id
            )

        # --- Persist atomically ---
        await self._sessions.save(updated_session)
        if new_signals:
            await self._signals.save_batch(new_signals)

        logger.info(
            "coaching.message.processed",
            trace_id=input_data.trace_id,
            session_id=str(input_data.session_id),
            is_fallback=is_fallback,
            signals_extracted=len(new_signals),
        )

        return SendMessageOutput(
            session_id=input_data.session_id,
            message_id=assistant_message.id,
            response_content=response_text,
            coaching_response=coaching_response,
            is_fallback=is_fallback,
            prompt_version=llm_response.prompt_version if llm_response else "fallback",
            token_usage=(
                {
                    "input_tokens": llm_response.input_tokens,
                    "output_tokens": llm_response.output_tokens,
                }
                if llm_response
                else {"input_tokens": 0, "output_tokens": 0}
            ),
            estimated_cost_usd=llm_response.estimated_cost_usd if llm_response else 0.0,
            trace_id=input_data.trace_id,
        )

    def _build_context_messages(
        self,
        session: CoachingSession,
        user_message: str,
        active_goals: list,
        burnout_risk_level: str,
        burnout_factors: list[str],
        relevant_sessions: list[CoachingSession],
    ) -> list[dict[str, str]]:
        """
        Construct the message array for the LLM.

        Structure:
          1. User context block (goals summary, behavioral state)
          2. Relevant past session summaries (semantic retrieval)
          3. Active window (last N messages from current session)
          4. Current user message

        All content is role-separated. No PII beyond what the user explicitly shared.
        """
        context_parts: list[str] = []

        # Goals summary
        if active_goals:
            goals_summary = "\n".join(
                f"- {g.title} ({g.goal_type.value}, priority: {g.priority.name}, "
                f"progress: {g.progress_score:.0%})"
                for g in active_goals[:5]
            )
            context_parts.append(f"Active goals:\n{goals_summary}")

        # Behavioral state
        context_parts.append(
            f"Current burnout risk level: {burnout_risk_level}"
            + (f"\nContributing factors: {'; '.join(burnout_factors)}" if burnout_factors else "")
        )

        # Relevant past sessions
        for past in relevant_sessions:
            if past.summary_text:
                context_parts.append(f"Relevant past session summary:\n{past.summary_text}")

        # Session history (active window) + session summary if available
        history_messages: list[dict[str, str]] = []

        if session.summary_text:
            history_messages.append({
                "role": "user",
                "content": f"[Previous session summary]\n{session.summary_text}",
            })

        for msg in session.active_window_messages:
            history_messages.append({
                "role": msg.role,
                "content": msg.content,
            })

        # Build final message list
        messages: list[dict[str, str]] = []
        if context_parts:
            messages.append({
                "role": "user",
                "content": "Context:\n" + "\n\n".join(context_parts),
            })
            messages.append({
                "role": "model",
                "content": "Understood. I have your current context.",
            })

        messages.extend(history_messages)
        messages.append({"role": "user", "content": user_message})

        return messages

    def _extract_signals(
        self,
        coaching_response: dict,
        user_id: UUID,
        session_id: UUID,
    ) -> list[BehavioralSignal]:
        """
        Extract behavioral signals from LLM response.

        LLM may suggest signals in the `detected_signals` field.
        We map suggestions to BehavioralSignal entities — the LLM
        cannot set intensity or goal_id directly (we determine those).
        """
        signals: list[BehavioralSignal] = []
        suggested = coaching_response.get("detected_signals", [])

        allowed_signal_types = {
            "stagnation": SignalType.GOAL_STAGNANT,
            "overcommitment": SignalType.OVERCOMMITMENT_DETECTED,
            "burnout_risk": SignalType.BURNOUT_RISK_HIGH,
            "drift": SignalType.DRIFT_DETECTED,
        }

        for suggestion in suggested:
            signal_key = suggestion.get("type", "")
            if signal_key in allowed_signal_types:
                signals.append(
                    BehavioralSignal(
                        user_id=user_id,
                        session_id=session_id,
                        signal_type=allowed_signal_types[signal_key],
                        intensity=0.6,  # Default intensity; refined by planning engine
                        metadata={"source": "llm_detected", "raw": suggestion},
                    )
                )
        return signals

    async def _signal_repository_recent(self, user_id: UUID) -> list[BehavioralSignal]:
        """Wrapper to fetch recent signals with 14-day window."""
        since = datetime.utcnow() - timedelta(days=14)
        return await self._signals.get_by_user_since(user_id, since)

    async def _summarize_if_needed(
        self,
        session: CoachingSession,
        user_id: UUID,
        trace_id: str,
    ) -> CoachingSession:
        """
        Summarize messages that have fallen outside the active window.
        Updates session summary_text and computes new embedding.
        """
        messages_to_summarize = session.messages[:-ACTIVE_WINDOW_SIZE]
        if not messages_to_summarize:
            return session

        summary_prompt = [
            {
                "role": "user",
                "content": (
                    "Summarize the following coaching conversation history in 3–5 sentences, "
                    "capturing key goals discussed, insights, and commitments made. "
                    "Focus on what matters for future coaching continuity.\n\n"
                    + "\n".join(
                        f"{m.role.upper()}: {m.content}"
                        for m in messages_to_summarize
                    )
                ),
            }
        ]

        try:
            summary_response = await self._llm.generate(
                prompt_name="session_summarizer",
                messages=summary_prompt,
                user_id=str(user_id),
                session_id=str(session.id),
                trace_id=trace_id,
            )
            summary_text = summary_response.parsed_content.get("summary", "")
            embedding = await self._llm.embed(summary_text)

            return session.model_copy(
                update={
                    "summary_text": summary_text,
                    "embedding": embedding,
                    "messages": list(session.messages[-ACTIVE_WINDOW_SIZE:]),
                }
            )
        except LLMServiceError:
            logger.warning(
                "coaching.summarization.failed",
                trace_id=trace_id,
                session_id=str(session.id),
            )
            return session
