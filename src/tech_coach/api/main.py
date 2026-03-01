"""
FastAPI application factory.

This module creates the ASGI application, configures middleware,
sets up dependency injection, and registers routers.

Startup sequence:
  1. Load settings (fail fast if misconfigured)
  2. Configure structured logging
  3. Initialize DB engine (connection pool)
  4. Initialize LLM client (Vertex AI SDK)
  5. Initialize Redis cache
  6. Register routers
  7. Mount health check endpoint

Shutdown:
  1. Close Redis connection pool
  2. Dispose DB connection pool
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tech_coach.api.middleware.auth_middleware import AuthMiddleware
from tech_coach.api.middleware.trace_middleware import TraceMiddleware
from tech_coach.api.routers import auth, goals, plans, reflections, sessions, signals
from tech_coach.config import get_settings
from tech_coach.infrastructure.db.session import engine
from tech_coach.infrastructure.llm.cache import LLMCache
from tech_coach.infrastructure.llm.prompt_registry import PromptRegistry
from tech_coach.infrastructure.llm.vertex_client import VertexAIClient
from tech_coach.infrastructure.observability.cost_estimator import CostEstimator
from tech_coach.infrastructure.observability.logger import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """
    Application lifespan: startup and shutdown.
    """
    settings = get_settings()
    configure_logging()

    logger.info(
        "app.starting",
        env=settings.app_env.value,
        project=settings.gcp_project_id,
    )

    # Initialize LLM infrastructure
    prompts_dir = Path(__file__).parent.parent.parent.parent.parent / "prompts" / "v1"
    registry = PromptRegistry(prompts_dir=prompts_dir)
    cache = LLMCache()
    cost_estimator = CostEstimator()
    llm_client = VertexAIClient(
        prompt_registry=registry,
        cache=cache,
        cost_estimator=cost_estimator,
    )

    # Attach to app state for dependency injection
    app.state.llm_client = llm_client
    app.state.llm_cache = cache
    app.state.prompt_registry = registry

    logger.info("app.started")
    yield

    # Shutdown
    logger.info("app.shutting_down")
    await cache.close()
    await engine.dispose()
    logger.info("app.shutdown_complete")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Tech Coach API",
        description="Production-grade AI Coaching Platform",
        version="0.1.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # --- Middleware (applied in reverse order of registration) ---
    app.add_middleware(TraceMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8501"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Trace-ID"],
    )

    # --- Routers ---
    api_prefix = "/api/v1"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(goals.router, prefix=api_prefix, tags=["goals"])
    app.include_router(plans.router, prefix=api_prefix, tags=["plans"])
    app.include_router(reflections.router, prefix=api_prefix, tags=["reflections"])
    app.include_router(sessions.router, prefix=api_prefix, tags=["sessions"])
    app.include_router(signals.router, prefix=api_prefix, tags=["signals"])

    # --- Health check (unauthenticated) ---
    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "env": settings.app_env.value}

    @app.get("/ready", tags=["ops"])
    async def readiness() -> dict:
        """Kubernetes/Cloud Run readiness probe — checks DB connectivity."""
        from sqlalchemy import text
        from tech_coach.infrastructure.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
