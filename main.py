"""
main.py — BharathLedge
Entry point. Handles routing, session, and UI orchestration.

Parts:
  1. Imports + config + session init + auth gate
  2. Login page UI
  3. Dashboard header + greeting
  4. Feature card grid
  5. Feature routing (trends, qa, calculator, forecast, multilingual, history)
"""

import streamlit as st
from pathlib import Path

from features.Auth import supabase_auth as login
import database as db
from feature import get_feature_registry
from features.Multilingual.translator import init_state as ml_init_state, t

# PAGE CONFIG (must be first Streamlit call) 
st.set_page_config(
    page_title = "BharathLedge",
    page_icon  = "🤖",
    layout     = "wide",
    initial_sidebar_state = "collapsed",
)

#  LOAD CSS 
def _load_css(path: Path) -> None:
    with open(path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

_load_css(Path(__file__).parent / "styles.css")

# DEFAULT UI TEXT (English) 
_UI_TEXT_DEFAULT: dict = {
    "b1":           "INR Forecasting",
    "b2":           "Currency Trends",
    "b3":           "ForEx QA",
    "b4":           "Currency Calculator",
    "b5":           "Multilingual & Voice",
    "b6":           "My History",
    "back":         "← Back to Dashboard",
    "history":      "Activity History",
    "logout":       "Sign Out",
    "launch":       "Launch →",
    "soon":         "Coming soon",
    "live":         "Live",
    "morning":      "Good morning",
    "afternoon":    "Good afternoon",
    "evening":      "Good evening",
    "subtitle":     "Here's your INR intelligence dashboard",
    "desc_b1":      "Predict INR exchange rates using ML models",
    "desc_b2":      "Visualise historical currency movements",
    "desc_b3":      "Get instant answers on foreign exchange",
    "desc_b4":      "Convert currencies with live rates",
    "desc_b5":      "Use BharathLedge in your language with voice",
    "desc_b6":      "View your activity across all features",
    "soon_title":   "Coming soon",
    "forecast_msg": "INR Forecasting is under development. Check back in the next update.",
}

# SESSION STATE DEFAULTS 
_DEFAULTS: dict = {
    "logged_in":       False,
    "user_email":      None,
    "username":        None,
    "auth0_sub":       None,
    "current_page":    "dashboard",
    "language":        "English",
    "ui_translations": _UI_TEXT_DEFAULT.copy(),
    "theme":           "light",
    "_user_synced":    False,
}

for _key, _val in _DEFAULTS.items():
    if _key not in st.session_state:
        st.session_state[_key] = _val

# Initialise multilingual state (sets app_lang_code = 'en' on first load)
ml_init_state()

#  THEME — inject data-theme attribute
if st.session_state["theme"] == "dark":
    st.markdown(
        '<script>document.documentElement.setAttribute("data-theme","dark");</script>',
        unsafe_allow_html=True
    )

# AUTH0 CALLBACK HANDLER 
login.handle_callback()

#  AUTH GATE 
if not st.session_state.get("logged_in"):
    login.login_ui()
    st.stop()

# PAST THIS POINT: USER IS AUTHENTICATED 
_email    : str  = st.session_state.get("user_email") or ""
_username : str  = st.session_state.get("username") or "User"

# Build _T dynamically from the active language. Cached at translator level,
# so repeated calls in the same language are free.
_T : dict = {k: t(v) for k, v in _UI_TEXT_DEFAULT.items()}

# Upsert only once per session — not on every rerun
if not st.session_state.get("_user_synced"):
    try:
        db.upsert_user(
            email    = _email,
            name     = _username,
            provider = "google" if st.session_state.get("auth0_sub") else "email",
        )
        st.session_state["_user_synced"] = True
    except Exception:
        pass  # non-critical, don't crash dashboard


# ║  PART 2 — DASHBOARD TOPBAR                                  ║


def _initials(name: str) -> str:
    if not name:
        return "?"
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if name else "?"


col_logo, col_space, col_user, col_toggle, col_logout = st.columns(
    [1.6, 3.5, 2.2, 0.55, 0.85]
)

with col_logo:
    st.markdown("""
        <div class="dash-brand">
            <div class="dash-brand-icon">🤖</div>
            <div class="dash-brand-name">BharathLedge</div>
        </div>
    """, unsafe_allow_html=True)

with col_user:
    st.markdown(f"""
        <div class="dash-user-row">
            <div class="dash-avatar">{_initials(_username)}</div>
            <div class="dash-user-name">{_username}</div>
        </div>
    """, unsafe_allow_html=True)

with col_toggle:
    _is_dark    = st.session_state["theme"] == "dark"
    _icon       = "☀️" if _is_dark else "🌙"
    _toggle_tip = "Switch to light mode" if _is_dark else "Switch to dark mode"
    if st.button(_icon, key="theme_toggle", help=_toggle_tip):
        st.session_state["theme"] = "light" if _is_dark else "dark"
        st.rerun()

with col_logout:
    if st.button(_T["logout"], key="logout_btn", use_container_width=True):
        login.logout()

st.markdown(
    '<hr style="margin:0.1rem 0 1.5rem;border:none;'
    'border-top:1px solid var(--border)">',
    unsafe_allow_html=True
)

#  Apply theme attribute after potential toggle 
if st.session_state["theme"] == "dark":
    st.markdown(
        '<script>document.documentElement'
        '.setAttribute("data-theme","dark");</script>',
        unsafe_allow_html=True
    )
else:
    st.markdown(
        '<script>document.documentElement'
        '.removeAttribute("data-theme");</script>',
        unsafe_allow_html=True
    )

# Greeting 
import datetime as _dt
_hour = _dt.datetime.now().hour
_greeting = (
    _T["morning"]   if _hour < 12 else
    _T["afternoon"] if _hour < 17 else
    _T["evening"]
)

if st.session_state["current_page"] == "dashboard":
    st.markdown(f"""
        <div class="dash-greeting">
            <div class="dash-greeting-title">
                {_greeting}, {_username.split()[0]} 👋
            </div>
            <div class="dash-greeting-sub">
                {_T["subtitle"]}
            </div>
            <div class="teal-rule"></div>
        </div>
    """, unsafe_allow_html=True)


# ║  PART 3 — FEATURE CARD GRID + NAVIGATION                   ║

_FEATURES = [
    {
        "key":    "forecast",
        "icon":   "📈",
        "title":  _T["b1"],
        "desc":   _T["desc_b1"],
        "status": "live",
        "page":   "forecast",
    },
    {
        "key":    "trends",
        "icon":   "📊",
        "title":  _T["b2"],
        "desc":   _T["desc_b2"],
        "status": "live",
        "page":   "trends",
    },
    {
        "key":    "qa",
        "icon":   "💬",
        "title":  _T["b3"],
        "desc":   _T["desc_b3"],
        "status": "live",
        "page":   "qa",
    },
    {
        "key":    "calculator",
        "icon":   "💱",
        "title":  _T["b4"],
        "desc":   _T["desc_b4"],
        "status": "live",
        "page":   "calculator",
    },
    {
        "key":    "multilingual",
        "icon":   "🌐",
        "title":  _T["b5"],
        "desc":   _T["desc_b5"],
        "status": "live",
        "page":   "multilingual",
    },
    {
        "key":    "history",
        "icon":   "🕓",
        "title":  _T["b6"],
        "desc":   _T["desc_b6"],
        "status": "live",
        "page":   "history",
    },
]

#  Dashboard — 3+3 card grid 
if st.session_state["current_page"] == "dashboard":

    # Row 1 — 3 cards
    r1c1, r1c2, r1c3 = st.columns(3, gap="medium")

    for col, feat in zip([r1c1, r1c2, r1c3], _FEATURES[:3]):
        with col:
            _badge = (
                f'<span class="badge badge-teal" '
                f'style="font-size:0.65rem;padding:2px 8px">{_T["live"]}</span>'
                if feat["status"] == "live"
                else
                f'<span class="badge badge-slate" '
                f'style="font-size:0.65rem;padding:2px 8px">{_T["soon"]}</span>'
            )
            st.markdown(f"""
                <div class="feat-card">
                    <div style="display:flex;justify-content:space-between;
                                align-items:flex-start;margin-bottom:0.1rem">
                        <div class="feat-icon-wrap">{feat["icon"]}</div>
                        {_badge}
                    </div>
                    <div class="feat-title">{feat["title"]}</div>
                    <div class="feat-desc">{feat["desc"]}</div>
                </div>
            """, unsafe_allow_html=True)

            _btn_label = _T["launch"] if feat["status"] == "live" else _T["soon"]
            _btn_key   = f"btn_{feat['key']}"

            if feat["status"] == "live":
                if st.button(_btn_label, key=_btn_key, use_container_width=True):
                    st.session_state["current_page"] = feat["page"]
                    db.add_history(_email, feat["title"], "Opened")
                    st.rerun()
            else:
                st.button(
                    _btn_label, key=_btn_key,
                    use_container_width=True, disabled=True
                )

    st.markdown("<div style='height:0.75rem'></div>", unsafe_allow_html=True)

    # Row 2 — 3 cards
    r2c1, r2c2, r2c3 = st.columns(3, gap="medium")

    for col, feat in zip([r2c1, r2c2, r2c3], _FEATURES[3:]):
        with col:
            _badge = (
                f'<span class="badge badge-teal" '
                f'style="font-size:0.65rem;padding:2px 8px">{_T["live"]}</span>'
                if feat["status"] == "live"
                else
                f'<span class="badge badge-slate" '
                f'style="font-size:0.65rem;padding:2px 8px">{_T["soon"]}</span>'
            )
            st.markdown(f"""
                <div class="feat-card">
                    <div style="display:flex;justify-content:space-between;
                                align-items:flex-start;margin-bottom:0.1rem">
                        <div class="feat-icon-wrap">{feat["icon"]}</div>
                        {_badge}
                    </div>
                    <div class="feat-title">{feat["title"]}</div>
                    <div class="feat-desc">{feat["desc"]}</div>
                </div>
            """, unsafe_allow_html=True)

            _btn_label = _T["launch"] if feat["status"] == "live" else _T["soon"]
            _btn_key   = f"btn_{feat['key']}"

            if feat["status"] == "live":
                if st.button(_btn_label, key=_btn_key, use_container_width=True):
                    st.session_state["current_page"] = feat["page"]
                    db.add_history(_email, feat["title"], "Opened")
                    st.rerun()
            else:
                st.button(
                    _btn_label, key=_btn_key,
                    use_container_width=True, disabled=True
                )

# ║  PART 4 — FEATURE ROUTING                                   ║


def _back_btn() -> None:
    if st.button(_T["back"], key="back_btn"):
        st.session_state["current_page"] = "dashboard"
        st.rerun()


_reg = get_feature_registry()

# Trends 
if st.session_state["current_page"] == "trends":
    _back_btn()
    _reg["trends"](db=db, T=_T)

# ForEx QA
elif st.session_state["current_page"] == "qa":
    _back_btn()
    _reg["qa"](db=db, T=_T)

# Currency Calculator 
elif st.session_state["current_page"] == "calculator":
    _back_btn()
    _reg["calculator"](db=db, T=_T)

# INR Forecasting
elif st.session_state["current_page"] == "forecast":
    _back_btn()
    _reg["forecast"](db=db, T=_T)

# History
elif st.session_state["current_page"] == "history":
    _back_btn()
    from features.History.app import render as render_history
    render_history(db=db, T=_T)

# Multilingual & Voice
elif st.session_state["current_page"] == "multilingual":
    _back_btn()
    st.markdown(
        '<div class="content-page-header">'
        '<span style="font-size:1.4rem">🌐</span>'
        f'<div class="content-page-title">{_T["b5"]}</div>'
        '</div>',
        unsafe_allow_html=True
    )
    from features.Multilingual.chat import render as render_multilingual
    render_multilingual()