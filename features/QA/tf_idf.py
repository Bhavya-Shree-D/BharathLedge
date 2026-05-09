# tf_idf.py - ForEx QA Feature (fixed)
import json
import streamlit as st
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from features.Multilingual.translator import t, to_english
from db_client import log_activity


_WELCOME_EN = (
    "Hello! I can answer your questions about forex and "
    "RBI policies. How can I help you today?"
)
_NO_MATCH_EN = (
    "I couldn't find a good match for your question. "
    "Could you try rephrasing it or ask something else "
    "about forex and RBI policies?"
)


# ── Cache FAQ data for the entire session (fix for Bug 2) ──────────────────
@st.cache_resource
def _load_faq_and_vectorizer():
    """Load FAQ JSON and build TF-IDF vectorizer ONCE per app session."""
    json_path = Path(__file__).parent / "RBI_FAQ.json"
    try:
        with open(json_path, encoding="utf-8") as f:
            faq_data = json.load(f)
    except FileNotFoundError:
        return None, None, None
    except json.JSONDecodeError:
        return None, None, None

    questions = [item["question"] for item in faq_data]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    question_matrix = vectorizer.fit_transform(questions)
    return faq_data, vectorizer, question_matrix


def _find_best_answer(user_question, vectorizer, question_matrix, faq_data, threshold=0.2):
    user_vector = vectorizer.transform([user_question])
    similarities = cosine_similarity(user_vector, question_matrix)[0]
    best_idx = similarities.argmax()
    if similarities[best_idx] < threshold:
        return None
    return faq_data[best_idx]


def render(db=None, T=None):
    header_text = (T.get("b3") if T else None) or t("ForEx QA")
    st.subheader(f"💬 {header_text}")

    theme_base = st.get_option("theme.base") or "light"
    text_color = "#111" if theme_base == "light" else "#f5f5f5"

    st.markdown(
        f"""
        <style>
          div[data-testid="stChatInput"] {{
              background: transparent !important;
              border-top: 0 !important;
              box-shadow: none !important;
          }}
          div[data-testid="stChatInput"] > div {{
              background: transparent !important;
              box-shadow: none !important;
          }}
          div[data-testid="stChatMessage"] p,
          div[data-testid="stChatMessage"] li,
          div[data-testid="stChatMessage"] span {{
              color: {text_color} !important;
          }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # ── Load FAQ + vectorizer (cached — runs once per app session) ──────────
    faq_data, vectorizer, question_matrix = _load_faq_and_vectorizer()

    if faq_data is None:
        st.error(t("FAQ data file not found or corrupted."))
        return

    # ── Session state init ──────────────────────────────────────────────────
    if "qa_messages" not in st.session_state:
        st.session_state.qa_messages = [
            {"role": "assistant", "content_en": _WELCOME_EN}
        ]

    # ── Render existing messages ────────────────────────────────────────────
    for msg in st.session_state.qa_messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "assistant":
                st.markdown(t(msg.get("content_en", "")))
                if msg.get("source_url"):
                    st.caption(f"[{t('Source')}]({msg['source_url']})")
            else:
                st.markdown(msg.get("content", ""))

    # ── Handle new input (Fix for Bug 1: process THEN rerun, no pre-render) ─
    user_input = st.chat_input(t("Ask a question about forex..."))

    if user_input:
        # 1. Append user message
        st.session_state.qa_messages.append(
            {"role": "user", "content": user_input}
        )

        # 2. Find answer (vectorizer already loaded — no lag)
        english_query = to_english(user_input)
        match = _find_best_answer(
            english_query, vectorizer, question_matrix, faq_data
        )

        # 3. Append assistant response
        if match:
            st.session_state.qa_messages.append({
                "role": "assistant",
                "content_en": match["answer"],
                "source_url": match.get("source_url", ""),
            })
            # 4. Log activity
            log_activity(
                st.session_state.get("user_email", ""),
                "QA",
                f"Asked: {user_input[:80]}",
            )
        else:
            st.session_state.qa_messages.append(
                {"role": "assistant", "content_en": _NO_MATCH_EN}
            )

        # 5. Single rerun AFTER all state is committed (fix for double render)
        st.rerun()

    # ── Clear chat ──────────────────────────────────────────────────────────
    if len(st.session_state.qa_messages) > 1:
        if st.button(f"🗑️ {t('Clear Chat')}", key="clear_qa_chat"):
            st.session_state.qa_messages = [
                {"role": "assistant", "content_en": _WELCOME_EN}
            ]
            st.rerun()


if __name__ == "__main__":
    st.set_page_config(page_title="ForEx QA", layout="wide")
    st.title("🧪 QA Feature - Standalone Test")
    render()