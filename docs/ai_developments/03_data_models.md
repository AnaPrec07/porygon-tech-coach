# Data Model Schemas

## Entity Relationship Summary

```
User (1) ──────────────────────────────────────────────────────────── (∞)
  │                                                                     │
  ├── Goal (∞) ──────────────────────── parent_goal_id ──── Goal (self)
  │     │                                    (nullable)
  │     └── BehavioralSignal (∞) [goal_id FK]
  │
  ├── CoachingSession (∞)
  │     │
  │     └── EvaluationLog (∞) [session_id FK]
  │
  ├── WeeklyPlan (∞) ── contains ── Task[] (embedded JSONB or sub-table)
  │
  ├── Reflection (∞) [week_start, plan_id FK]
  │
  ├── Skill (∞)
  │
  ├── Project (∞) ─── references Goal[] and Skill[]
  │
  └── BehavioralSignal (∞) [various FK]

PromptVersion (∞) ──────────── EvaluationLog (∞) [prompt_version_id FK]
```

---

## Schema Definitions

### User

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| email | VARCHAR(254) | Unique, indexed |
| display_name | VARCHAR(200) | |
| google_sub | VARCHAR(255) | Unique, indexed (Google OAuth subject) |
| is_active | BOOLEAN | Soft disable |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Normalization**: User PII stored once. All other tables reference `user_id` UUID only.
**Multi-user evolution**: Add `tenant_id` FK + RLS policies.

---

### Goal

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | → users.id, CASCADE |
| title | VARCHAR(200) | |
| description | TEXT | |
| goal_type | VARCHAR(20) | ENUM: short_term, quarterly, long_term |
| status | VARCHAR(20) | ENUM: draft, active, paused, completed, abandoned |
| priority | INTEGER | 1=Low, 2=Medium, 3=High, 4=Critical |
| target_date | DATE | |
| smart_criteria | JSONB | Nullable. Set after LLM refinement + user approval |
| progress_score | FLOAT | [0.0, 1.0]. Deterministic only. |
| parent_goal_id | UUID FK | → goals.id (nullable). Decomposition hierarchy. |
| skill_ids | JSONB | Array of skill UUIDs |
| version | INTEGER | Incremented on significant modification |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Indexes**:
- `(user_id, status)` — primary filter
- `(user_id, goal_type, status)` — type-filtered queries
- `(parent_goal_id)` — hierarchy traversal
- `(target_date)` — deadline queries

**Versioning strategy**: When a goal's status changes or SMART criteria are rewritten,
increment `version`. For full audit trail, a `goal_history` table can be added with
trigger-based snapshots (v2 feature).

---

### CoachingSession

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| session_type | VARCHAR(30) | ENUM: open_coaching, goal_setting, weekly_planning, etc. |
| status | VARCHAR(20) | active, completed, abandoned |
| goal_ids | JSONB | Array of goal UUIDs discussed |
| messages | JSONB | Full message history [{role, content, ...}] |
| summary_text | TEXT | Compressed context summary (LLM-generated) |
| embedding | VECTOR(768) | pgvector. For semantic retrieval. |
| total_tokens_used | INTEGER | |
| total_cost_usd | FLOAT | |
| metadata | JSONB | Flexible per-session metadata |
| started_at | TIMESTAMPTZ | |
| ended_at | TIMESTAMPTZ | Nullable (active sessions) |

**pgvector HNSW index** on `embedding` for cosine similarity search:
```sql
CREATE INDEX ix_sessions_embedding_hnsw ON coaching_sessions
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

**Messages embedded in JSONB** (not a separate table) because:
- Sessions are read whole (no partial message fetch needed)
- Average session: 10–20 messages ≈ 5–10 KB — well within JSONB limits
- Simplifies queries (no JOIN overhead)
- JSONB supports indexed access if needed

---

### BehavioralSignal

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| signal_type | VARCHAR(50) | ENUM of 15 signal types |
| goal_id | UUID FK | Nullable |
| session_id | UUID FK | Nullable |
| plan_id | UUID FK | Nullable |
| intensity | FLOAT | [0.0, 1.0] |
| metadata | JSONB | Signal-specific context |
| recorded_at | TIMESTAMPTZ | When the event occurred |
| created_at | TIMESTAMPTZ | When persisted |

**Append-only**: signals are never updated or deleted.
**Indexes**:
- `(user_id, recorded_at)` — primary time-series query
- `(user_id, signal_type)` — signal-type filtering

---

### EvaluationLog

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK | |
| session_id | UUID FK | Nullable |
| prompt_version_id | UUID FK | Nullable |
| trace_id | VARCHAR(128) | Cloud Trace correlation |
| prompt_name | VARCHAR(100) | e.g., "coaching_dialogue" |
| prompt_version | VARCHAR(20) | e.g., "1.0.0" |
| model_id | VARCHAR(100) | e.g., "gemini-1.5-pro-002" |
| input_tokens | INTEGER | |
| output_tokens | INTEGER | |
| total_tokens | INTEGER | |
| latency_ms | INTEGER | |
| estimated_cost_usd | FLOAT | |
| eval_score | FLOAT | Nullable (online evals only) |
| cache_hit | BOOLEAN | |
| error_type | VARCHAR(100) | Nullable |
| retry_count | INTEGER | |
| input_hash | VARCHAR(64) | SHA256 of input (no PII) |
| metadata | JSONB | |

**Analytics query examples**:
```sql
-- Monthly cost by prompt name
SELECT prompt_name, SUM(estimated_cost_usd) as monthly_cost
FROM evaluation_logs
WHERE created_at >= DATE_TRUNC('month', NOW())
GROUP BY prompt_name;

-- Avg latency per prompt version
SELECT prompt_version, AVG(latency_ms) as avg_latency_ms
FROM evaluation_logs
GROUP BY prompt_version ORDER BY prompt_version;

-- Error rate by model
SELECT model_id,
       COUNT(*) FILTER (WHERE error_type IS NOT NULL) as errors,
       COUNT(*) as total
FROM evaluation_logs GROUP BY model_id;
```

---

### PromptVersion

| Field | Type | Notes |
|---|---|---|
| id | UUID PK | |
| prompt_name | VARCHAR(100) | |
| version | VARCHAR(20) | Semantic version |
| model_id | VARCHAR(100) | |
| description | TEXT | |
| system_prompt_hash | VARCHAR(64) | SHA256 for change detection |
| eval_score | FLOAT | Nullable |
| eval_passed | BOOLEAN | Nullable |
| is_production | BOOLEAN | Only one per prompt_name at a time |
| promoted_at | TIMESTAMPTZ | Nullable |
| deprecated_at | TIMESTAMPTZ | Nullable |

**Unique constraint**: `(prompt_name, version)`
**Business rule**: at most one `is_production=TRUE` per `prompt_name` (enforced in application layer).
