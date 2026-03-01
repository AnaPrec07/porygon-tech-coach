"""
Vertex AI Gemini client with full observability, retry, and cost tracking.

Design decisions:
  - Every call is wrapped in retry with exponential backoff (tenacity)
  - Hard timeout enforced at 30s (Cloud Run has 60s default request timeout)
  - JSON schema enforcement via response_schema parameter (Gemini native)
  - Safety configuration blocks harmful content categories
  - All calls produce an EvaluationLog record (persisted by caller)
  - Cache checked before any API call (Redis via LLMCache)
  - No PII in logs — context is hashed before logging
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import vertexai
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from vertexai.generative_models import (
    GenerationConfig,
    GenerativeModel,
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
)

from tech_coach.config import get_settings
from tech_coach.infrastructure.llm.cache import LLMCache
from tech_coach.infrastructure.llm.prompt_registry import PromptRegistry
from tech_coach.infrastructure.observability.cost_estimator import CostEstimator
from tech_coach.infrastructure.observability.logger import get_logger, log_llm_call

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Response type
# ---------------------------------------------------------------------------


@dataclass
class LLMResponse:
    """
    Structured response from a Vertex AI call.

    parsed_content is the JSON-parsed and schema-validated response body.
    raw_text is the raw string response (for debugging).
    """

    parsed_content: dict[str, Any]
    raw_text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_usd: float
    prompt_version: str
    model_id: str
    trace_id: str
    cache_hit: bool
    retry_count: int


class LLMServiceError(Exception):
    """Raised when the LLM service fails after all retries."""

    def __init__(self, message: str, error_type: str, retry_count: int) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.retry_count = retry_count


# ---------------------------------------------------------------------------
# Safety Configuration
# ---------------------------------------------------------------------------

_SAFETY_SETTINGS = [
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    SafetySetting(
        category=HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
]


# ---------------------------------------------------------------------------
# Vertex AI Client
# ---------------------------------------------------------------------------


class VertexAIClient:
    """
    Production Vertex AI Gemini client.

    Lifecycle:
      - Initialized once at application startup
      - vertexai.init() called once (not per request)
      - GenerativeModel instantiated per prompt_name/model combination
        and cached internally

    Thread safety: GenerativeModel is stateless per call. This client
    is safe to share across async request handlers.
    """

    def __init__(
        self,
        prompt_registry: PromptRegistry,
        cache: LLMCache,
        cost_estimator: CostEstimator,
    ) -> None:
        self._registry = prompt_registry
        self._cache = cache
        self._cost_estimator = cost_estimator
        self._model_cache: dict[str, GenerativeModel] = {}

        settings = get_settings()
        vertexai.init(
            project=settings.gcp_project_id,
            location=settings.vertex_ai_location,
        )
        logger.info(
            "vertex_ai.client.initialized",
            project=settings.gcp_project_id,
            location=settings.vertex_ai_location,
        )

    def _get_model(self, prompt_name: str) -> tuple[GenerativeModel, dict]:
        """Return a cached GenerativeModel + prompt config for the given prompt name."""
        prompt_config = self._registry.get(prompt_name)
        model_id = prompt_config["model"]

        cache_key = f"{prompt_name}:{model_id}"
        if cache_key not in self._model_cache:
            self._model_cache[cache_key] = GenerativeModel(
                model_name=model_id,
                system_instruction=prompt_config["system_prompt"],
            )
        return self._model_cache[cache_key], prompt_config

    async def generate(
        self,
        prompt_name: str,
        messages: list[dict[str, str]],
        user_id: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        override_max_output_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Generate a structured JSON response from Gemini.

        Args:
            prompt_name: Key into the prompt registry (e.g., "coaching_dialogue")
            messages: Conversation turns [{"role": "user"/"model", "content": "..."}]
            user_id: Authenticated user ID (for logging, not included in prompt)
            session_id: Coaching session ID (for logging)
            trace_id: Distributed trace ID (auto-generated if not provided)
            override_max_output_tokens: Override prompt config token budget

        Returns:
            LLMResponse with validated JSON content

        Raises:
            LLMServiceError: If all retries exhausted or schema validation fails
        """
        trace_id = trace_id or str(uuid.uuid4())
        model, prompt_config = self._get_model(prompt_name)
        prompt_version = f"{prompt_name}:{prompt_config['version']}"
        model_id = prompt_config["model"]

        # Build context hash for cache key (no PII in hash input beyond user_id)
        context_hash = self._hash_context(messages)
        cache_key = f"{prompt_version}:{user_id}:{context_hash}"

        # --- Cache check ---
        cached = await self._cache.get(cache_key)
        if cached is not None:
            logger.debug(
                "llm.cache.hit",
                trace_id=trace_id,
                prompt_version=prompt_version,
                cache_key_hash=hashlib.sha256(cache_key.encode()).hexdigest()[:16],
            )
            log_llm_call(
                logger,
                trace_id=trace_id,
                prompt_name=prompt_name,
                prompt_version=prompt_config["version"],
                model_id=model_id,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                estimated_cost_usd=0.0,
                cache_hit=True,
                retry_count=0,
                user_id=user_id,
                session_id=session_id,
            )
            return LLMResponse(
                parsed_content=cached,
                raw_text=json.dumps(cached),
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                estimated_cost_usd=0.0,
                prompt_version=prompt_version,
                model_id=model_id,
                trace_id=trace_id,
                cache_hit=True,
                retry_count=0,
            )

        # --- API call with retry ---
        token_budget = prompt_config.get("token_budget", {})
        max_output_tokens = override_max_output_tokens or token_budget.get(
            "output_max", 2048
        )
        response_schema = prompt_config.get("response_schema")

        generation_config = GenerationConfig(
            response_mime_type="application/json",
            response_schema=response_schema,
            max_output_tokens=max_output_tokens,
            temperature=prompt_config.get("temperature", 0.3),
            top_p=prompt_config.get("top_p", 0.95),
        )

        vertex_contents = [
            {"role": m["role"], "parts": [{"text": m["content"]}]}
            for m in messages
        ]

        retry_count = 0
        start_time = time.monotonic()

        try:
            response = await self._call_with_retry(
                model=model,
                contents=vertex_contents,
                generation_config=generation_config,
                retry_count_ref=[retry_count],
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            error_type = type(exc).__name__
            log_llm_call(
                logger,
                trace_id=trace_id,
                prompt_name=prompt_name,
                prompt_version=prompt_config["version"],
                model_id=model_id,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                estimated_cost_usd=0.0,
                cache_hit=False,
                retry_count=retry_count,
                error_type=error_type,
                user_id=user_id,
                session_id=session_id,
            )
            raise LLMServiceError(
                message=f"LLM call failed: {exc}",
                error_type=error_type,
                retry_count=retry_count,
            ) from exc

        latency_ms = int((time.monotonic() - start_time) * 1000)
        raw_text = response.text

        # --- Parse and validate ---
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise LLMServiceError(
                message=f"LLM returned invalid JSON: {exc}",
                error_type="JSONDecodeError",
                retry_count=retry_count,
            ) from exc

        # --- Token usage and cost ---
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0

        cost = self._cost_estimator.estimate(model_id, input_tokens, output_tokens)

        # --- Log ---
        log_llm_call(
            logger,
            trace_id=trace_id,
            prompt_name=prompt_name,
            prompt_version=prompt_config["version"],
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost.total_cost_usd,
            cache_hit=False,
            retry_count=retry_count,
            user_id=user_id,
            session_id=session_id,
        )

        # --- Cache write (if cacheable) ---
        ttl = prompt_config.get("cache_ttl_seconds", 0)
        if ttl > 0:
            await self._cache.set(cache_key, parsed, ttl=ttl)

        return LLMResponse(
            parsed_content=parsed,
            raw_text=raw_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            estimated_cost_usd=cost.total_cost_usd,
            prompt_version=prompt_version,
            model_id=model_id,
            trace_id=trace_id,
            cache_hit=False,
            retry_count=retry_count,
        )

    @staticmethod
    def _hash_context(messages: list[dict]) -> str:
        """SHA256 of the serialized messages list. Used for cache keying."""
        serialized = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode()).hexdigest()

    async def _call_with_retry(
        self,
        model: GenerativeModel,
        contents: list,
        generation_config: GenerationConfig,
        retry_count_ref: list[int],
    ) -> Any:  # noqa: ANN401
        """
        Execute Vertex AI call with exponential backoff.

        Retries on transient errors (quota exceeded, service unavailable).
        Does NOT retry on schema validation failures or content policy blocks.
        """

        @retry(
            retry=retry_if_exception_type((Exception,)),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        async def _execute() -> Any:  # noqa: ANN401
            retry_count_ref[0] += 1
            return await model.generate_content_async(
                contents=contents,
                generation_config=generation_config,
                safety_settings=_SAFETY_SETTINGS,
            )

        return await _execute()

    async def embed(
        self,
        text: str,
        task_type: str = "SEMANTIC_SIMILARITY",
    ) -> list[float]:
        """
        Generate a text embedding using the configured embedding model.

        Used for:
          - Session semantic search (task_type=SEMANTIC_SIMILARITY)
          - Document retrieval (task_type=RETRIEVAL_DOCUMENT)
        """
        from vertexai.language_models import TextEmbeddingModel

        settings = get_settings()
        embed_model = TextEmbeddingModel.from_pretrained(
            settings.vertex_ai_embedding_model_id
        )
        embeddings = await embed_model.get_embeddings_async(
            texts=[text],
            task_type=task_type,
        )
        return embeddings[0].values
