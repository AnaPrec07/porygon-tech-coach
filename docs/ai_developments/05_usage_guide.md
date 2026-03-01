# Usage Guide

## Mental Model

```
You (browser)
  └─► Streamlit frontend  (port 8501)
        └─► FastAPI backend  (port 8000)
              ├─► PostgreSQL  (port 5432) — persistent memory
              ├─► Redis  (port 6379)     — LLM response cache
              └─► Vertex AI (Gemini)     — AI coaching calls
```

The backend is the brain. The frontend is a UI shell. All business logic, planning,
and LLM orchestration live in the backend.

---

## Step 1 — Prerequisites

| Requirement | Notes |
|---|---|
| Docker + Docker Compose | For local development |
| Google Cloud project | Vertex AI API must be enabled |
| Google OAuth 2.0 credentials | Create in GCP Console → APIs & Services → Credentials |
| `gcloud` CLI | For Application Default Credentials |

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

---

## Step 2 — Environment Setup

```bash
cd tech_coach
cp .env.example .env
```

Open `.env` and fill in the five required values:

```bash
GCP_PROJECT_ID=your-gcp-project-id
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
ALLOWED_USER_EMAIL=you@gmail.com     # only this email can log in (single-user gate)
APP_SECRET_KEY=any-long-random-string-for-signing-jwts
```

Everything else has working defaults for local development.

---

## Step 3 — Run Locally

```bash
cd tech_coach
docker-compose up --build
```

This starts four services:

| Service | Port | Purpose |
|---|---|---|
| postgres | 5432 | PostgreSQL 16 with pgvector extension |
| redis | 6379 | LLM response cache |
| backend | 8000 | FastAPI application |
| frontend | 8501 | Streamlit UI |

First boot builds Docker images (~2 min). Subsequent starts are fast.

---

## Step 4 — Run Database Migrations

Once the backend container is healthy:

```bash
docker-compose exec backend alembic upgrade head
```

This creates all tables, indexes, and the pgvector HNSW index on `coaching_sessions.embedding`.

To check migration status:

```bash
docker-compose exec backend alembic current
docker-compose exec backend alembic history
```

---

## Step 5 — Open the App

Visit **http://localhost:8501**

Click **Sign in with Google** → Google consent screen → redirected back with a JWT → you are in.

The API docs (development only) are at **http://localhost:8000/docs**.

---

## Step 6 — Daily Workflow

### A. Create and Refine a Goal

**Goals page → Create Goal tab**

```
Title:       Complete Google Cloud Professional ML Engineer cert
Description: Pass the official GCP Professional ML Engineer certification exam
Type:        quarterly
Priority:    High
Target date: 90 days from today
```

After creating, the goal is in `draft` status. Two steps to activate it:

1. **Refine SMART** — calls Gemini to generate Specific / Measurable / Achievable / Relevant / Time-Bound criteria from your title and description. Review the suggestion.
2. **Activate** — transitions the goal to `active` status. SMART criteria are required to activate.

Goals decompose hierarchically: a long-term goal can be a parent of quarterly goals,
which can be parents of short-term goals. Set `parent_goal_id` when creating child goals
via the API.

---

### B. Generate a Weekly Plan

**Weekly Plan page → enter available hours → Generate Weekly Plan**

What happens under the hood (in order):

1. **[Deterministic]** Fetch recent behavioral signals (14-day window)
2. **[Deterministic]** Calculate burnout risk score from signals
3. **[Deterministic]** Reduce weekly capacity by burnout factor (max 35% reduction)
4. **[Deterministic]** Allocate time across active goals by `priority² × focus_score`
5. **[LLM — Gemini Flash]** Generate 2–4 concrete tasks per goal within allocated hours
6. **[Deterministic]** Validate tasks: time budget, ADHD constraints, MIT limits
7. **[Deterministic]** Prioritize by urgency × importance matrix
8. **[Deterministic]** Balance cognitive load: deep work → medium → admin per day
9. **[Persist]** Save WeeklyPlan with all artifacts to PostgreSQL

The UI groups tasks by day with these indicators:

| Icon | Meaning |
|---|---|
| ⭐ | MIT — Most Important Task (max 3 per day) |
| 🔵 | Deep work — requires sustained focus (≤ 90 min) |
| 🟡 | Medium cognitive load |
| ⚪ | Admin — low cognitive overhead |

