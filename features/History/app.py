"""
features/History/app.py
User activity history — feature headings with emoji, entries below with date.
"""

import streamlit as st
from datetime import datetime, timezone
from db_client import get_activity_history

_FEATURE_META = {
    "Trends":      {"icon": "📊", "label": "Currency Trends"},
    "Calculator":  {"icon": "💱", "label": "Currency Calculator"},
    "QA":          {"icon": "💬", "label": "ForEx QA"},
    "Forecasting": {"icon": "📈", "label": "INR Forecasting"},
    "Multilingual":{"icon": "🌐", "label": "Multilingual & Voice"},
}


def _format_time(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt.astimezone(timezone.utc)

        if diff.days == 0:
            if diff.seconds < 60:
                return "just now"
            elif diff.seconds < 3600:
                return f"{diff.seconds // 60} min ago"
            else:
                return f"{diff.seconds // 3600} hr ago"
        elif diff.days == 1:
            return f"Yesterday {dt.strftime('%I:%M %p')}"
        elif diff.days < 7:
            return f"{diff.days} days ago"
        else:
            return dt.strftime("%d %b %Y, %I:%M %p")
    except Exception:
        return ts_str


def render(db=None, T=None):
    st.subheader("🕓 My History")
    st.markdown(
        "<div style='color:#94A3B8;font-size:0.85rem;margin-bottom:1.5rem'>"
        "Your activity across all features</div>",
        unsafe_allow_html=True,
    )

    user_email = st.session_state.get("user_email", "")
    if not user_email:
        st.warning("Please log in to view history.")
        return

    with st.spinner("Loading..."):
        try:
            # Using your db_client here
            history = get_activity_history(user_email)
        except Exception as e:
            st.error(f"Could not load history: {e}")
            return

    # Filter only feature activity
    feature_history = [
        h for h in history
        if h.get("feature") in _FEATURE_META
    ]

    if not feature_history:
        st.markdown(
            "<div style='text-align:center;padding:3rem 1rem'>"
            "<div style='font-size:2.5rem;margin-bottom:0.75rem'>📭</div>"
            "<div style='font-weight:600;color:#475569;font-size:1rem;"
            "margin-bottom:0.3rem'>No activity yet</div>"
            "<div style='font-size:0.85rem;color:#94A3B8'>"
            "Start using features to see your history here.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        return

    # Group by feature preserving order of first appearance
    grouped: dict = {}
    for item in feature_history:
        feat = item.get("feature")
        if feat not in grouped:
            grouped[feat] = []
        grouped[feat].append(item)

    # Render each feature section
    for feat, items in grouped.items():
        meta  = _FEATURE_META[feat]
        icon  = meta["icon"]
        label = meta["label"]

        # Feature heading
        st.markdown(
            f"<div style='margin-top:1.5rem;margin-bottom:0.75rem;"
            f"display:flex;align-items:center;gap:8px'>"
            f"<span style='font-size:1.3rem'>{icon}</span>"
            f"<span style='font-size:1rem;font-weight:700;"
            f"color:var(--text-primary,#0F172A)'>{label}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Entries
        for item in items[:15]:
            action   = item.get("action", "—")
            ts       = item.get("created_at", "")
            time_str = _format_time(ts) if ts else ""

            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"align-items:flex-start;padding:0.45rem 0;"
                f"border-bottom:1px solid #F1F5F9'>"
                f"<span style='font-size:0.875rem;"
                f"color:var(--text-secondary,#475569)'>{action}</span>"
                f"<span style='font-size:0.75rem;color:#94A3B8;"
                f"white-space:nowrap;margin-left:16px'>{time_str}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        if len(items) > 15:
            st.caption(f"Showing latest 15 of {len(items)} entries")

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)