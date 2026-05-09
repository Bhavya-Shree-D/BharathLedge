"""
Multilingual feature — language selector UI.

Renders heading + dropdown + Go button.
On Go → calls translator.apply() to switch the language globally,
then shows the returned confirmation as a pop-up alert.
"""

import streamlit as st

from .translator import LANGUAGES, init_state, get_lang_name, t, apply


def render() -> None:
    init_state()

    st.markdown(f"### {t('Select your preferred language')}")

    names = list(LANGUAGES.keys())
    current_name = get_lang_name()
    default_index = names.index(current_name) if current_name in names else 0

    selected_name = st.selectbox(
        label="language_dropdown",
        options=names,
        index=default_index,
        label_visibility="collapsed",
        key="ml_dropdown",
    )

    if st.button(t("Go"), key="ml_go_btn"):
        message = apply(selected_name)
        st.session_state["ml_alert"] = message
        st.rerun()

    if "ml_alert" in st.session_state:
        st.toast(st.session_state.pop("ml_alert"), icon="🌐")