"""
Streamlit application entry point.

Multi-page app using Streamlit's native page routing.
Authentication is handled via JWT stored in st.session_state.

Pages:
  1_goals.py       — Goal management and SMART refinement
  2_weekly_plan.py — Weekly plan generation and task tracking
  3_reflections.py — Structured reflection logging
  4_progress.py    — Progress visualization and behavioral signals
  5_chat.py        — AI coaching dialogue
"""

from __future__ import annotations

import streamlit as st

from frontend.auth import handle_oauth_callback, is_authenticated, login_redirect

st.set_page_config(
    page_title="Tech Coach",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main() -> None:
    # Handle OAuth callback (?code=...)
    query_params = st.query_params
    if "code" in query_params:
        handle_oauth_callback(query_params["code"])
        return

    # Auth gate
    if not is_authenticated():
        _render_landing()
        return

    # Authenticated: show main dashboard summary
    _render_dashboard()


def _render_landing() -> None:
    st.title("Tech Coach")
    st.markdown(
        """
        **Your Personal AI Coaching Platform**

        Long-term adaptive coaching for professional development.
        Built on Google Vertex AI (Gemini).
        """
    )
    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Persistent Memory", "PostgreSQL + Vectors")
    with col2:
        st.metric("Planning Engine", "Deterministic + ADHD-aware")
    with col3:
        st.metric("AI Model", "Gemini 1.5 Pro")

    st.divider()

    if st.button("Sign in with Google", type="primary", use_container_width=True):
        login_redirect()


def _render_dashboard() -> None:
    from frontend.api_client import APIClient

    client = APIClient()
    user_token = st.session_state.get("access_token", "")

    st.title("Dashboard")

    # Quick stats row
    col1, col2, col3, col4 = st.columns(4)

    try:
        goals = client.get_goals(token=user_token)
        active_goals = [g for g in goals if g["status"] == "active"]

        with col1:
            st.metric("Active Goals", len(active_goals))

        avg_progress = (
            sum(g["progress_score"] for g in active_goals) / len(active_goals)
            if active_goals
            else 0
        )
        with col2:
            st.metric("Avg Progress", f"{avg_progress:.0%}")

        # Current week plan
        import datetime
        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday())
        try:
            plan = client.get_weekly_plan(token=user_token, week_start=week_start.isoformat())
            pending_tasks = [t for t in plan.get("tasks", []) if t["status"] == "pending"]
            with col3:
                st.metric("Tasks This Week", len(plan.get("tasks", [])))
            with col4:
                st.metric("Pending", len(pending_tasks))
        except Exception:
            with col3:
                st.metric("Tasks This Week", "No plan yet")
            with col4:
                if st.button("Generate Plan"):
                    st.switch_page("pages/2_weekly_plan.py")

    except Exception as exc:
        st.error(f"Error loading dashboard data: {exc}")

    # Navigation cards
    st.divider()
    st.subheader("Navigate to:")

    nav_col1, nav_col2, nav_col3 = st.columns(3)
    with nav_col1:
        if st.button("🎯 Goals", use_container_width=True):
            st.switch_page("pages/1_goals.py")
    with nav_col2:
        if st.button("📋 Weekly Plan", use_container_width=True):
            st.switch_page("pages/2_weekly_plan.py")
    with nav_col3:
        if st.button("💬 Chat with Coach", use_container_width=True, type="primary"):
            st.switch_page("pages/5_chat.py")


if __name__ == "__main__":
    main()
