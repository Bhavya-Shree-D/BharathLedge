from __future__ import annotations
from typing import Callable, Dict, Any
import streamlit as st


def _err(msg: str) -> Callable[..., Any]:
    def _f(*args, **kwargs):
        st.error(msg)
    return _f


@st.cache_resource
def get_feature_registry() -> Dict[str, Callable[..., Any]]:
    registry: Dict[str, Callable[..., Any]] = {}

    try:
        from features.Forecasting.app import render as render_forecast
        registry["forecast"] = render_forecast
    except Exception as e:
        registry["forecast"] = _err(f"Forecasting feature failed to load: {e}")

    try:
        from features.Visualization.app import render as render_trends
        registry["trends"] = render_trends
    except Exception as e:
        registry["trends"] = _err(f"Visualization feature failed to load: {e}")

    try:
        from features.QA.tf_idf import render as render_qa
        registry["qa"] = render_qa
    except Exception as e:
        registry["qa"] = _err(f"Q&A feature failed to load: {e}")

    try:
        from features.Currency_Converter.app import render as render_calc
        registry["calculator"] = render_calc
    except Exception as e:
        registry["calculator"] = _err(f"Currency Converter feature failed to load: {e}")

    try:
        from features.Multilingual.chat import render as render_multilingual
        registry["multilingual"] = render_multilingual
    except Exception as e:
        registry["multilingual"] = _err(f"Multilingual feature failed to load: {e}")

    try:
        from features.History.app import render as render_history
        registry["history"] = render_history
    except Exception as e:
        registry["history"] = _err(f"History feature failed to load: {e}")

    return registry