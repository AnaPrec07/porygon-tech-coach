"""Weekly plan page — generate and track tasks."""

from __future__ import annotations

import datetime

import streamlit as st

from frontend.api_client import APIClient
from frontend.auth import require_auth

require_auth()

st.title("Weekly Plan")
st.caption("AI-assisted weekly plan built on top of deterministic goal allocation.")

client = APIClient()
token = st.session_state["access_token"]

# Current week
today = datetime.date.today()
week_start = today - datetime.timedelta(days=today.weekday())
week_end = week_start + datetime.timedelta(days=6)

st.subheader(f"Week of {week_start.strftime('%b %d')} – {week_end.strftime('%b %d, %Y')}")

# Try to load existing plan
plan = None
try:
    plan = client.get_weekly_plan(token=token, week_start=week_start.isoformat())
except Exception:
    pass

if plan is None:
    st.info("No plan for this week yet.")
    with st.form("generate_form"):
        capacity = st.number_input(
            "Available hours this week",
            min_value=1.0, max_value=60.0, value=20.0, step=0.5,
            help="Hours available for focused work (exclude meetings, personal time)",
        )
        submitted = st.form_submit_button("Generate Weekly Plan", type="primary")
        if submitted:
            with st.spinner("Generating plan with AI + planning engine..."):
                try:
                    result = client.generate_weekly_plan(
                        token=token,
                        week_start=week_start.isoformat(),
                        capacity_hours=capacity,
                    )
                    st.success(
                        f"Plan generated! {result['task_count']} tasks across "
                        f"{result['adjusted_capacity_hours']:.1f}h "
                        f"(burnout risk: {result['burnout_risk_level']})"
                    )
                    if result.get("overcommitted"):
                        st.warning(
                            f"Overcommitment detected: plan uses "
                            f"{result['overcommitment_ratio']:.0%} of adjusted capacity"
                        )
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed to generate plan: {exc}")
else:
    # Display plan
    tasks = plan.get("tasks", [])
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Stats row
    completed = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)
    st.progress(completed / total if total > 0 else 0, text=f"{completed}/{total} tasks completed")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Capacity", f"{plan['capacity_hours']:.0f}h")
    with col2:
        st.metric("Burnout Risk", f"{plan['burnout_risk_at_creation']:.0%}")
    with col3:
        st.metric("Focus Score", f"{plan['focus_score']:.0%}")

    if plan.get("goal_allocations"):
        with st.expander("Goal Allocations"):
            for goal_id, hours in plan["goal_allocations"].items():
                st.write(f"• {goal_id[:8]}... — {hours:.1f}h")

    st.divider()

    # Tasks by day
    tasks_by_day: dict[int, list] = {}
    for t in tasks:
        d = t.get("scheduled_day", 0)
        tasks_by_day.setdefault(d, []).append(t)

    for day_num in sorted(tasks_by_day.keys()):
        day_label = day_names[day_num] if day_num < 7 else f"Day {day_num}"
        date_label = (week_start + datetime.timedelta(days=day_num)).strftime("%b %d")
        st.subheader(f"{day_label} — {date_label}")

        for task in sorted(tasks_by_day[day_num], key=lambda t: t.get("order_in_day", 0)):
            is_mit = task.get("is_mit", False)
            status = task.get("status", "pending")
            load_icon = {"deep_work": "🔵", "medium": "🟡", "admin": "⚪"}.get(
                task.get("cognitive_load", "medium"), "🟡"
            )
            status_icon = {"completed": "✅", "skipped": "⏭️", "pending": "⬜"}.get(status, "⬜")

            col1, col2, col3 = st.columns([5, 1, 2])
            with col1:
                label = f"{'⭐ ' if is_mit else ''}{load_icon} **{task['title']}**"
                if task.get("description"):
                    label += f"\n\n  _{task['description']}_"
                st.markdown(label)
            with col2:
                st.caption(f"{task.get('estimated_minutes', 0)}m")
            with col3:
                if status == "pending":
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅", key=f"done_{task['id']}", help="Mark complete"):
                            try:
                                actual = task.get("estimated_minutes")
                                client.update_task_status(
                                    token=token,
                                    plan_id=plan["plan_id"],
                                    task_id=task["id"],
                                    status="completed",
                                    actual_minutes=actual,
                                )
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                    with c2:
                        if st.button("⏭️", key=f"skip_{task['id']}", help="Skip"):
                            try:
                                client.update_task_status(
                                    token=token,
                                    plan_id=plan["plan_id"],
                                    task_id=task["id"],
                                    status="skipped",
                                )
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
                else:
                    st.write(status_icon)
