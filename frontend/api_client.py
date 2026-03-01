"""HTTP client for communicating with the FastAPI backend."""

from __future__ import annotations

import os
from typing import Any

import httpx


class APIClient:
    """
    HTTP client for the Tech Coach FastAPI backend.

    All requests include the JWT access token in the Authorization header.
    Raises httpx.HTTPStatusError on 4xx/5xx responses (caller handles).
    """

    def __init__(self) -> None:
        self._base_url = os.getenv("BACKEND_URL", "http://localhost:8000")
        self._timeout = httpx.Timeout(30.0, connect=5.0)

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # --- Goals ---

    def get_goals(self, token: str, status: str | None = None) -> list[dict]:
        params = {}
        if status:
            params["status"] = status
        with httpx.Client(timeout=self._timeout) as client:
            r = client.get(
                f"{self._base_url}/api/v1/goals/",
                headers=self._headers(token),
                params=params,
            )
            r.raise_for_status()
            return r.json()

    def create_goal(self, token: str, goal_data: dict) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base_url}/api/v1/goals/",
                headers=self._headers(token),
                json=goal_data,
            )
            r.raise_for_status()
            return r.json()

    def refine_goal_smart(self, token: str, goal_id: str, context: str = "") -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base_url}/api/v1/goals/{goal_id}/refine-smart",
                headers=self._headers(token),
                json={"goal_id": goal_id, "user_context": context},
            )
            r.raise_for_status()
            return r.json()

    # --- Plans ---

    def get_weekly_plan(self, token: str, week_start: str) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.get(
                f"{self._base_url}/api/v1/plans/",
                headers=self._headers(token),
                params={"week_start": week_start},
            )
            r.raise_for_status()
            return r.json()

    def generate_weekly_plan(self, token: str, week_start: str, capacity_hours: float) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base_url}/api/v1/plans/generate",
                headers=self._headers(token),
                json={"week_start": week_start, "capacity_hours": capacity_hours},
                timeout=60.0,  # Plan generation can take up to 30s
            )
            r.raise_for_status()
            return r.json()

    def update_task_status(
        self,
        token: str,
        plan_id: str,
        task_id: str,
        status: str,
        actual_minutes: int | None = None,
    ) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.patch(
                f"{self._base_url}/api/v1/plans/{plan_id}/tasks/{task_id}",
                headers=self._headers(token),
                json={"status": status, "actual_minutes": actual_minutes},
            )
            r.raise_for_status()
            return r.json()

    # --- Sessions ---

    def start_session(self, token: str, session_type: str, goal_ids: list[str]) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base_url}/api/v1/sessions/",
                headers=self._headers(token),
                json={"session_type": session_type, "goal_ids": goal_ids},
            )
            r.raise_for_status()
            return r.json()

    def send_message(self, token: str, session_id: str, content: str) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base_url}/api/v1/sessions/{session_id}/messages",
                headers=self._headers(token),
                json={"content": content},
                timeout=45.0,  # LLM calls can take up to 30s
            )
            r.raise_for_status()
            return r.json()

    def end_session(self, token: str, session_id: str) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            r = client.patch(
                f"{self._base_url}/api/v1/sessions/{session_id}/end",
                headers=self._headers(token),
            )
            r.raise_for_status()
            return r.json()

    def _post(self, token: str, path: str, data: dict) -> dict:
        """Generic POST helper for pages that need direct API access."""
        with httpx.Client(timeout=self._timeout) as client:
            r = client.post(
                f"{self._base_url}{path}",
                headers=self._headers(token),
                json=data,
            )
            r.raise_for_status()
            return r.json()
