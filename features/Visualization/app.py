"""
Currency Trends Visualization Feature - app.py
Data source: data/raw/yfinance.parquet (USDINR, EURINR, JPYINR columns)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objs as go
from pathlib import Path
from datetime import datetime, timedelta

# Column names in yfinance.parquet and their display labels
PAIR_LABELS = {
    "USDINR": "USD/INR",
    "EURINR": "EUR/INR",
    "JPYINR": "JPY/INR",
}

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "yfinance.parquet"


@st.cache_data(ttl=3600)
def _load_prices() -> pd.DataFrame:
    # Cache for 1 hour — parquet only updates once a day via daily_update.py
    df = pd.read_parquet(DATA_PATH, engine="pyarrow", columns=list(PAIR_LABELS.keys()))
    df.index = pd.to_datetime(df.index)
    df.index.name = "Date"
    return df.sort_index()


def render(db=None, T=None):
    header_text = T.get("b2", "Currency Trends") if T else "Currency Trends"
    st.subheader(f"📊 {header_text}")

    if not DATA_PATH.exists():
        st.error(
            "❌ Price data not found. Run the forecasting pipeline first: "
            "`python features/Forecasting/ingest.py full`"
        )
        return

    try:
        df = _load_prices()
    except Exception as e:
        st.error(f"❌ Error loading price data: {e}")
        return

    if df.empty:
        st.error("❌ Price data is empty. Re-run ingest.py.")
        return

    ui_min = df.index.min().date()
    ui_max = df.index.max().date()

    st.info(
        f"📅 Data available from {pd.Timestamp(ui_min).strftime('%d-%b-%Y')} "
        f"to {pd.Timestamp(ui_max).strftime('%d-%b-%Y')}"
    )

    st.markdown("### Select Parameters")

    col1, col2, col3, col4 = st.columns([1.5, 1.5, 1.5, 1])

    with col1:
        currency = st.selectbox(
            "Currency:",
            options=list(PAIR_LABELS.keys()),
            format_func=lambda x: PAIR_LABELS[x],
            key="trend_currency",
        )

    default_end   = ui_max
    default_start = max(ui_min, (datetime.strptime(str(default_end), "%Y-%m-%d") - timedelta(days=365)).date())

    with col2:
        start_date = st.date_input(
            "From Date:",
            value=default_start,
            min_value=ui_min,
            max_value=ui_max,
            key="trend_start_date",
        )

    with col3:
        end_date = st.date_input(
            "To Date:",
            value=default_end,
            min_value=ui_min,
            max_value=ui_max,
            key="trend_end_date",
        )

    with col4:
        st.markdown("<br>", unsafe_allow_html=True)
        go_button = st.button("GO", key="go_btn", type="primary", use_container_width=True)

    if go_button:
        if start_date > end_date:
            st.error("❌ Start date must be before end date.")
            return

        filtered = df.loc[
            (df.index >= pd.Timestamp(start_date)) &
            (df.index <= pd.Timestamp(end_date)),
            currency,
        ].dropna()

        if filtered.empty:
            st.warning("⚠️ No data available in the selected date range.")
            return

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=filtered.index,
            y=filtered.values,
            mode="lines",
            name=PAIR_LABELS[currency],
            line=dict(color="#1f77b4", width=2),
            hovertemplate=(
                "<b>Date</b>: %{x|%d-%b-%Y}<br>"
                "<b>Rate</b>: ₹%{y:.4f}<extra></extra>"
            ),
        ))

        fig.update_layout(
            title={
                "text": (
                    f"{PAIR_LABELS[currency]} Exchange Rate "
                    f"({start_date.strftime('%d-%b-%Y')} to {end_date.strftime('%d-%b-%Y')})"
                ),
                "x": 0.5,
                "xanchor": "center",
            },
            xaxis_title="Date",
            yaxis_title="INR per unit",
            hovermode="x unified",
            height=500,
            template="plotly_white",
            showlegend=True,
        )

        st.plotly_chart(fig, use_container_width=True)

        if db:
            try:
                db.add_history(
                    st.session_state.get("user_email", ""),
                    "Currency Trends",
                    f"Visualized {PAIR_LABELS[currency]} from {start_date} to {end_date}",
                )
            except Exception:
                pass

        with st.expander("📊 View Statistics", expanded=False):
            max_val  = filtered.max()
            min_val  = filtered.min()
            avg_val  = filtered.mean()
            max_date = filtered.idxmax().strftime("%d-%b-%Y")
            min_date = filtered.idxmin().strftime("%d-%b-%Y")

            ca, cb, cc, cd = st.columns(4)
            with ca:
                st.metric("Highest Rate", f"₹{max_val:.4f}", delta=f"on {max_date}")
            with cb:
                st.metric("Lowest Rate",  f"₹{min_val:.4f}", delta=f"on {min_date}")
            with cc:
                st.metric("Average Rate", f"₹{avg_val:.4f}")
            with cd:
                st.metric("Data Points",  len(filtered))

            if len(filtered) > 1:
                st.markdown("---")
                st.markdown("**Additional Insights:**")
                start_rate   = float(filtered.iloc[0])
                end_rate     = float(filtered.iloc[-1])
                change       = end_rate - start_rate
                change_pct   = (change / start_rate) * 100
                volatility   = filtered.std()

                cx, cy = st.columns(2)
                with cx:
                    st.metric("Period Change", f"₹{change:.4f}", delta=f"{change_pct:+.2f}%")
                with cy:
                    st.metric("Volatility (Std Dev)", f"₹{volatility:.4f}")


if __name__ == "__main__":
    st.set_page_config(page_title="Currency Trends", layout="wide")
    render()