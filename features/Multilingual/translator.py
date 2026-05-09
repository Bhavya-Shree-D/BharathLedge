"""Language state + translation interface. Delegates HTTP to pure_api."""

import logging
import streamlit as st

from .pure_api import translate

log = logging.getLogger(__name__)

LANGUAGES: dict[str, str] = {
    "English":          "en",
    "हिन्दी (Hindi)":     "hi",
    "తెలుగు (Telugu)":   "te",
    "ಕನ್ನಡ (Kannada)":   "kn",
}

_NAME_BY_CODE = {c: n for n, c in LANGUAGES.items()}
_DEFAULT = "en"
_KEY = "app_lang_code"


# ---- state ----------------------------------------------------------------

def init_state() -> None:
    st.session_state.setdefault(_KEY, _DEFAULT)


def get_lang() -> str:
    return st.session_state.get(_KEY, _DEFAULT)


def set_lang(code: str) -> None:
    if code in _NAME_BY_CODE:
        st.session_state[_KEY] = code
    else:
        log.warning("ignored unknown lang code: %s", code)


def get_lang_name() -> str:
    return _NAME_BY_CODE.get(get_lang(), "English")


# ---- translation ----------------------------------------------------------

# Process-scoped cache: (text, src, tgt) → translated text.
_TRANS_CACHE: dict[tuple[str, str, str], str] = {}


def _swap(text: str, src: str, tgt: str) -> str:
    if not text or src == tgt:
        return text
    key = (text, src, tgt)
    cached = _TRANS_CACHE.get(key)
    if cached is not None:
        return cached
    out = translate(text, src, tgt)
    _TRANS_CACHE[key] = out
    return out


def t(text: str) -> str:
    """English UI string → active language."""
    return _swap(text, "en", get_lang())


def to_english(text: str) -> str:
    """Active language → English (for chatbot core)."""
    return _swap(text, get_lang(), "en")


def from_english(text: str) -> str:
    """English (from chatbot core) → active language."""
    return _swap(text, "en", get_lang())


def prewarm(texts: list[str], lang: str | None = None) -> None:
    """Translate `texts` to `lang` in one HTTP call and seed the cache."""
    if not texts:
        return
    code = lang or get_lang()
    if code == "en":
        return

    from .pure_api import translate_batch

    todo = [s for s in texts if s and (s, "en", code) not in _TRANS_CACHE]
    if not todo:
        return

    translated = translate_batch(todo, "en", code)
    for src_text, out in zip(todo, translated):
        _TRANS_CACHE[(src_text, "en", code)] = out


# ---- action ---------------------------------------------------------------

def apply(selected_name: str) -> str:
    """Persist language and return a confirmation in that language."""
    code = LANGUAGES.get(selected_name)
    if code is None:
        log.warning("apply() got unknown name: %s", selected_name)
        code = _DEFAULT
    set_lang(code)

    msg = f"Language set to: {selected_name}"
    return f"✅ {_swap(msg, 'en', code)}"