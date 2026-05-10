# features/Forecasting/app.py

import datetime
import streamlit as st
import pandas as pd
from features.Forecasting.predict import run_predict

_PAIR_LABELS = {
    "USDINR": "🇺🇸 USD → INR",
    "EURINR": "🇪🇺 EUR → INR",
    "JPYINR": "🇯🇵 JPY → INR (per 100)",
}

_CONFIDENCE = {
    1:  ("Low",    "Short-horizon predictions have limited reliability."),
    3:  ("Low",    "Short-horizon predictions have limited reliability."),
    5:  ("Medium", "Moderate signal at this horizon."),
    10: ("High",   "Strong signal — rolling trend features are reliable here."),
    21: ("High",   "Strongest signal — best performing horizon in evaluation."),
}


@st.cache_data(ttl=86400)  # refresh pipeline at most once per day
def _refresh_pipeline() -> str | None:
    """
    Runs the daily data update pipeline (ingest → align → features).
    Returns an error message string if it fails, None on success.
    Cached for 24 hours so it does not re-run on every Streamlit rerun.
    """
    try:
        from features.Forecasting.ingest import run_daily_update
        from features.Forecasting.align import run_alignment
        from features.Forecasting.features import run_feature_engineering

        run_daily_update()
        run_alignment()
        run_feature_engineering()
        return None
    except Exception as e:
        return str(e)


@st.cache_data(ttl=3600)  # cache predictions for 1 hour
def _get_predictions() -> pd.DataFrame:
    return run_predict()


def render(db, T: dict) -> None:
    st.markdown(
        '<div class="content-page-header">'
        '<span style="font-size:1.4rem">📈</span>'
        '<div class="content-page-title">INR Forecasting</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── Refresh pipeline data (once per day) ──────────────────
    pipeline_error = _refresh_pipeline()
    if pipeline_error:
        st.warning(
            f"⚠️ Daily data refresh failed — showing last available data. "
            f"Reason: {pipeline_error}"
        )

    # ── Load predictions ───────────────────────────────────────
    with st.spinner("Loading predictions…"):
        try:
            df = _get_predictions()
        except Exception as e:
            st.error(f"Prediction failed: {e}")
            st.info("Run the full pipeline before using this feature.")
            return

    as_of = df["as_of_date"].iloc[0]

    # Warn if the data is more than 5 calendar days old
    try:
        staleness_days = (datetime.date.today() - as_of).days
        if staleness_days > 5:
            st.warning(
                f"⚠️ Data is {staleness_days} days old (as of {as_of}). "
                "FRED may be delayed or the pipeline failed to update. "
                "Try restarting the app or running the pipeline manually."
            )
    except Exception:
        pass

    st.caption(f"Predictions as of **{as_of}** · Cached for 1 hour · Powered by LightGBM")

    # ── Pair selector ──────────────────────────────────────────
    pair = st.radio(
        "Select currency pair",
        options=list(_PAIR_LABELS.keys()),
        format_func=lambda x: _PAIR_LABELS[x],
        horizontal=True,
        key="forecast_pair",
    )

    pair_df = df[df["pair"] == pair].sort_values("horizon_days")

    if pair_df.empty:
        st.warning("No predictions available for this pair.")
        return

    current_price = pair_df["current_price"].iloc[0]
    st.markdown(f"**Current rate:** ₹ {current_price:,.4f}")

    st.markdown("---")

    # ── Prediction cards — one per horizon ────────────────────
    cols = st.columns(len(pair_df))

    for col, (_, row) in zip(cols, pair_df.iterrows()):
        h             = int(row["horizon_days"])
        pred_price    = row["predicted_price"]
        log_ret       = row["predicted_log_return"]
        target_date   = row["target_date"]
        direction     = "▲" if log_ret > 0 else "▼"
        color         = "#0D9488" if log_ret > 0 else "#E53E3E"
        pct_change    = (pred_price - current_price) / current_price * 100
        conf_label, conf_tip = _CONFIDENCE[h]

        with col:
            st.markdown(
                f"""
                <div style="
                    border:1px solid var(--border);
                    border-radius:12px;
                    padding:1rem 0.75rem;
                    text-align:center;
                ">
                    <div style="font-size:0.7rem;color:#64748B;margin-bottom:0.3rem">
                        {h}d horizon
                    </div>
                    <div style="font-size:1.3rem;font-weight:700;color:#0D9488">
                        ₹ {pred_price:,.4f}
                    </div>
                    <div style="font-size:0.85rem;color:{color};font-weight:600">
                        {direction} {abs(pct_change):.2f}%
                    </div>
                    <div style="font-size:0.65rem;color:#64748B;margin-top:0.4rem">
                        Target: {target_date or "TBD"}
                    </div>
                    <div style="
                        margin-top:0.5rem;
                        font-size:0.6rem;
                        font-weight:600;
                        color:#64748B;
                        text-transform:uppercase;
                        letter-spacing:0.05em;
                    " title="{conf_tip}">
                        Confidence: {conf_label}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # ── Disclaimer ─────────────────────────────────────────────
    st.markdown("---")
    st.caption(
        "⚠️ These are statistical model outputs, not financial advice. "
        "Short-horizon predictions (1d–5d) have limited reliability. "
        "Long-horizon predictions (10d–21d) show stronger historical signal "
        "but past performance does not guarantee future results."
    )

    # Log to history 
    try:
        email = st.session_state.get("user_email", "")
        if email:
            db.add_history(email, "INR Forecasting", f"Viewed {pair}")
    except Exception:
        pass