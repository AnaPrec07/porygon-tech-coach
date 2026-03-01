"""Initial schema: all tables with indexes and pgvector extension.

Revision ID: 001
Revises:
Create Date: 2026-02-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension (must run before creating vector columns)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")

    # -------------------------------------------------------------------------
    # users
    # -------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("google_sub", sa.String(255), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)

    # -------------------------------------------------------------------------
    # goals
    # -------------------------------------------------------------------------
    op.create_table(
        "goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("goal_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="draft"),
        sa.Column("priority", sa.Integer(), nullable=False, default=2),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("smart_criteria", postgresql.JSONB(), nullable=True),
        sa.Column("progress_score", sa.Float(), nullable=False, default=0.0),
        sa.Column("parent_goal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("skill_ids", postgresql.JSONB(), nullable=False, default=[]),
        sa.Column("version", sa.Integer(), nullable=False, default=1),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_goal_id"], ["goals.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goals_user_status", "goals", ["user_id", "status"])
    op.create_index("ix_goals_user_type_status", "goals", ["user_id", "goal_type", "status"])
    op.create_index("ix_goals_target_date", "goals", ["target_date"])
    op.create_index("ix_goals_parent_goal_id", "goals", ["parent_goal_id"])

    # -------------------------------------------------------------------------
    # coaching_sessions (with pgvector embedding)
    # -------------------------------------------------------------------------
    op.create_table(
        "coaching_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, default="active"),
        sa.Column("goal_ids", postgresql.JSONB(), nullable=False, default=[]),
        sa.Column("messages", postgresql.JSONB(), nullable=False, default=[]),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column(
            "embedding",
            postgresql.ARRAY(sa.Float()),
            nullable=True,
            comment="768-dim session embedding for pgvector search",
        ),
        sa.Column("total_tokens_used", sa.Integer(), nullable=False, default=0),
        sa.Column("total_cost_usd", sa.Float(), nullable=False, default=0.0),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, default={}),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sessions_user_type_started",
        "coaching_sessions",
        ["user_id", "session_type", "started_at"],
    )
    op.create_index(
        "ix_sessions_user_status",
        "coaching_sessions",
        ["user_id", "status"],
    )
    # pgvector HNSW index for ANN search
    # Note: Vector column type set up via pgvector extension
    op.execute(
        "ALTER TABLE coaching_sessions ALTER COLUMN embedding TYPE vector(768) "
        "USING embedding::vector(768)"
    )
    op.execute(
        "CREATE INDEX ix_sessions_embedding_hnsw ON coaching_sessions "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # -------------------------------------------------------------------------
    # behavioral_signals
    # -------------------------------------------------------------------------
    op.create_table(
        "behavioral_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("intensity", sa.Float(), nullable=False, default=1.0),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, default={}),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["coaching_sessions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_signals_user_recorded",
        "behavioral_signals",
        ["user_id", "recorded_at"],
    )
    op.create_index(
        "ix_signals_user_type",
        "behavioral_signals",
        ["user_id", "signal_type"],
    )

    # -------------------------------------------------------------------------
    # prompt_versions + evaluation_logs
    # -------------------------------------------------------------------------
    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), default=""),
        sa.Column("system_prompt_hash", sa.String(64), nullable=False),
        sa.Column("eval_score", sa.Float(), nullable=True),
        sa.Column("eval_passed", sa.Boolean(), nullable=True),
        sa.Column("is_production", sa.Boolean(), nullable=False, default=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, default={}),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_name", "version", name="uq_prompt_version"),
    )

    op.create_table(
        "evaluation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prompt_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("eval_score", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, default=False),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, default=0),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, default={}),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["session_id"], ["coaching_sessions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"], ["prompt_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eval_logs_user_created", "evaluation_logs", ["user_id", "created_at"]
    )
    op.create_index("ix_eval_logs_trace_id", "evaluation_logs", ["trace_id"])
    op.create_index("ix_eval_logs_session_id", "evaluation_logs", ["session_id"])


def downgrade() -> None:
    op.drop_table("evaluation_logs")
    op.drop_table("prompt_versions")
    op.drop_table("behavioral_signals")
    op.drop_table("coaching_sessions")
    op.drop_table("goals")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
