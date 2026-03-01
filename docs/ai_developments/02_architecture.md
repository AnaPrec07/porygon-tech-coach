# Architecture: Diagram, Explanation & Folder Structure

---

## High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           User (Browser)                                    │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ HTTPS
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Cloud Run: Streamlit Frontend                       │
│  Goals │ Weekly Plan │ Reflections │ Progress Charts │ Chat Interface       │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │ HTTP/REST (internal VPC)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Cloud Run: FastAPI Backend                          │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  API Layer (FastAPI Routers)                                         │  │
│  │  /goals  /plans  /reflections  /sessions  /signals  /eval           │  │
│  └──────────────────────┬───────────────────────────────────────────────┘  │
│                         │                                                   │
│  ┌──────────────────────▼───────────────────────────────────────────────┐  │
│  │  Application Layer (Use Cases)                                       │  │
│  │  CreateGoal │ GenerateWeeklyPlan │ ProcessReflection │ StartSession  │  │
│  └──────────────────────┬───────────────────────────────────────────────┘  │
│                         │                                                   │
│  ┌──────────────────────▼───────────────────────────────────────────────┐  │
│  │  Domain Layer                                                        │  │
│  │  ┌─────────────────────────┐  ┌───────────────────────────────────┐ │  │
│  │  │  Domain Entities        │  │  Planning Engine (Deterministic)  │ │  │
│  │  │  Goal │ Skill │ Project │  │  Prioritize │ Allocate │ Score    │ │  │
│  │  │  WeeklyPlan │ Signal    │  │  BurnoutRisk │ FocusScore        │ │  │
│  │  └─────────────────────────┘  └───────────────────────────────────┘ │  │
│  └──────────────────────┬───────────────────────────────────────────────┘  │
│                         │                                                   │
│  ┌──────────────────────▼───────────────────────────────────────────────┐  │
│  │  Infrastructure Layer                                                │  │
│  │  ┌────────────┐  ┌──────────────┐  ┌─────────────┐  ┌───────────┐  │  │
│  │  │ PostgreSQL │  │  Vertex AI   │  │ Cloud Cache │  │  Logger   │  │  │
│  │  │ Repository │  │  LLM Client  │  │  (Redis)    │  │  Tracer   │  │  │
│  │  │ (SQLAlchemy│  │  Gemini 1.5  │  │             │  │           │  │  │
│  │  │ + pgvector)│  │  Pro/Flash   │  │             │  │           │  │  │
│  │  └────────────┘  └──────────────┘  └─────────────┘  └───────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐   ┌──────────────────┐   ┌─────────────────────┐
│ Cloud SQL   │   │  Vertex AI API   │   │  Cloud Logging      │
│ PostgreSQL  │   │  Gemini Models   │   │  Cloud Trace        │
│ (private IP)│   │  Embeddings API  │   │  Cloud Monitoring   │
└─────────────┘   └──────────────────┘   └─────────────────────┘
                           │
                  ┌────────▼──────────┐
                  │  Secret Manager   │
                  │  (DB creds, OAuth │
                  │   secrets, API    │
                  │   keys)           │
                  └───────────────────┘
```

---

## Detailed Architecture Explanation

### Request Flow: Coaching Session

```
1. User sends message via Streamlit chat interface
2. Streamlit POSTs to FastAPI: POST /api/v1/sessions/{session_id}/messages
3. FastAPI middleware: validate JWT, extract user_id
4. Router delegates to StartCoachingSession use case
5. Use case:
   a. Load user context from GoalRepository, BehavioralSignalRepository
   b. Calculate current burnout_risk and focus_score via PlanningEngine (deterministic)
   c. Retrieve last N session summaries from CoachingSessionRepository
   d. Retrieve semantically relevant past sessions via vector search (pgvector)
   e. Build prompt context (user state + history + behavioral signals)
   f. Call VertexAIClient.generate() with prompt_version="coaching_dialogue:1.0.0"
   g. Validate LLM response against JSON schema
   h. Extract behavioral signals from response (LLM-suggested, deterministic engine validates)
   i. Persist: message, response, evaluation_log, behavioral_signals
   j. Return validated response to API
