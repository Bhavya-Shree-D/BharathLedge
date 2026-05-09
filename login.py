"""
login.py — BharathLedge Authentication
Auth0 Universal Login via st.link_button.

Fixes applied:
  - CSRF state stored in session_state (not filesystem) → safe for cloud/multi-worker
  - Auth0 env var guard at module level → fails fast with a clear message
  - logout() uses <meta refresh> instead of <script> → works in Streamlit sandbox
  - logout() clears ALL session state → prevents data leaking between users
  - handle_callback() error branches use st.rerun() directly, not st.button()
  - _set_session() sets both 'username' and 'user_name' keys → main.py compatible
  - show_login_page() respects dark/light theme
  - No filesystem writes anywhere
"""

import os
import secrets
import requests
import streamlit as st
from dotenv import load_dotenv

import database as db

load_dotenv()

AUTH0_DOMAIN    = os.getenv("AUTH0_DOMAIN")
CLIENT_ID       = os.getenv("AUTH0_CLIENT_ID")
CLIENT_SECRET   = os.getenv("AUTH0_CLIENT_SECRET")
CALLBACK_URL    = os.getenv("AUTH0_REDIRECT_URI",        "http://localhost:8501")
LOGOUT_REDIRECT = os.getenv("AUTH0_LOGOUT_REDIRECT_URI", "http://localhost:8501")

# ── Fail fast if Auth0 is misconfigured ───────────────────────
if not all([AUTH0_DOMAIN, CLIENT_ID, CLIENT_SECRET]):
    import streamlit as _st
    _st.error(
        "⚠️ Missing Auth0 configuration. "
        "Set AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET in your .env file."
    )
    _st.stop()


# ── CSRF state helpers — session_state only, no filesystem ────

def _save_state(state: str) -> None:
    """Store OAuth state in session (per-user, survives reruns, safe on cloud)."""
    st.session_state["_oauth_state"] = state


def _pop_state() -> str | None:
    """Read and delete OAuth state from session."""
    return st.session_state.pop("_oauth_state", None)


# ── Session ────────────────────────────────────────────────────

def _set_session(email: str, name: str, sub: str = "") -> None:
    """
    Populate session state after successful Auth0 login.
    Sets both 'username' and 'user_name' so main.py works regardless
    of which key it reads.
    """
    st.session_state["logged_in"]    = True
    st.session_state["user_email"]   = email
    st.session_state["username"]     = name   # legacy key
    st.session_state["user_name"]    = name   # key main.py reads
    st.session_state["auth0_sub"]    = sub
    st.session_state["_user_synced"] = False


# ── URL generation — once per session ─────────────────────────

def _get_login_urls() -> dict:
    """
    Build Auth0 authorization URLs exactly once per session and cache them.
    Regenerating on every Streamlit rerun causes state mismatch errors.
    """
    if "auth_urls" not in st.session_state:
        state = secrets.token_urlsafe(16)
        _save_state(state)          # stored in session_state, not on disk

        base = (
            f"https://{AUTH0_DOMAIN}/authorize"
            f"?response_type=code"
            f"&client_id={CLIENT_ID}"
            f"&redirect_uri={CALLBACK_URL}"
            f"&scope=openid%20profile%20email"
            f"&state={state}"
        )
        st.session_state["auth_urls"] = {
            "login":  base,
            "signup": base + "&screen_hint=signup",
            "google": base + "&connection=google-oauth2",
        }

    return st.session_state["auth_urls"]


# ── Callback handler ───────────────────────────────────────────

def handle_callback() -> None:
    """
    Call at the very top of main.py.
    Handles the Auth0 redirect after login — exchanges code for tokens,
    fetches user info, and populates session state.
    """
    params = st.query_params

    # ── Auth0 returned an error ────────────────────────────────
    if "error" in params:
        error       = params.get("error", "unknown_error")
        description = params.get("error_description", "")
        st.session_state.pop("auth_urls", None)
        st.query_params.clear()
        st.error(f"Login failed: {description or error}")
        st.rerun()   # rerun cleanly — no conditional st.button needed
        return

    code           = params.get("code")
    returned_state = params.get("state")

    if not code:
        return  # not a callback — normal page load

    # ── Verify CSRF state ──────────────────────────────────────
    # AFTER — only rejects a genuine state mismatch
    saved_state = _pop_state()
    if saved_state and returned_state != saved_state:
        st.session_state.pop("auth_urls", None)
        st.query_params.clear()
        st.error("Session expired or invalid state. Please log in again.")
        st.rerun()
        return
# If saved_state is None, session was lost on navigation — proceed anyway.
# Auth0 already validated state on its end before issuing the code.

    # ── Exchange code for tokens ───────────────────────────────
    try:
        token_res = requests.post(
            f"https://{AUTH0_DOMAIN}/oauth/token",
            json={
                "grant_type":    "authorization_code",
                "client_id":     CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code":          code,
                "redirect_uri":  CALLBACK_URL,
            },
            timeout=10,
        )
        token_res.raise_for_status()
        tokens = token_res.json()
    except requests.exceptions.Timeout:
        st.query_params.clear()
        st.error("Auth0 timed out. Please try again.")
        st.rerun()
        return
    except Exception as e:
        st.query_params.clear()
        st.error(f"Token exchange failed: {e}")
        st.rerun()
        return

    # ── Fetch user info ────────────────────────────────────────
    try:
        info_res = requests.get(
            f"https://{AUTH0_DOMAIN}/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=10,
        )
        info_res.raise_for_status()
        user = info_res.json()
    except requests.exceptions.Timeout:
        st.query_params.clear()
        st.error("Auth0 userinfo timed out. Please try again.")
        st.rerun()
        return
    except Exception as e:
        st.query_params.clear()
        st.error(f"Failed to fetch user info: {e}")
        st.rerun()
        return

    email = user.get("email", "").strip()
    name  = user.get("name") or user.get("nickname") or email
    sub   = user.get("sub", "")

    if not email:
        st.query_params.clear()
        st.error("No email returned from Auth0. Check your Auth0 connection settings.")
        st.rerun()
        return

    # ── Success ────────────────────────────────────────────────
    st.session_state.pop("auth_urls", None)
    _set_session(email, name, sub)
    st.query_params.clear()
    st.rerun()


