"""Authentication utilities for Streamlit frontend.

DEBUG_MODE=True (default):
  - is_authenticated() always returns True
  - require_auth() is a no-op (sets a placeholder token so pages can read it)
  - OAuth callback and login redirect are bypassed

DEBUG_MODE=False:
  - Full OAuth flow is active; JWT stored in st.session_state["access_token"]

To re-enable full auth: set the DEBUG_MODE environment variable to "false".
"""

from __future__ import annotations

import os

import httpx
import streamlit as st

# Feature flag — mirrors settings.debug_mode on the backend.
# Read from env so both frontend and backend share the same toggle.
DEBUG_MODE: bool = os.getenv("DEBUG_MODE", "true").lower() not in ("false", "0", "no")

# Placeholder token sent to the backend in debug mode.
# The backend ignores it when debug_mode=True; it is never validated.
_DEBUG_TOKEN = "debug-mode-token"


def is_authenticated() -> bool:
    if DEBUG_MODE:
        return True
    return "access_token" in st.session_state and bool(st.session_state["access_token"])


def require_auth() -> None:
    """
    Enforce authentication gate.

    In debug mode: sets a placeholder access_token so downstream pages that
    read st.session_state["access_token"] work without modification.
    In production mode: redirects to landing page if unauthenticated.
    """
    if DEBUG_MODE:
        if "access_token" not in st.session_state:
            st.session_state["access_token"] = _DEBUG_TOKEN
        return

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
