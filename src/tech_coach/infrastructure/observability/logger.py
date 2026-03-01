"""
Structured JSON logger with Google Cloud Logging integration.

Design:
  - structlog for structured, context-aware logging
  - PII redaction: goal text, reflection content, email addresses are never logged
  - Every log entry includes trace_id for correlation with Cloud Trace
  - Production: emits JSON to stdout (Cloud Run captures → Cloud Logging)
  - Development: human-readable console output

Usage:
    from tech_coach.infrastructure.observability.logger import get_logger

    logger = get_logger(__name__)
    logger.info("llm.call.completed", trace_id=trace_id, tokens=1024, latency_ms=450)
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from tech_coach.config import get_settings

# PII field names that must never appear in logs
_PII_FIELDS = frozenset(
    {
        "email",
        "user_email",
        "display_name",
        "goal_text",
        "goal_title",
        "goal_description",
        "reflection_content",
        "message_content",
        "raw_text",
        "system_prompt",
        "user_message",
    }
)


def _redact_pii(logger: Any, method: str, event_dict: dict) -> dict:  # noqa: ANN401
    """structlog processor: redact PII fields before emission."""
    for field in _PII_FIELDS:
        if field in event_dict:
            event_dict[field] = "[REDACTED]"
    return event_dict


def _add_environment(logger: Any, method: str, event_dict: dict) -> dict:  # noqa: ANN401
    """Add environment tag to every log entry."""
    event_dict["env"] = get_settings().app_env.value
    return event_dict


def configure_logging() -> None:
    """
    Configure structlog for the application.

    Call once at startup in api/main.py.
    """
    settings = get_settings()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact_pii,
        _add_environment,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.is_production:
        # Cloud Logging expects JSON on stdout
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
            logger_factory=structlog.PrintLoggerFactory(sys.stdout),
            cache_logger_on_first_use=True,
        )
    else:
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, settings.log_level.upper(), logging.DEBUG)
            ),
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


# ---------------------------------------------------------------------------
# LLM Call Log Entry
# ---------------------------------------------------------------------------


def log_llm_call(
    logger: structlog.stdlib.BoundLogger,
    *,
    trace_id: str,
    prompt_name: str,
    prompt_version: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    estimated_cost_usd: float,
    cache_hit: bool,
    retry_count: int,
    eval_score: float | None = None,
    error_type: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """
    Emit a structured log entry for an LLM call.

    This log is analytics-ready: all numeric fields are included so that
    BigQuery queries can compute cost/latency aggregates without parsing.
    """
    log_method = logger.error if error_type else logger.info
    log_method(
        "llm.call.completed",
        trace_id=trace_id,
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        latency_ms=latency_ms,
        estimated_cost_usd=estimated_cost_usd,
        cache_hit=cache_hit,
        retry_count=retry_count,
        eval_score=eval_score,
        error_type=error_type,
        user_id=user_id,
        session_id=session_id,
    )