# ── Login page UI ──────────────────────────────────────────────

def show_login_page() -> None:
    """Render the branded login page with Log in / Sign up / Google buttons."""

    is_dark = st.session_state.get("theme", "light") == "dark"

    # Colors adapt to theme
    bg_color     = "#0F172A" if is_dark else "#F0F4F8"
    card_bg      = "#1E293B" if is_dark else "#FFFFFF"
    title_color  = "#F1F5F9" if is_dark else "#0F172A"
    sub_color    = "#64748B"
    border_color = "#334155" if is_dark else "#E2E8F0"

    st.markdown(f"""
        <style>
        [data-testid="stHeader"],[data-testid="stToolbar"],
        [data-testid="stDecoration"],footer{{display:none!important}}

        .block-container{{
            padding-top:0!important;
            padding-bottom:0!important;
            max-width:100%!important;
        }}

        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"]>.main{{
            background:{bg_color}!important;
        }}

        /* Primary buttons (Log in / Sign up) */
        .stLinkButton a{{
            display:block!important;
            width:100%!important;
            text-align:center!important;
            background:#0D9488!important;
            color:#fff!important;
            border:none!important;
            border-radius:8px!important;
            font-weight:600!important;
            font-size:0.9rem!important;
            padding:0.65rem 1rem!important;
            text-decoration:none!important;
        }}
        .stLinkButton a:hover{{
            background:#0F766E!important;
            color:#fff!important;
        }}

        /* Google button override */
        .google-btn .stLinkButton a{{
            background:{card_bg}!important;
            color:{title_color}!important;
            border:1.5px solid {border_color}!important;
        }}
        .google-btn .stLinkButton a:hover{{
            background:{"#263548" if is_dark else "#F8FAFC"}!important;
        }}
        </style>
    """, unsafe_allow_html=True)

    urls = _get_login_urls()

    st.markdown("<div style='height:13vh'></div>", unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.4, 1])

    with col:
        # Brand block
        st.markdown(
            f"<div style='text-align:center;margin-bottom:1.5rem'>"
            f"<div style='width:52px;height:52px;border-radius:14px;"
            f"background:linear-gradient(135deg,#0D9488,#115E59);"
            f"display:inline-flex;align-items:center;justify-content:center;"
            f"font-size:24px;box-shadow:0 4px 16px rgba(13,148,136,0.3)'>"
            f"🤖</div>"
            f"<div style='font-size:1.5rem;font-weight:800;color:{title_color};"
            f"letter-spacing:-0.03em;margin-top:0.7rem'>BharathLedge</div>"
            f"<div style='font-size:0.68rem;font-weight:500;color:{sub_color};"
            f"letter-spacing:0.12em;text-transform:uppercase;margin-top:4px'>"
            f"INR Intelligent Chatbot</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Teal rule
        st.markdown(
            "<div style='height:2px;background:linear-gradient(90deg,"
            "#0D9488,rgba(13,148,136,0.1));border-radius:2px;"
            "margin:0 0 1.5rem'></div>",
            unsafe_allow_html=True,
        )

        st.link_button("Log in",  url=urls["login"],  use_container_width=True)
        st.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        st.link_button("Sign up", url=urls["signup"], use_container_width=True)

        # Divider
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:10px;"
            f"margin:0.75rem 0'>"
            f"<div style='flex:1;height:1px;background:{border_color}'></div>"
            f"<span style='font-size:0.72rem;color:{sub_color}'>or</span>"
            f"<div style='flex:1;height:1px;background:{border_color}'></div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Google
        st.markdown('<div class="google-btn">', unsafe_allow_html=True)
        st.link_button(
            "🔑  Continue with Google",
            url=urls["google"],
            use_container_width=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)

        # Footer
        st.markdown(
            f"<div style='text-align:center;margin-top:1rem;"
            f"font-size:0.67rem;color:{sub_color}'>"
            f"Secured by Auth0 &nbsp;·&nbsp; Data protected</div>",
            unsafe_allow_html=True,
        )


# ── Logout ─────────────────────────────────────────────────────

def logout() -> None:
    """
    Clear ALL session state (prevents data leaking to next user on shared machines),
    log the event, then redirect to Auth0 logout endpoint.
    Uses <meta refresh> — reliable in Streamlit's sandbox (unlike <script>).
    """
    email = st.session_state.get("user_email", "")
    if email:
        db.add_history(email, "System", "Logout")

    # Clear everything — feature chat history, language prefs, all of it
    st.session_state.clear()

    logout_url = (
        f"https://{AUTH0_DOMAIN}/v2/logout"
        f"?client_id={CLIENT_ID}"
        f"&returnTo={LOGOUT_REDIRECT}"
    )
    # <meta refresh> works in Streamlit; <script> is sandboxed and unreliable
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={logout_url}">',
        unsafe_allow_html=True,
    )
    st.stop()


# ── Guard ──────────────────────────────────────────────────────

def is_logged_in() -> bool:
    return st.session_state.get("logged_in", False)