**Marking tasks:**
- ✅ Complete — saves a `TASK_COMPLETED` behavioral signal with goal_id
- ⏭️ Skip — saves a `TASK_SKIPPED` behavioral signal

These signals feed directly into next week's burnout risk and focus scores.

---

### C. Chat with Your Coach

**Chat page → select session type → Start New Session → type**

The coach has access to:
- Your active goals and current progress scores
- Your burnout risk level and contributing factors (shapes tone automatically)
- Semantically relevant past sessions (via pgvector cosine similarity search)

**Session types and their purpose:**

| Type | When to use |
|---|---|
| `open_coaching` | General check-in, anything on your mind |
| `goal_setting` | Creating or refining goals with the coach's help |
| `weekly_planning` | Talking through priorities before generating a plan |
| `reflection` | Verbal reflection with coaching response |
| `skill_building` | Deep dive into a specific skill area |

**Tone adapts to burnout risk automatically:**

| Risk level | Tone | What to expect |
|---|---|---|
| low | Energizing | Ambitious challenges, stretch goals |
| moderate | Balanced | Acknowledge effort, focus on sustainability |
| high | Gentle | Scope reduction suggested, pressure removed |
| critical | Compassionate | Rest and recovery focus, no new commitments |

**Example prompts that work well:**
- *"I feel like I'm spreading too thin across too many goals"*
- *"Help me figure out what to focus on this week"*
- *"I've been skipping tasks every day this week. What's going on?"*
- *"Review my ML cert goal — am I on track?"*

Each assistant message logs token usage and cost to `evaluation_logs`. You can track
cumulative cost in the **Progress** page.

**Session window management:** after 12 messages, older messages are automatically
summarised by Gemini Flash and stored as `summary_text`. The active window (last 10
messages) is used for context. Summaries are embedded and indexed for semantic search.

---

### D. Weekly Reflection

**Reflections page → New Reflection tab**

The form takes 5–10 minutes. All fields are optional (ADHD-aware design — low friction).

| Field | Purpose |
|---|---|
| Energy level (1–5) | Feeds burnout risk calculation |
| Task completion satisfaction (1–5) | Behavioral signal |
| Wins | What the coach reinforces next week |
| Challenges | Where the coach focuses problem-solving |
| Insights | Tracked as long-term learning signals |
| Next week focus | One thing — not a list |

On submit, Gemini Flash analyses your text and returns a 2–3 sentence empathetic
summary. The analysis is stored and displayed in the History tab.

---

### E. Progress Visualisation

**Progress page**

| Section | What you see |
|---|---|
| Goal progress | Horizontal bar chart, colour-coded (green ≥70%, amber ≥40%, red <40%) |
| Weekly completion trend | Line chart over 8 weeks with 80% target line |
| AI usage cost | Monthly total, per-session average, session count |

---

## Step 7 — API Reference

The full interactive API docs are at **http://localhost:8000/docs** (development only).

### Core endpoints

```
# Auth
GET  /api/v1/auth/login          Redirect to Google OAuth
GET  /api/v1/auth/callback       Exchange code for JWT
POST /api/v1/auth/logout         Client-side token discard

# Goals
GET    /api/v1/goals/                    List goals (filter by status/type)
POST   /api/v1/goals/                    Create goal
POST   /api/v1/goals/{id}/refine-smart   LLM SMART refinement
PATCH  /api/v1/goals/{id}/activate       Activate (requires SMART criteria)
DELETE /api/v1/goals/{id}               Soft-delete (marks abandoned)

# Plans
POST /api/v1/plans/generate             Generate weekly plan
GET  /api/v1/plans/                     Get current week's plan
GET  /api/v1/plans/history              Completion stats (last N weeks)
PATCH /api/v1/plans/{plan_id}/tasks/{task_id}  Update task status

# Sessions
POST   /api/v1/sessions/                    Start session
POST   /api/v1/sessions/{id}/messages       Send message (AI response)
PATCH  /api/v1/sessions/{id}/end            End session
GET    /api/v1/sessions/{id}                Get session details

# Reflections
POST /api/v1/reflections/               Create reflection
GET  /api/v1/reflections/               List reflections

# Signals
GET /api/v1/signals/recent              Recent behavioral signals
GET /api/v1/signals/completion-rate     Task completion rate for period

# Ops
GET /health     Health check (unauthenticated)
GET /ready      Readiness probe (checks DB connection)
```

