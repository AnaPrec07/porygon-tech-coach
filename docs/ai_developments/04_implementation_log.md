# Implementation Log

## Session: 2026-02-28 — Initial Full Implementation

### Status: Complete (v1 Scaffold)

---

## What Was Built

### Documentation (`docs/ai_developments/`)

- `01_system_design_decisions.md` — Complete design decisions including:
  - Vertex AI vs ADK tradeoff analysis
  - PostgreSQL vs document DB rationale
  - Streamlit vs React frontend tradeoff
  - Deterministic vs LLM boundary definitions
  - Prompt versioning strategy
  - Cost control architecture
  - Security design
  - Evaluation framework design
  - Multi-user evolution plan

- `02_architecture.md` — System architecture with:
  - Full ASCII architecture diagram
  - Request flow walkthrough (coaching session)
  - LLM call flow (with cache, retry, fallback)
  - Planning engine data flow
  - Complete folder structure

- `03_data_models.md` — Production schemas for all 10 entities
- `04_implementation_log.md` — This file

---

### Domain Layer (`src/tech_coach/domain/`)

**Models (Pydantic, frozen, no infra imports):**
- `user.py` — User entity with Google OAuth fields
- `goal.py` — Goal with SMART criteria, hierarchical decomposition, state machine
- `behavioral_signal.py` — 15 signal types, append-only
- `weekly_plan.py` — Task + WeeklyPlan with ADHD constraints (MIT, cognitive load)
- `coaching_session.py` — Session with message history, vector embedding
- `reflection.py` — Structured reflection template
- `skill.py` — Skill with learning resources
- `project.py` — Skill-building project

**Repository interfaces (abstract, async):**
- `GoalRepository` — 8 abstract methods
- `SignalRepository` — 5 abstract methods
- `SessionRepository` — 5 abstract methods with semantic search
- `PlanRepository` — 6 abstract methods

**Planning Engine (`services/planning_engine.py`):**
- `calculate_burnout_risk()` — 4-component composite score
- `calculate_focus_score()` — Deadline pressure + momentum + recency
- `allocate_weekly_time()` — Priority-weighted allocation with burnout reduction
- `prioritize_tasks()` — Urgency × importance matrix + MIT constraints
- `balance_cognitive_load()` — Deep work → medium → admin scheduling
- `calculate_goal_progress()` — Time-weighted task completion
- `detect_stagnant_goals()` — Signal-based stagnation detection
- `detect_overcommitment()` — Capacity ratio detection

---

### Infrastructure Layer (`src/tech_coach/infrastructure/`)

**Database:**
- `base.py` — SQLAlchemy declarative base + UUID + timestamp mixins
- `session.py` — Async session factory with connection pool config
- `models/goal.py` — Full ORM with indexes
- `models/coaching_session.py` — pgvector VECTOR(768) embedding column
- `models/evaluation_log.py` — EvaluationLog + PromptVersion ORM
- `repositories/goal_repository.py` — Full SQLAlchemy implementation

**LLM:**
- `vertex_client.py` — Production Vertex AI client with:
  - Cache check before every API call
  - Tenacity retry with exponential backoff (3 attempts: 1s, 2s, 4s)
  - 30s hard timeout
  - JSON schema enforcement via `response_schema`
  - Safety settings (4 harm categories)
  - Full token usage extraction
  - Cost logging per call
  - Embedding support (text-embedding-004)
- `prompt_registry.py` — YAML-based versioned prompt loader
- `cache.py` — Async Redis cache with graceful degradation

**Auth:**
- `jwt_handler.py` — JWT create + decode with token type validation

**Observability:**
- `logger.py` — structlog JSON logging with PII redaction (15 PII field names)
- `cost_estimator.py` — Per-call USD cost calculation (Pro + Flash pricing)

---

### Application Layer (`src/tech_coach/application/`)

**Use cases:**
- `send_coaching_message.py` — Full coaching message flow:
  - Context building (goals + burnout risk + semantic session search)
  - LLM call with prompt version tracking
  - JSON schema validation
  - Behavioral signal extraction from LLM suggestions
  - Session window management + summarization trigger
  - Graceful fallback on LLM failure
- `generate_weekly_plan.py` — Plan generation:
  - Deterministic context first (burnout risk, time allocation)
  - LLM task suggestion within constraints
  - Task validation + time budget enforcement
  - Prioritization + cognitive load balancing
  - Rule-based fallback

---

