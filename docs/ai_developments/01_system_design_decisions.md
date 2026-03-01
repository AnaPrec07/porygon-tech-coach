# System Design Decisions & Tradeoffs

## Document Purpose

This document captures the architectural decisions, tradeoffs, and rationale for the
Professional AI Coach platform. It is the authoritative design reference and must be
updated when decisions change.

---

## 1. Framework Selection: Direct Vertex AI vs Google ADK

### Decision: Direct Vertex AI SDK

**Rationale:**

Google Agent Development Kit (ADK) is designed for multi-agent orchestration and provides
higher-level abstractions for tool calling, agent pipelines, and session management. However,
for this platform, direct Vertex AI usage is more appropriate because:

| Dimension | Direct Vertex AI | Google ADK |
|---|---|---|
| Control over LLM calls | Full | Abstracted away |
| JSON schema enforcement | Native via `response_schema` | Indirect |
| Observability integration | Direct, granular | Framework-managed |
| Token budgeting control | Per-call | Session-level |
| Debugging complexity | Low | Medium-high |
| Prompt versioning | Manual (our system) | ADK-managed |
| Maturity / stability | GA | Preview |
| Vendor lock-in | Moderate | High |

ADK would become appropriate when:
- We need multi-agent coordination (Research + Planning + Coaching agents that hand off tasks)
- We have >3 tools that need to be dynamically selected by the model
- We scale to multi-user with concurrent sessions requiring managed state

For v1 with a single user and deterministic planning engine, ADK adds complexity without
commensurate benefit.

---

## 2. Database: PostgreSQL vs Document DB

### Decision: PostgreSQL with pgvector extension

**Why relational:**

The coaching domain has clear, structured relationships:
- Users own Goals → Goals decompose into WeeklyPlans → Plans contain Tasks
- CoachingSessions reference Goals and produce BehavioralSignals
- EvaluationLogs reference PromptVersions

These are not document-shaped. They are relational. Querying "give me all active goals
with completion rate < 40% for user X" is a JOIN + aggregate — SQL is the right tool.

**Document DB problems for this domain:**
- Referential integrity is application-enforced (unreliable for audit purposes)
- Aggregation pipelines for behavioral analytics are verbose and slow
- Schema evolution is harder to audit (no migrations, no ALTER TABLE)
- ACID transactions matter: updating a goal + creating a behavioral signal must be atomic

**pgvector for semantic memory:**

Included in v1 because:
- Coaching sessions accumulate fast → semantic retrieval over session history is necessary
  within 2-3 months of use
- Avoids a separate vector DB service (Pinecone, Weaviate) — one PostgreSQL instance handles both
- Justification threshold: once there are >50 sessions, keyword search degrades; semantic
  search over embeddings produces dramatically better context injection for LLM prompts

**Multi-user evolution:**

- Add `user_id` FK and Row-Level Security (RLS) policies in PostgreSQL
- Connection pooling via PgBouncer (Cloud SQL Proxy handles this)
- Read replicas for analytics queries
- Partition large tables (coaching_sessions, evaluation_logs) by user_id + created_at

---

## 3. Frontend: Streamlit vs FastAPI Templates vs React

### Decision: Streamlit (v1)

**Tradeoff analysis:**

| Criterion | Streamlit | FastAPI + Jinja2 | React |
|---|---|---|---|
| Dev velocity | Fast | Medium | Slow |
| Interactivity | Medium | Low | High |
| Data visualization | Excellent (native) | Manual | Via libraries |
| Separation from API | No (runs in same process or separate) | Yes | Yes |
| Multi-user scalability | Limited (session state per user) | Full | Full |
| Production readiness | Medium | High | High |
| Auth integration | Manual | Manual | Manual |

Streamlit is chosen for v1 because:
- Single user: Streamlit's session-state model is sufficient
- Native chart components for progress visualization
- Rapid iteration on UX without a frontend build system
- Can run as a separate service pointing to the FastAPI backend

**Migration path to v2:**
- Streamlit → React/Next.js when multi-user requires proper session isolation and
  more complex UX flows
- The FastAPI backend is completely frontend-agnostic; migration does not require backend changes

---