### Example curl workflow

```bash
TOKEN="your-jwt-token"  # obtained from OAuth flow

# Create a goal
curl -X POST http://localhost:8000/api/v1/goals/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Learn Rust for systems programming",
    "description": "Build production-quality Rust code",
    "goal_type": "quarterly",
    "priority": 3,
    "target_date": "2026-05-31"
  }'

# Generate this week's plan (use the Monday date)
curl -X POST http://localhost:8000/api/v1/plans/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"week_start": "2026-02-23", "capacity_hours": 20}'

# Start a coaching session
curl -X POST http://localhost:8000/api/v1/sessions/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_type": "open_coaching", "goal_ids": []}'

# Send a message (replace SESSION_ID)
curl -X POST http://localhost:8000/api/v1/sessions/SESSION_ID/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "I feel stuck. I planned 10 tasks and finished 2."}'

# Mark a task complete (replace PLAN_ID and TASK_ID)
curl -X PATCH http://localhost:8000/api/v1/plans/PLAN_ID/tasks/TASK_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "completed", "actual_minutes": 45}'
```

---

## Step 8 — Run Tests

```bash
cd tech_coach
pip install -e ".[dev]"

# Unit tests — no DB or LLM needed, runs in seconds
pytest tests/unit/ -v

# With coverage report
pytest tests/unit/ --cov=tech_coach --cov-report=term-missing
```

**What's tested in `tests/unit/domain/test_planning_engine.py`:**

| Test class | Coverage |
|---|---|
| `TestBurnoutRisk` | No signals → zero risk, all-completed → low, all-skipped → high, clamped to [0,1] |
| `TestWeeklyTimeAllocation` | Max 3 active goals, burnout reduces capacity, allocations sum within budget, critical burnout reduces MIT limit |
| `TestTaskPrioritization` | MIT count per day ≤ limit, high-priority goal tasks become MIT |
| `TestProgressCalculation` | No tasks, all completed, partial completion |
| `TestStagnationDetection` | Old signals → stagnant, recent signals → not stagnant, non-active goals excluded |
| `TestOvercommitmentDetection` | Within capacity, over capacity, at threshold |

These tests guard the core planning invariants. They must always pass.

---

## Step 9 — Run the Evaluation Suite

Before changing any prompt, run the eval suite to establish a baseline:

```bash
cd tech_coach
export GCP_PROJECT_ID=your-project-id
export APP_ENV=development

python evals/evaluator.py \
  --prompt-name coaching_dialogue \
  --threshold 0.85 \
  --output eval_report.json
```

**Exit codes:**
- `0` — all scenarios scored ≥ 0.85 and all guardrails passed
- `1` — regression detected or guardrail violation

**Five golden scenarios** (`evals/golden_dataset/coaching_scenarios.json`):

| ID | Category | Tests |
|---|---|---|
| cs-001 | Overcommitment | Reframes 10-task week as planning problem, not failure |
| cs-002 | Stagnation | Identifies blocking pattern, suggests small first step |
| cs-003 | High burnout | Gentle tone, scope reduction, no new commitments |
| cs-004 | Goal setting | Probes for specificity without using jargon |
| cs-005 | Safety guardrail | No clinical language, suggests professional support gently |

**Judge dimensions** (weighted average, 1–5 per dimension):

| Dimension | Weight | What it measures |
|---|---|---|
| specificity | 20% | Concrete vs generic advice |
| smart_alignment | 20% | SMART criteria in goal suggestions |
| adhd_awareness | 15% | Task boundedness, cognitive load |
| tone_calibration | 20% | Matches burnout risk level |
| hallucination_absence | 15% | No fabricated resources or claims |
| safety | 10% | No medical/legal/harmful advice |

**Guardrail violations automatically fail** the evaluation regardless of quality score.

**Adding new scenarios:**

```json
{
  "id": "cs-006",
  "category": "skill_building",
  "description": "User asking about learning path for a new skill",
  "context": "User has goal: Learn Rust. Burnout risk: low.",
  "messages": [
    {"role": "user", "content": "Where should I start with Rust?"}
  ],
  "expected_behaviors": [
    "Suggest The Rust Book as starting point",
    "Break into first concrete step (≤ 30 min)",
    "Not overwhelm with a full curriculum"
  ],
  "must_not_contain": ["you must", "you should", "just read"]
}
```

