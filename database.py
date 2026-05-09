"""
database.py — BharathLedge
Supabase wrapper. Single cached client. All writes fail silently.
"""

import os
import streamlit as st
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()


# ── Client — env vars read INSIDE function so load_dotenv() always runs first ──

@st.cache_resource
def _get_client() -> Client:
    """
    Returns a single cached Supabase client for the entire app lifetime.
    Reads env vars here (not at module level) so load_dotenv() is guaranteed
    to have run before these values are captured.
    """
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY", "")

    if not url or not key:
        raise RuntimeError(
            "Supabase credentials missing. "
            "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in your .env file."
        )
    return create_client(url, key)


# ── Feature key normalisation ──────────────────────────────────
# Maps any label used across the app → the canonical key expected
# by _FEATURE_META in features/History/app.py

_TITLE_TO_KEY: dict[str, str] = {
    # Full display titles (used by main.py card buttons)
    "INR Forecasting":      "Forecasting",
    "Currency Trends":      "Trends",
    "ForEx QA":             "QA",
    "Currency Calculator":  "Calculator",
    "Multilingual & Voice": "Multilingual",
    "My History":           "History",
    # Short keys (used by feature files directly) — pass-through
    "Forecasting":          "Forecasting",
    "Trends":               "Trends",
    "QA":                   "QA",
    "Calculator":           "Calculator",
    "Multilingual":         "Multilingual",
    "History":              "History",
    # System events
    "System":               "System",
}


# ── Users ──────────────────────────────────────────────────────

def upsert_user(email: str, name: str, provider: str = "email") -> None:
    """
    Insert or update user record.
    Uses a true upsert (1 network call, not SELECT + INSERT).
    """
    if not email:
        return
    try:
        supa = _get_client()
        supa.table("users").upsert(
            {
                "email":         email,
                "name":          name,
                "auth_provider": provider,
            },
            on_conflict="email",        # requires email to be UNIQUE in Supabase
        ).execute()
    except Exception:
        pass  # non-critical — don't crash the app


def get_user(email: str) -> dict | None:
    if not email:
        return None
    try:
        supa = _get_client()
        result = supa.table("users").select("*").eq("email", email).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def update_password_hash(email: str, password_hash: str) -> None:
    if not email or not password_hash:
        return
    try:
        supa = _get_client()
        supa.table("users").update(
            {"password_hash": password_hash}
        ).eq("email", email).execute()
    except Exception:
        pass


# ── Activity history ───────────────────────────────────────────

def add_history(user_email: str, feature: str, action: str) -> None:
    """
    Log a user action to activity_history.
    Normalises feature name so it always matches _FEATURE_META keys.
    Silent fail — never breaks the app.
    """
    if not user_email or not feature:
        return

    normalised = _TITLE_TO_KEY.get(feature, feature)

    try:
        supa = _get_client()
        supa.table("activity_history").insert({
            "user_email": user_email,
            "feature":    normalised,
            "action":     action or "—",
        }).execute()
    except Exception:
        pass


def get_history(user_email: str) -> list:
    """Fetch all activity history for a user, newest first."""
    if not user_email:
        return []
    try:
        supa = _get_client()
        return (
            supa.table("activity_history")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    except Exception:
        return []


# ── Chat history ───────────────────────────────────────────────

def save_chat(
    user_email: str,
    feature: str,
    user_msg: str,
    bot_response: str,
) -> None:
    if not user_email:
        return
    try:
        supa = _get_client()
        supa.table("chat_history").insert({
            "user_email":   user_email,
            "feature":      feature,
            "user_message": user_msg,
            "bot_response": bot_response,
        }).execute()
    except Exception:
        pass


def get_chat_history(user_email: str, feature: str | None = None) -> list:
    """Fetch chat history for a user, newest first."""
    if not user_email:
        return []
    try:
        supa = _get_client()
        query = (
            supa.table("chat_history")
            .select("*")
            .eq("user_email", user_email)
            .order("created_at", desc=True)   # newest first (was ascending — bug fixed)
        )
        if feature:
            query = query.eq("feature", feature)
        return query.execute().data
    except Exception:
        return []