## 4. What Is Deterministic vs LLM-Assisted

This is a critical architectural boundary. LLM non-determinism must never contaminate
core planning logic.

### Strictly Deterministic (never LLM)

| Function | Why Deterministic |
|---|---|
| Burnout risk score calculation | Must be auditable and explainable |
| Weekly time allocation algorithm | User must understand and trust it |
| Task prioritization (urgency × importance matrix) | Core planning integrity |
| Progress score calculation | Metrics must not drift with model updates |
| Goal status transitions | State machine — must be predictable |
| Session authentication and authorization | Security-critical |
| Cost estimation per request | Financial accountability |

### LLM-Assisted (validated before persistence)

| Function | LLM Role | Validation |
|---|---|---|
| Goal refinement into SMART criteria | Suggest → user approves | JSON schema |
| Weekly plan text generation | Draft → deterministic engine finalizes | Schema + planner validates |
| Reflection analysis | Pattern detection → signal extraction | Schema + human review |
| Resource/project suggestions | Brainstorm → user curates | Schema validation |
| Coaching dialogue | Full LLM → bounded by system prompt | Guardrail evaluation |

### Must Never Depend Purely on LLM

- **Goal completion status**: always set by deterministic rules or user action
- **Burnout risk**: heuristic calculation; LLM may interpret but never set the score
- **Data persistence decisions**: LLM outputs are staged → validated → persisted
- **Authentication decisions**: zero LLM involvement

---

## 5. Prompt Versioning Strategy

### Decision: YAML-based versioned prompt registry with DB-tracked usage

**Structure:**
```
prompts/
├── v1/
│   ├── coaching_dialogue.yaml
│   ├── goal_refinement.yaml
│   ├── reflection_analysis.yaml
│   └── weekly_plan_generation.yaml
└── registry.py
```

Each prompt file contains:
```yaml
version: "1.0.0"
model: "gemini-1.5-pro-002"
description: "System prompt for coaching dialogue sessions"
system_prompt: |
  ...
few_shot_examples: [...]
response_schema: {...}
token_budget:
  input_max: 8000
  output_max: 2048
```

**Versioning rules:**
- Semantic versioning: `MAJOR.MINOR.PATCH`
- MAJOR: changes that break eval rubric (prompt intent changes)
- MINOR: additive changes (new examples, clarifications)
- PATCH: wording fixes that do not affect outputs

**Database tracking:**
- Every LLM call logs `prompt_version` in `evaluation_logs`
- Before a new version is promoted to production, the offline eval suite must pass
- Eval regression gate: new version must score ≥ current version on golden dataset

---

## 6. Cost Control Architecture

### Token Budgeting

- Hard limit per request type (defined in prompt YAML)
- `coaching_dialogue`: 8k input / 2k output
- `goal_refinement`: 2k input / 1k output
- `weekly_plan_generation`: 4k input / 2k output

### Conversation Window Management

- Active window: last 10 turns (approximately 3k tokens at average turn length)
- Window overflow triggers: historical summarization (separate low-cost LLM call)
- Summary stored in `coaching_sessions.summary_text` and injected as compressed context

### Caching Strategy

- Identical prompts (same hash) within a 24h window return cached response
- Cache stored in Redis (Cloud Memorystore) keyed by SHA256(prompt_version + messages_hash)
- TTL: 24h for coaching responses, 7d for resource suggestions
- Never cache: personalized behavioral analysis, real-time reflection parsing

### Cost Estimation

```
Gemini 1.5 Pro: $0.00125/1k input tokens, $0.005/1k output tokens
Per coaching session (~20 turns):
  Input: ~15k tokens → $0.019
  Output: ~5k tokens → $0.025
  Total: ~$0.044/session
```

All cost estimates logged per request for monthly budget tracking.

---

## 7. Security Design

### Authentication

- Google OAuth 2.0 (not username/password)
- JWT session tokens with 8h expiry, refresh token rotation
- `user_id` propagated through entire request chain (never derived from request body)
- Single-user v1: hardcoded allowed email in Secret Manager (not in code)

### PII-Aware Logging

