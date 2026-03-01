# syntax=docker/dockerfile:1.7
# Production Dockerfile for the FastAPI backend
#
# Build stages:
#   1. builder: install dependencies into a clean virtualenv
#   2. runtime: copy only the virtualenv and application code
#
# This produces a minimal image with no build tools.

# --- Build stage ---
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definition
COPY pyproject.toml .

# Install into isolated virtualenv
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# --- Runtime stage ---
FROM python:3.11-slim-bookworm AS runtime

# Security: don't run as root
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Cloud Run: listen on PORT env var (default 8080)
ENV PORT=8080
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check (Cloud Run readiness probe)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

USER appuser

EXPOSE ${PORT}

CMD ["sh", "-c", "uvicorn tech_coach.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level warning"]
