"""Redis-based LLM response cache."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from tech_coach.config import get_settings
from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)


class LLMCache:
    """
    Async Redis cache for LLM responses.

    Cache keys are built from: prompt_version + user_id + context_hash
    This ensures:
      - Cache is invalidated when prompt version changes
      - Cache is isolated per user (no cross-user contamination)
      - Cache hits require identical context (no stale results for evolving conversations)

    Cache misses are silent (return None). Cache write failures are logged but
    do not fail the request (degraded mode: uncached responses).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        self._default_ttl = settings.cache_default_ttl_seconds

    async def get(self, key: str) -> dict[str, Any] | None:
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("llm.cache.get.error", error=str(exc))
            return None

    async def set(self, key: str, value: dict[str, Any], ttl: int | None = None) -> None:
        try:
            serialized = json.dumps(value)
            await self._client.setex(
                name=key,
                time=ttl or self._default_ttl,
                value=serialized,
            )
        except Exception as exc:
            logger.warning("llm.cache.set.error", error=str(exc))

    async def invalidate(self, pattern: str) -> int:
        """Invalidate all keys matching a glob pattern. Returns count deleted."""
        try:
            keys = await self._client.keys(pattern)
            if not keys:
                return 0
            return await self._client.delete(*keys)
        except Exception as exc:
            logger.warning("llm.cache.invalidate.error", error=str(exc))
            return 0

    async def close(self) -> None:
        await self._client.aclose()