6. FastAPI returns response to Streamlit
7. Streamlit renders response in chat UI
```

### LLM Call Flow

```
VertexAIClient.generate()
  │
  ├─ Load prompt from PromptRegistry (versioned YAML)
  ├─ Check cache: SHA256(prompt_version + context_hash) → Redis lookup
  │   ├─ Cache hit: return cached response + log cache hit
  │   └─ Cache miss: proceed to Vertex AI
  │
  ├─ Build GenerativeModel request with:
  │   ├─ system_instruction (from prompt YAML)
  │   ├─ generation_config: response_mime_type="application/json",
  │   │                     response_schema=<JSON schema>,
  │   │                     max_output_tokens=<from budget>,
  │   │                     temperature=0.3 (coaching: low temp for consistency)
  │   └─ safety_settings (block harmful content)
  │
  ├─ Execute with retry (exponential backoff: 1s, 2s, 4s, max 3 retries)
  ├─ Timeout: 30s hard limit
  │
  ├─ On success:
  │   ├─ Parse JSON response
  │   ├─ Validate against Pydantic schema
  │   ├─ Write cache entry (if cacheable)
  │   ├─ Log EvaluationLog record to DB
  │   ├─ Emit structured log to Cloud Logging
  │   └─ Return LLMResponse
  │
  └─ On failure (after retries):
      ├─ Log error with full context (no PII)
      ├─ Raise LLMServiceError (caught at use case layer)
      └─ Use case returns degraded response (rule-based fallback)
```

### Planning Engine Data Flow

```
BehavioralSignals (DB)
        │
        ▼
PlanningEngine.calculate_burnout_risk()
        │
        ├─ completion_rate_trend (last 14 days) → trend slope
        ├─ planned_hours vs actual_hours (last 7 days) → overcommitment ratio
        ├─ session_gap_days → isolation signal
        └─ Returns: BurnoutRiskScore(value: float, factors: List[str])

Goals (DB) + BurnoutRiskScore
        │
        ▼
PlanningEngine.allocate_weekly_time(goals, capacity_hours, burnout_risk)
        │
        ├─ Base allocation: weighted by (priority × deadline_proximity)
        ├─ Burnout adjustment: reduce total by burnout_risk × 0.3
        ├─ ADHD constraint: max 3 goals active per week (MIT principle)
        └─ Returns: Dict[goal_id, allocated_hours]

LLM-suggested tasks (validated) + Allocations
        │
        ▼
PlanningEngine.build_weekly_plan()
        │
        ├─ Assign tasks to time slots
        ├─ Balance cognitive load (deep work vs admin)
        └─ Returns: WeeklyPlan domain entity
