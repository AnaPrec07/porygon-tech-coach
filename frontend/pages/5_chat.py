"""
Chat interface page — AI Coaching Dialogue.

Implements a streaming-style chat UI using Streamlit's st.chat_message.
Session state manages the active coaching session and message history.
"""

from __future__ import annotations

import streamlit as st

from frontend.api_client import APIClient
from frontend.auth import require_auth

require_auth()

st.title("Chat with Your Coach")
st.caption("AI-powered coaching dialogue. Your context is remembered across sessions.")

client = APIClient()
token = st.session_state["access_token"]

# --- Session management ---
if "coaching_session_id" not in st.session_state:
    st.session_state.coaching_session_id = None
    st.session_state.chat_messages = []
    st.session_state.session_cost = 0.0

# Sidebar controls
with st.sidebar:
    st.subheader("Session")
    session_type = st.selectbox(
        "Session type",
        ["open_coaching", "goal_setting", "weekly_planning", "reflection", "skill_building"],
        format_func=lambda x: x.replace("_", " ").title(),
    )

    if st.session_state.coaching_session_id is None:
        if st.button("Start New Session", type="primary", use_container_width=True):
            with st.spinner("Starting session..."):
                result = client.start_session(
                    token=token,
                    session_type=session_type,
                    goal_ids=[],
                )
                st.session_state.coaching_session_id = result["session_id"]
                st.session_state.chat_messages = []
                st.session_state.session_cost = 0.0
            st.rerun()
    else:
        st.success(f"Session active")
        st.caption(f"ID: {st.session_state.coaching_session_id[:8]}...")
        st.metric("Session cost", f"${st.session_state.session_cost:.4f}")

        if st.button("End Session", use_container_width=True):
            with st.spinner("Ending session..."):
                result = client.end_session(
                    token=token,
                    session_id=st.session_state.coaching_session_id,
                )
            st.session_state.coaching_session_id = None
            st.session_state.chat_messages = []
            st.success("Session ended.")
            st.rerun()

# --- Chat interface ---
if st.session_state.coaching_session_id is None:
    st.info("Start a coaching session from the sidebar to begin.")
else:
    # Render message history
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("is_fallback"):
                st.caption("⚠️ AI temporarily unavailable — rule-based response")

    # Input
    if prompt := st.chat_input("Message your coach..."):
        # Display user message immediately
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.chat_messages.append({"role": "user", "content": prompt})

        # Get AI response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    result = client.send_message(
                        token=token,
                        session_id=st.session_state.coaching_session_id,
                        content=prompt,
                    )
                    response_text = result["response"]
                    is_fallback = result.get("is_fallback", False)
                    cost = result.get("estimated_cost_usd", 0.0)

                    st.markdown(response_text)
                    if is_fallback:
                        st.caption("⚠️ AI temporarily unavailable — rule-based response")

                    col1, col2 = st.columns([4, 1])
                    with col2:
                        token_info = result.get("token_usage", {})
                        st.caption(
                            f"↑{token_info.get('input_tokens', 0)} "
                            f"↓{token_info.get('output_tokens', 0)} tokens"
                        )

                    st.session_state.chat_messages.append({
                        "role": "assistant",
                        "content": response_text,
                        "is_fallback": is_fallback,
                    })
                    st.session_state.session_cost += cost

                except Exception as exc:
                    st.error(f"Error: {exc}")