- User goal text, reflection content → never logged to Cloud Logging
- Logged: user_id (UUID, not email), session_id, trace_id, token counts, scores
- Log levels enforced: DEBUG stripped in production builds

### Secrets Management

- All secrets in Google Secret Manager (never in env files or code)
- Secret access via Workload Identity (no service account keys on disk)
- Secret rotation: database credentials rotated every 90 days

### Input Validation

- All API inputs validated via Pydantic schemas before processing
- LLM outputs parsed through JSON schema validator before any persistence
- SQL: ORM only (no raw queries except for analytics), parameterized always

---

## 8. Evaluation Framework Design

### Offline Evaluation Pipeline

```
Golden Dataset → Prompt v_new → LLM → Responses → LLM-as-Judge → Scores
                                                 ↓
                                         Compare vs v_current baseline
                                                 ↓
                              PASS (score ≥ baseline) → promote to staging
                              FAIL → block promotion, create issue
```

### LLM-as-Judge Rubric (Coaching Dialogue)

Dimensions scored 1-5:
- **Specificity**: advice is concrete, not generic
- **SMART alignment**: goal suggestions meet SMART criteria
- **ADHD-awareness**: structure appropriate for attention challenges
- **Tone calibration**: motivating without being toxic-positive
- **Hallucination absence**: advice is grounded, no fabricated resources
- **Safety**: no harmful advice (medical, legal, financial)

### Guardrail Evaluation

Separate from quality evaluation:
- Harmful advice classifier (fine-tuned on coaching domain)
- PII leakage detector in responses
- Tone toxicity check (no shame, no pressure language)

### CI/CD Integration

```yaml
# cloudbuild.yaml step
- name: 'python:3.11'
  entrypoint: 'python'
  args: ['scripts/eval_run.py', '--prompt-version', '$SHORT_SHA']
  env:
    - 'EVAL_THRESHOLD=0.85'
    - 'BASELINE_VERSION=latest_production'
```

Eval gate blocks deployment if score < 0.85 on golden dataset.

---

## 9. Clean Architecture Layer Responsibilities

```
┌─────────────────────────────────────────────────────┐
│                    API Layer                        │
│  FastAPI routers, request/response schemas, auth    │
│  middleware. No business logic. No DB access.       │
├─────────────────────────────────────────────────────┤
│                Application Layer                    │
│  Use cases, orchestration. Calls domain services    │
│  and infrastructure via interfaces. No framework    │
│  dependencies.                                      │
├─────────────────────────────────────────────────────┤
│                  Domain Layer                       │
│  Entities, value objects, domain services.          │
│  Pure Python. Zero infrastructure imports.          │
│  Planning engine lives here.                        │
├─────────────────────────────────────────────────────┤
│               Infrastructure Layer                  │
│  SQLAlchemy, Vertex AI client, Redis cache,         │
│  Google Cloud Logging, Secret Manager.              │
│  Implements domain repository interfaces.           │
└─────────────────────────────────────────────────────┘
```

**Dependency rule:** Inner layers know nothing about outer layers.
The domain layer has zero imports from infrastructure or application.

---

## 10. Multi-User Evolution Plan

### What changes when adding multi-tenancy:

| Component | v1 (single-user) | v2 (multi-user) |
|---|---|---|
| Auth | Hardcoded allowed email | Full OAuth, user table |
| DB access | Single schema | RLS + user_id partitioning |
| Rate limiting | None | Per-user token quotas |
| Billing | N/A | Stripe integration, per-user cost tracking |
| Session isolation | OS process isolation | Proper request-scoped auth context |
| LLM cache | Global | Per-user cache namespace |
| Eval A/B testing | Not applicable | Traffic split by user cohort |

### Database RLS migration:

```sql
-- Add to all tables
ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
CREATE POLICY goals_isolation ON goals
  USING (user_id = current_setting('app.current_user_id')::uuid);
```

### What does NOT change:

- Domain layer (pure Python entities and services)
- LLM integration layer (already accepts user_id in context)
- Planning engine (stateless, user context passed in)
- Evaluation framework (eval by prompt version, not by user)
- Infrastructure abstractions (repository interfaces)

The v1 design explicitly avoids any global state that would prevent multi-tenancy.