### API Layer (`src/tech_coach/api/`)

- `main.py` — FastAPI app factory with lifespan (startup/shutdown)
- `dependencies.py` — DI: DB session, current user, repositories
- `middleware/trace_middleware.py` — Distributed trace ID injection
- `routers/auth.py` — Google OAuth flow + JWT issuance
- `routers/goals.py` — CRUD + SMART refinement
- `routers/sessions.py` — Session lifecycle + message sending

---

### Evaluation Framework (`evals/`)

- `evaluator.py` — Offline eval runner (CI/CD compatible, exits 0/1)
- `judge.py` — LLM-as-judge with 6 weighted dimensions (1–5 scoring)
- `report.py` — Aggregate scoring + per-dimension analysis
- `rubrics/coaching_rubric.yaml` — Scoring rubric with automatic fail conditions
- `golden_dataset/coaching_scenarios.json` — 5 production scenarios covering:
  - Overcommitment
  - Stagnation
  - High burnout risk
  - Goal setting
  - Safety guardrail (mental health)

---

### Prompts (`prompts/v1/`)

4 versioned YAML prompts:
- `coaching_dialogue.yaml` — Primary coaching dialogue (Gemini Pro, temp=0.3)
- `goal_refinement.yaml` — SMART criteria generation (Gemini Pro, temp=0.2)
- `weekly_plan_generation.yaml` — Task generation (Gemini Flash for cost, temp=0.3)
- `session_summarizer.yaml` — History compression (Gemini Flash, temp=0.1)

---

### Frontend (`frontend/`)

- `app.py` — Streamlit entry point with OAuth callback handling
- `auth.py` — Auth utilities (is_authenticated, require_auth, login_redirect)
- `api_client.py` — HTTP client with all API calls
- `pages/1_goals.py` — Goal management + SMART refinement
- `pages/4_progress.py` — Progress charts (Plotly)
- `pages/5_chat.py` — AI coaching chat interface

---

### Infrastructure (`infra/`, `Dockerfile`, `cloudbuild.yaml`)

- `Dockerfile` — Multi-stage build (builder + runtime), non-root user
- `Dockerfile.frontend` — Streamlit container
- `docker-compose.yml` — Local dev with pgvector, Redis, backend, frontend
- `cloudbuild.yaml` — 8-step CI/CD: lint → test → eval gate → build → push → deploy
- `infra/main.tf` — Terraform: Cloud SQL, Cloud Run, VPC, Secret Manager, IAM

---

### Tests (`tests/`)

- `tests/unit/domain/test_planning_engine.py` — 20+ tests covering:
  - All burnout risk scenarios
  - Time allocation with burnout reduction
  - MIT limit enforcement
  - Task prioritization by priority
  - Progress calculation
  - Stagnation detection
  - Overcommitment detection

---

## Key Design Invariants (Never Violate)

1. **Domain layer has zero infrastructure imports** — planning engine is pure Python
2. **LLM output is never persisted without schema validation**
3. **Progress scores, burnout risk, and status transitions are always deterministic**
4. **All LLM calls log an EvaluationLog record** (cost, latency, tokens, trace_id)
5. **PII never appears in logs** (15 redacted field names)
6. **All repository calls are scoped to user_id** (prevents cross-user data access)
7. **Eval gate must pass before deployment** (CI/CD enforced)

---

## Next Steps (Not Yet Implemented)

### v1 Completion
- [ ] `plans.py` router (generate + task status update endpoints)
- [ ] `reflections.py` router
- [ ] `signals.py` router
- [ ] `session_repository.py` SQLAlchemy implementation (pgvector query)
- [ ] `signal_repository.py` SQLAlchemy implementation
- [ ] `plan_repository.py` SQLAlchemy implementation
- [ ] `user_repository.py` SQLAlchemy implementation
- [ ] `frontend/pages/2_weekly_plan.py`
- [ ] `frontend/pages/3_reflections.py`
- [ ] Alembic migration env.py configuration
- [ ] Integration tests (requires test database)
- [ ] Cost reporting script (`scripts/cost_report.py`)

### v2 Features
- [ ] Row-Level Security (RLS) for multi-user isolation
- [ ] Per-user rate limiting and token quotas
- [ ] Stripe billing integration
- [ ] A/B testing framework for prompts by user cohort
- [ ] Cloud Monitoring dashboards for cost + quality metrics
- [ ] Evaluation pipeline integrated into GitHub Actions
