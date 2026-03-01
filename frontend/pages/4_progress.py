"""Progress visualization page."""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

from frontend.api_client import APIClient
from frontend.auth import require_auth

require_auth()

st.title("Progress")
st.caption("Track goal progress, task completion trends, and behavioral signals.")

client = APIClient()
token = st.session_state["access_token"]

# --- Goal Progress Overview ---
st.subheader("Goal Progress")

try:
    goals = client.get_goals(token=token, status="active")

    if not goals:
        st.info("No active goals to display progress for.")
    else:
        # Radar chart for multi-goal progress
        goal_names = [g["title"][:30] + "..." if len(g["title"]) > 30 else g["title"] for g in goals]
        goal_scores = [g["progress_score"] * 100 for g in goals]

        col1, col2 = st.columns([2, 1])
        with col1:
            fig = go.Figure(go.Bar(
                x=goal_scores,
                y=goal_names,
                orientation="h",
                marker_color=[
                    "#2ecc71" if s >= 70 else "#f39c12" if s >= 40 else "#e74c3c"
                    for s in goal_scores
                ],
                text=[f"{s:.0f}%" for s in goal_scores],
                textposition="auto",
            ))
            fig.update_layout(
                title="Active Goal Progress",
                xaxis_title="Progress (%)",
                xaxis=dict(range=[0, 100]),
                height=max(300, len(goals) * 60),
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            for goal in goals:
                priority_label = {1: "Low", 2: "Medium", 3: "High", 4: "Critical"}.get(
                    goal["priority"], "Medium"
                )
                st.metric(
                    label=goal["title"][:25],
                    value=f"{goal['progress_score']:.0%}",
                    delta=None,
                    help=f"Priority: {priority_label} | Target: {goal['target_date']}",
                )

except Exception as exc:
    st.error(f"Failed to load progress data: {exc}")

st.divider()

# --- Weekly Completion Trend ---
st.subheader("Weekly Completion Trend")
st.caption("Task completion rate over the past 8 weeks")

# Placeholder data — in production, fetched from /api/v1/plans/stats
import datetime
import random

weeks = []
for i in range(7, -1, -1):
    d = datetime.date.today() - datetime.timedelta(weeks=i)
    d -= datetime.timedelta(days=d.weekday())
    weeks.append(d.strftime("W%W"))

# Replace with real API data when available
completion_rates = [random.uniform(0.3, 0.9) for _ in weeks]

fig2 = go.Figure()
fig2.add_trace(go.Scatter(
    x=weeks,
    y=[r * 100 for r in completion_rates],
    mode="lines+markers",
    name="Completion Rate",
    line=dict(color="#3498db", width=2),
    marker=dict(size=8),
    fill="tozeroy",
    fillcolor="rgba(52, 152, 219, 0.1)",
))
fig2.add_hline(
    y=80,
    line_dash="dash",
    line_color="green",
    annotation_text="Target: 80%",
)
fig2.update_layout(
    yaxis=dict(range=[0, 100], title="Completion Rate (%)"),
    xaxis_title="Week",
    height=300,
    margin=dict(l=10, r=10, t=10, b=10),
)
st.plotly_chart(fig2, use_container_width=True)

st.divider()

# --- Cost Summary ---
st.subheader("AI Usage Cost")
st.caption("Estimated Vertex AI costs for your coaching sessions")
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("This Month", "$0.00", help="Fetched from evaluation_logs")
with col2:
    st.metric("Avg per Session", "$0.00")
with col3:
    st.metric("Total Sessions", "0")
