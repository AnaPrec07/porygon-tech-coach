"""Goals management page."""

from __future__ import annotations

import datetime

import streamlit as st

from frontend.api_client import APIClient
from frontend.auth import require_auth

require_auth()

st.title("Goals")
st.caption("Manage your short-term, quarterly, and long-term goals.")

client = APIClient()
token = st.session_state["access_token"]

# --- Tabs ---
tab_active, tab_create, tab_all = st.tabs(["Active Goals", "Create Goal", "All Goals"])

with tab_active:
    try:
        goals = client.get_goals(token=token, status="active")
    except Exception as exc:
        st.error(f"Failed to load goals: {exc}")
        goals = []

    if not goals:
        st.info("No active goals yet. Create one in the 'Create Goal' tab.")
    else:
        for goal in goals:
            with st.expander(
                f"{'🔴' if goal['priority'] == 4 else '🟡' if goal['priority'] == 3 else '🟢'} "
                f"{goal['title']} — {goal['goal_type'].replace('_', ' ').title()}",
                expanded=False,
            ):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.progress(goal["progress_score"], text=f"Progress: {goal['progress_score']:.0%}")
                    st.caption(f"Target: {goal['target_date']}")
                    if goal.get("description"):
                        st.write(goal["description"])
                with col2:
                    if goal.get("smart_criteria"):
                        if st.button("View SMART", key=f"smart_{goal['id']}"):
                            st.session_state[f"show_smart_{goal['id']}"] = True
                    else:
                        if st.button("Refine SMART", key=f"refine_{goal['id']}", type="primary"):
                            with st.spinner("AI is refining your goal..."):
                                try:
                                    updated = client.refine_goal_smart(
                                        token=token, goal_id=goal["id"]
                                    )
                                    st.success("SMART criteria added!")
                                    st.rerun()
                                except Exception as exc:
                                    st.error(str(exc))

                if st.session_state.get(f"show_smart_{goal['id']}") and goal.get("smart_criteria"):
                    smart = goal["smart_criteria"]
                    for key, label in [
                        ("specific", "Specific"),
                        ("measurable", "Measurable"),
                        ("achievable", "Achievable"),
                        ("relevant", "Relevant"),
                        ("time_bound", "Time-Bound"),
                    ]:
                        if smart.get(key):
                            st.markdown(f"**{label}:** {smart[key]}")

with tab_create:
    with st.form("create_goal_form"):
        st.subheader("New Goal")
        title = st.text_input("Title", max_chars=200, placeholder="e.g., Complete Google Cloud Professional ML Engineer cert")
        description = st.text_area("Description", max_chars=2000, height=100)
        col1, col2 = st.columns(2)
        with col1:
            goal_type = st.selectbox(
                "Type",
                ["short_term", "quarterly", "long_term"],
                format_func=lambda x: x.replace("_", " ").title(),
            )
        with col2:
            priority = st.selectbox(
                "Priority",
                [1, 2, 3, 4],
                index=1,
                format_func=lambda x: {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}[x],
            )
        target_date = st.date_input(
            "Target Date",
            min_value=datetime.date.today() + datetime.timedelta(days=1),
        )

        submitted = st.form_submit_button("Create Goal", type="primary")
        if submitted:
            if not title:
                st.error("Title is required")
            else:
                try:
                    client.create_goal(
                        token=token,
                        goal_data={
                            "title": title,
                            "description": description,
                            "goal_type": goal_type,
                            "priority": priority,
                            "target_date": target_date.isoformat(),
                        },
                    )
                    st.success(f"Goal '{title}' created!")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to create goal: {exc}")

with tab_all:
    try:
        all_goals = client.get_goals(token=token)
    except Exception as exc:
        st.error(str(exc))
        all_goals = []

    if not all_goals:
        st.info("No goals found.")
    else:
        for goal in all_goals:
            status_emoji = {
                "active": "🟢", "paused": "🟡", "completed": "✅",
                "abandoned": "❌", "draft": "📝",
            }.get(goal["status"], "⚪")
            st.write(
                f"{status_emoji} **{goal['title']}** — "
                f"{goal['status'].title()} | {goal['goal_type'].replace('_', ' ').title()} | "
                f"Progress: {goal['progress_score']:.0%}"
            )
