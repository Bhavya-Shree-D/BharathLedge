"""
features/Auth/supabase_auth.py
Replaces auth0_sso.py — uses Supabase Auth for email/password + Google OAuth.
"""

import streamlit as st
from db_client import get_db

supabase = get_db()


def _init_state():
    for k, v in {
        "logged_in": False,
        "user_email": "",
        "user_name": "",
        "auth0_sub": "",  # kept for DB compatibility — we'll store Supabase UID here
        "_show_reset_form": False,
        "_reset_result": None,
    }.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _set_session(user):
    """Populate session state from Supabase user object."""
    st.session_state.logged_in  = True
    st.session_state.user_email = user.email or ""
    st.session_state.auth0_sub  = user.id
    st.session_state.user_name  = (
        (user.user_metadata or {}).get("full_name")
        or (user.user_metadata or {}).get("name")
        or (user.email or "").split("@")[0]
    )
    st.session_state.username = st.session_state.user_name


def handle_callback():
    """
    Drop-in replacement for auth0_sso.handle_callback().
    Call this at the top of main.py — handles Google OAuth redirect.
    """
    _init_state()

    params = st.query_params
    if "code" in params:
        try:
            code = params["code"]
            session = supabase.auth.exchange_code_for_session({"auth_code": code})
            if session and session.user:
                _set_session(session.user)
                st.query_params.clear()
                st.rerun()
        except Exception as e:
            st.error(f"Google login error: {e}")
            st.query_params.clear()

    if not st.session_state.logged_in:
        try:
            session = supabase.auth.get_session()
            if session and session.user:
                _set_session(session.user)
        except Exception:
            pass


def login_ui():
    """
    Renders Login / Sign Up / Google tabs.
    Call this when user is not logged in.
    """
    st.markdown(
        "<h2 style='text-align:center'>🏦 BharathLedge</h2>"
        "<p style='text-align:center;color:#64748B'>INR Intelligent Chatbot</p>",
        unsafe_allow_html=True,
    )

    tab_login, tab_signup, tab_google = st.tabs(["Login", "Sign Up", "Google"])

    # ── LOGIN ────────────────────────────────────────────────────────────────
    with tab_login:
        st.markdown("#### Welcome back 👋")
        email = st.text_input("Email", key="li_email",
                               placeholder="you@example.com")
        password = st.text_input("Password", key="li_pass",
                                  type="password", placeholder="••••••••")

        if st.button("Login", key="btn_login", type="primary",
                     use_container_width=True):
            if not email or not password:
                st.warning("Please enter email and password.")
            else:
                _do_login(email.strip(), password)

        # ── FORGOT PASSWORD ──────────────────────────────────────────────────
        st.markdown("<div style='height:0.3rem'></div>", unsafe_allow_html=True)

        col_left, _ = st.columns([1, 2])
        with col_left:
            if st.button("Forgot password?", key="toggle_reset", type="secondary"):
                st.session_state["_show_reset_form"] = not st.session_state.get(
                    "_show_reset_form", False
                )
                st.session_state["_reset_result"] = None
                st.rerun()

        if st.session_state.get("_show_reset_form"):
            st.markdown("---")
            st.markdown("##### Reset your password")
            st.caption("Enter your account email. We'll send a reset link.")

            reset_email = st.text_input(
                "Account email",
                key="reset_email_input",
                placeholder="you@example.com",
                label_visibility="collapsed",
            )

            col_send, col_cancel = st.columns([2, 1])

            with col_send:
                if st.button("Send reset link", key="send_reset_btn",
                             use_container_width=True, type="primary"):
                    if not reset_email or "@" not in reset_email:
                        st.session_state["_reset_result"] = (
                            False, "Enter a valid email address."
                        )
                    else:
                        ok, msg = _do_forgot_password(reset_email.strip())
                        st.session_state["_reset_result"] = (ok, msg)
                    st.rerun()

            with col_cancel:
                if st.button("Cancel", key="cancel_reset_btn",
                             use_container_width=True):
                    st.session_state["_show_reset_form"] = False
                    st.session_state["_reset_result"] = None
                    st.rerun()

            result = st.session_state.get("_reset_result")
            if result:
                ok, msg = result
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    # ── SIGN UP ──────────────────────────────────────────────────────────────
    with tab_signup:
        st.markdown("#### Create your account 🆕")
        name    = st.text_input("Full Name", key="su_name",
                                 placeholder="Bhavya Shree")
        email_s = st.text_input("Email", key="su_email",
                                 placeholder="you@example.com")
        pass_s  = st.text_input("Password", key="su_pass",
                                 type="password", placeholder="Min 6 characters")
        conf_s  = st.text_input("Confirm Password", key="su_conf",
                                 type="password", placeholder="Re-enter password")

        if st.button("Sign Up", key="btn_signup", type="primary",
                     use_container_width=True):
            if not all([name, email_s, pass_s, conf_s]):
                st.warning("Please fill all fields.")
            else:
                _do_signup(name, email_s.strip(), pass_s, conf_s)

    # ── GOOGLE ───────────────────────────────────────────────────────────────
    with tab_google:
        st.markdown("#### Sign in with Google 🔵")
        st.caption("You'll be redirected to Google and brought back automatically.")

        if st.button("Continue with Google", key="btn_google",
                     type="primary", use_container_width=True):
            _do_google()


def logout():
    """Drop-in replacement for auth0_sso.logout()."""
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state.update({
        "logged_in": False,
        "user_email": "",
        "user_name": "",
        "auth0_sub": "",
    })
    st.rerun()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _do_login(email: str, password: str):
    try:
        res = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        if res.user:
            _set_session(res.user)
            st.rerun()
        else:
            st.error("❌ Invalid email or password.")
    except Exception as e:
        msg = str(e)
        if "Invalid login credentials" in msg:
            st.error("❌ Invalid email or password.")
        elif "Email not confirmed" in msg:
            st.warning("📧 Please confirm your email first — check your inbox.")
        else:
            st.error(f"Login failed: {msg}")


def _do_signup(name: str, email: str, password: str, confirm: str):
    if password != confirm:
        st.error("❌ Passwords do not match.")
        return
    if len(password) < 6:
        st.error("❌ Password must be at least 6 characters.")
        return
    try:
        res = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {"data": {"full_name": name}},
        })
        if res.user:
            st.success("✅ Account created! Check your email to confirm before logging in.")
        else:
            st.error("Signup failed — please try again.")
    except Exception as e:
        msg = str(e)
        if "already registered" in msg:
            st.error("❌ Email already registered. Please log in instead.")
        else:
            st.error(f"Signup failed: {msg}")


def _do_google():
    try:
        res = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": "http://localhost:8501"},  # change for prod
        })
        if res.url:
            st.markdown(
                f'<meta http-equiv="refresh" content="0; url={res.url}">',
                unsafe_allow_html=True,
            )
    except Exception as e:
        st.error(f"Google login failed: {e}")


def _do_forgot_password(email: str) -> tuple[bool, str]:
    """
    Calls Supabase reset_password_for_email.
    Supabase sends a reset link to the address.
    Returns (success: bool, message: str).
    """
    try:
        supabase.auth.reset_password_for_email(email)
        return True, "✅ Reset link sent! Check your inbox (and spam folder)."
    except Exception as e:
        msg = str(e)
        return False, f"Failed to send reset link: {msg}"