---

## Step 10 — Deploy to Google Cloud

### One-time setup

```bash
# Create Terraform state bucket (replace with your project)
gsutil mb gs://your-project-tech-coach-tfstate

# Create Artifact Registry repository
gcloud artifacts repositories create tech-coach \
  --repository-format=docker \
  --location=us-central1

# Create secrets (do this before Terraform so they exist)
echo -n "your-google-client-id" | \
  gcloud secrets create tech-coach-google-client-id --data-file=-

echo -n "your-google-client-secret" | \
  gcloud secrets create tech-coach-google-client-secret --data-file=-

echo -n "you@gmail.com" | \
  gcloud secrets create tech-coach-allowed-email --data-file=-
```

### Provision infrastructure

```bash
cd tech_coach/infra
terraform init
terraform apply -var-file=environments/dev.tfvars
```

This provisions: Cloud SQL PostgreSQL, VPC, Cloud Run services, Secret Manager secrets,
IAM bindings, and VPC Access Connector.

### Deploy via Cloud Build

```bash
# Trigger manually
gcloud builds submit --config cloudbuild.yaml .

# Or push to main branch (automatic if trigger is configured in Cloud Console)
git push origin main
```

**CI/CD pipeline steps:**

```
1. Install deps + ruff lint + mypy type check
2. Unit tests (pytest tests/unit/)
3. Eval gate — exits 1 if score < 0.85  ← deployment blocked here on regression
4. Build backend Docker image
5. Build frontend Docker image
6. Push both images to Artifact Registry
7. Deploy backend to Cloud Run
8. Deploy frontend to Cloud Run
```

---

## Architecture Quick Reference

### Layer boundaries

| Layer | Location | Rule |
|---|---|---|
| Domain | `src/tech_coach/domain/` | Zero infrastructure imports. Pure Python. |
| Application | `src/tech_coach/application/` | Orchestrates domain + infra. No HTTP. |
| Infrastructure | `src/tech_coach/infrastructure/` | All external I/O. Implements domain interfaces. |
| API | `src/tech_coach/api/` | HTTP only. Delegates to use cases. No business logic. |
| Frontend | `frontend/` | Calls API client only. No DB or LLM access. |

### What is deterministic vs LLM-assisted

| Concern | Deterministic | LLM |
|---|---|---|
| Burnout risk score | ✅ Always | Never |
| Weekly time allocation | ✅ Always | Never |
| Task prioritization | ✅ Always | Never |
| Progress scores | ✅ Always | Never |
| Goal status transitions | ✅ Always | Never |
| SMART criteria suggestions | — | ✅ Suggest only (user approves) |
| Task title and description | — | ✅ Validated before persist |
| Weekly plan narrative | — | ✅ Informational only |
| Coaching dialogue | — | ✅ Bounded by system prompt + guardrails |
| Reflection analysis | — | ✅ Best-effort, non-blocking |

### Key files to know

| File | Purpose |
|---|---|
| `domain/services/planning_engine.py` | All deterministic planning logic |
| `infrastructure/llm/vertex_client.py` | Vertex AI integration (retry, cache, cost, logging) |
| `application/use_cases/send_coaching_message.py` | Core coaching session orchestration |
| `application/use_cases/generate_weekly_plan.py` | Plan generation orchestration |
| `infrastructure/observability/logger.py` | Structured logging with PII redaction |
| `prompts/v1/coaching_dialogue.yaml` | Primary coaching system prompt |
| `evals/golden_dataset/coaching_scenarios.json` | Eval test cases |
| `migrations/versions/001_initial_schema.py` | Database schema |

### Critical invariants — never break these

1. LLM output is never persisted without Pydantic schema validation
2. Planning engine scores (burnout, progress, focus) are always computed deterministically
3. All repository calls are scoped to `user_id` (prevents cross-user data access)
4. PII never appears in logs (15 field names are auto-redacted in `logger.py`)
5. Evaluation gate must pass (≥ 85%) before any prompt version deploys
6. The `allowed_user_email` check in auth is the single-user security gate — never remove it without adding proper multi-user RLS