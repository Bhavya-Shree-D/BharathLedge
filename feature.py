from __future__ import annotations
from typing import Callable, Dict, Any
from features.Visualization.app import render as render_trends
from features.QA.tf_idf import render as render_qa
from features.Currency_Converter.app import render as render_calc

def _err(msg: str) -> Callable[..., Any]:
    def _f(*args, **kwargs):
        import streamlit as st
        st.error(msg)
    return _f

def get_feature_registry() -> Dict[str, Callable[..., Any]]:
    registry: Dict[str, Callable[..., Any]] = {}

    try:
        from features.Visualization.app import render as render_trends
        registry["trends"] = render_trends
    except Exception as e:
        registry["trends"] = _err(f"Trends feature failed to load: {e}")

    try:
        from features.QA.tf_idf import render as render_qa
        registry["qa"] = render_qa
    except Exception as e:
        registry["qa"] = _err(f"Q&A feature failed to load: {e}")

    try:
        from features.Currency_Converter import render as render_calc
        registry["calculator"] = render_calc
    except Exception as e:
        registry["calculator"] = _err(f"Calculator feature failed to load: {e}")

    try:
        from features.Forecasting.app import render as render_forecast
        registry["forecast"] = render_forecast
    except Exception as e:
        registry["forecast"] = _err(f"Forecasting feature failed to load: {e}")

    return registry
