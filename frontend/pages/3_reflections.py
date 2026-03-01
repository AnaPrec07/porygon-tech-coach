"""Weekly reflection logging page."""

from __future__ import annotations

import datetime

import streamlit as st

from frontend.api_client import APIClient
from frontend.auth import require_auth

require_auth()

st.title("Reflections")
st.caption("Weekly structured reflection. Takes 5–10 minutes. Feeds into your coaching AI.")

client = APIClient()
token = st.session_state["access_token"]

tab_new, tab_history = st.tabs(["New Reflection", "History"])

with tab_new:
    today = datetime.date.today()
    # Default to last Monday
    last_monday = today - datetime.timedelta(days=today.weekday())

    with st.form("reflection_form"):
        week_date = st.date_input(
            "Week start (Monday)",
            value=last_monday,
            help="Which week are you reflecting on?",
        )

        st.markdown("#### Energy & Satisfaction")
        col1, col2 = st.columns(2)
        with col1:
            energy = st.select_slider(
                "Energy level this week",
                options=[1, 2, 3, 4, 5],
                value=3,
                format_func=lambda x: {1: "😴 Depleted", 2: "😕 Low", 3: "😐 Okay",
                                        4: "😊 Good", 5: "⚡ Excellent"}[x],
            )
        with col2:
            satisfaction = st.select_slider(
                "Task completion satisfaction",
                options=[1, 2, 3, 4, 5],
                value=3,
                format_func=lambda x: {1: "😞 Very unsatisfied", 2: "😕 Unsatisfied",
                                        3: "😐 Neutral", 4: "😊 Satisfied",
                                        5: "🎉 Very satisfied"}[x],
            )

        st.markdown("#### Reflection (answer what resonates)")
        wins = st.text_area("What went well this week?", max_chars=2000, height=80)
        challenges = st.text_area("What was difficult or blocked you?", max_chars=2000, height=80)
        insights = st.text_area("What did you learn about yourself or your work?", max_chars=2000, height=80)
        next_focus = st.text_input(
            "Single most important focus for next week:",
            max_chars=1000,
            help="One thing. Not a list.",
        )
        raw_text = st.text_area(
            "Anything else you want to capture?",
            max_chars=5000,
            height=80,
            help="Free-form notes. Not required.",
        )

        submitted = st.form_submit_button("Save Reflection", type="primary")
        if submitted:
            with st.spinner("Saving and analysing..."):
                try:
                    result = client._post(
                        token=token,
                        path="/api/v1/reflections/",
                        data={
                            "week_start": week_date.isoformat(),
                            "wins": wins or None,
                            "challenges": challenges or None,
                            "insights": insights or None,
                            "next_week_focus": next_focus or None,
                            "energy_level": energy,
                            "completion_satisfaction": satisfaction,
                            "raw_text": raw_text or None,
                        },
                    )
                    st.success("Reflection saved!")
                    if result.get("analysis_summary"):
                        st.info(f"**AI Analysis:** {result['analysis_summary']}")
                except Exception as exc:
                    st.error(f"Failed to save: {exc}")

with tab_history:
    try:
        import httpx
        r = httpx.get(
            f"{client._base_url}/api/v1/reflections/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        r.raise_for_status()
        reflections = r.json()
        if not reflections:
            st.info("No reflections yet.")
        else:
            for ref in reflections:
                emoji = {1: "😴", 2: "😕", 3: "😐", 4: "😊", 5: "⚡"}.get(
                    ref.get("energy_level"), "📝"
                )
                st.write(
                    f"{emoji} **{ref['week_start']}** "
                    f"{'🤖 Analysed' if ref.get('has_analysis') else ''}"
                )
    except Exception as exc:
        st.error(str(exc))
