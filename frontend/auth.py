"""Authentication utilities for Streamlit frontend."""

from __future__ import annotations

import os

import httpx
import streamlit as st


def is_authenticated() -> bool:
    return "access_token" in st.session_state and bool(st.session_state["access_token"])


def require_auth() -> None:
    """Redirect to landing page if not authenticated."""
    if not is_authenticated():
        st.warning("Please sign in to continue.")
        if st.button("Go to Sign In"):
            st.switch_page("app.py")
        st.stop()


def login_redirect() -> None:
    """Redirect to backend OAuth login endpoint."""
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
    login_url = f"{backend_url}/api/v1/auth/login"
    st.markdown(f'<meta http-equiv="refresh" content="0; url={login_url}">', unsafe_allow_html=True)


def handle_oauth_callback(code: str) -> None:
    """Exchange OAuth code for JWT token via backend callback."""
    backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")

    with st.spinner("Authenticating..."):
        try:
            r = httpx.get(
                f"{backend_url}/api/v1/auth/callback",
                params={"code": code},
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
            st.session_state["access_token"] = data["access_token"]
            # Clear the OAuth code from query params
            st.query_params.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"Authentication failed: {exc}")
            st.stop()
