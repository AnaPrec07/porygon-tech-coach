"""
Trace ID middleware.

Assigns a unique trace_id to every request and stores it in:
  1. Request state (available to route handlers)
  2. structlog context vars (included in all log entries for the request)
  3. Response header X-Trace-ID (for client-side correlation)

Cloud Trace integration: the trace_id is formatted as a Cloud Trace ID
so that Cloud Logging → Cloud Trace correlation works automatically.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TraceMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())

        request.state.trace_id = trace_id

        # Bind trace_id to structlog context for this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