```

---

## Folder Structure

```
tech_coach/
├── docs/
│   ├── prompt_001.md                    # Original design brief
│   └── ai_developments/                 # Implementation documentation
│       ├── 01_system_design_decisions.md
│       ├── 02_architecture.md
│       ├── 03_data_models.md
│       └── 04_implementation_log.md
│
├── src/
│   └── tech_coach/                      # Main Python package
│       ├── __init__.py
│       ├── config.py                    # Settings via pydantic-settings
│       │
│       ├── domain/                      # Pure domain logic, zero infra imports
│       │   ├── __init__.py
│       │   ├── models/                  # Domain entities (Pydantic BaseModel)
│       │   │   ├── __init__.py
│       │   │   ├── user.py
│       │   │   ├── goal.py
│       │   │   ├── skill.py
│       │   │   ├── project.py
│       │   │   ├── weekly_plan.py
│       │   │   ├── reflection.py
│       │   │   ├── coaching_session.py
│       │   │   └── behavioral_signal.py
│       │   ├── repositories/            # Abstract interfaces (Protocol classes)
│       │   │   ├── __init__.py
│       │   │   ├── goal_repository.py
│       │   │   ├── session_repository.py
│       │   │   ├── signal_repository.py
│       │   │   └── plan_repository.py
│       │   └── services/               # Domain services (pure, deterministic)
│       │       ├── __init__.py
│       │       └── planning_engine.py
│       │
│       ├── application/                 # Use cases (orchestration only)
│       │   ├── __init__.py
│       │   ├── use_cases/
│       │   │   ├── __init__.py
│       │   │   ├── create_goal.py
│       │   │   ├── generate_weekly_plan.py
│       │   │   ├── process_reflection.py
│       │   │   ├── start_coaching_session.py
│       │   │   └── send_coaching_message.py
│       │   └── services/
│       │       ├── __init__.py
│       │       └── coaching_service.py  # Orchestrates use cases
│       │
│       ├── infrastructure/              # All external system integrations
│       │   ├── __init__.py
│       │   ├── db/
│       │   │   ├── __init__.py
│       │   │   ├── base.py             # SQLAlchemy declarative base
│       │   │   ├── session.py          # Async session factory
│       │   │   ├── models/             # SQLAlchemy ORM models
│       │   │   │   ├── __init__.py
│       │   │   │   ├── user.py
│       │   │   │   ├── goal.py
│       │   │   │   ├── skill.py
│       │   │   │   ├── project.py
│       │   │   │   ├── weekly_plan.py
│       │   │   │   ├── reflection.py
│       │   │   │   ├── coaching_session.py
│       │   │   │   ├── behavioral_signal.py
│       │   │   │   ├── evaluation_log.py
│       │   │   │   └── prompt_version.py
│       │   │   └── repositories/       # Concrete implementations
│       │   │       ├── __init__.py
│       │   │       ├── goal_repository.py
│       │   │       ├── session_repository.py
│       │   │       ├── signal_repository.py
│       │   │       └── plan_repository.py
│       │   ├── llm/
│       │   │   ├── __init__.py
│       │   │   ├── vertex_client.py    # Vertex AI integration
│       │   │   ├── prompt_registry.py  # Load/version prompts from YAML
│       │   │   ├── cache.py            # Redis-based response cache
│       │   │   └── schemas/            # JSON schemas for LLM output validation
│       │   │       ├── coaching_response.json
│       │   │       ├── goal_refinement.json
│       │   │       ├── weekly_plan.json
│       │   │       └── reflection_analysis.json
│       │   ├── auth/
│       │   │   ├── __init__.py
│       │   │   ├── google_oauth.py     # OAuth2 flow
│       │   │   └── jwt_handler.py      # JWT creation/validation
│       │   └── observability/
│       │       ├── __init__.py
│       │       ├── logger.py           # Structured JSON logger
│       │       ├── tracer.py           # Cloud Trace integration
│       │       └── cost_estimator.py   # Per-request cost calculation
│       │
│       └── api/                        # FastAPI application
│           ├── __init__.py
│           ├── main.py                 # App factory
│           ├── dependencies.py         # DI: DB session, current user, etc.
│           ├── middleware/
│           │   ├── __init__.py
│           │   ├── auth_middleware.py
│           │   └── trace_middleware.py
│           └── routers/
│               ├── __init__.py
│               ├── auth.py
│               ├── goals.py
│               ├── plans.py
│               ├── reflections.py
│               ├── sessions.py
│               └── signals.py
│
├── frontend/                           # Streamlit application
│   ├── app.py                          # Entry point
│   ├── auth.py                         # OAuth callback handler
│   ├── api_client.py                   # HTTP client to FastAPI
│   └── pages/
│       ├── 1_goals.py
│       ├── 2_weekly_plan.py
│       ├── 3_reflections.py
│       ├── 4_progress.py
│       └── 5_chat.py
│
├── prompts/                            # Versioned prompt templates
│   ├── v1/
│   │   ├── coaching_dialogue.yaml
│   │   ├── goal_refinement.yaml
│   │   ├── reflection_analysis.yaml
│   │   └── weekly_plan_generation.yaml
│   └── registry.py
│
├── evals/                              # Evaluation framework
│   ├── golden_dataset/
│   │   ├── coaching_scenarios.json
│   │   ├── goal_refinement_cases.json
│   │   └── reflection_cases.json
│   ├── rubrics/
│   │   ├── coaching_rubric.yaml
│   │   └── guardrail_rubric.yaml
│   ├── evaluator.py                    # Offline eval runner
│   ├── judge.py                        # LLM-as-judge implementation
│   └── report.py                       # Eval report generator
│
├── migrations/                         # Alembic migrations
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
│
├── infra/                              # Terraform IaC
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── modules/
│   │   ├── cloud_run/
│   │   ├── cloud_sql/
│   │   └── secret_manager/
│   └── environments/
│       ├── dev.tfvars
│       └── prod.tfvars
│
├── scripts/
│   ├── eval_run.py                     # CI eval runner
│   ├── seed_golden_dataset.py
│   └── cost_report.py
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── domain/
│   │   │   ├── test_planning_engine.py
│   │   │   └── test_goal_model.py
│   │   └── infrastructure/
│   │       ├── test_vertex_client.py
│   │       └── test_cost_estimator.py
│   ├── integration/
│   │   ├── test_goal_repository.py
│   │   └── test_coaching_session.py
│   └── e2e/
│       └── test_coaching_flow.py
│
├── Dockerfile
├── Dockerfile.frontend
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
├── cloudbuild.yaml
└── .env.example
```
