#currency converter app.py 
import os
import streamlit as st
from typing import Dict
from dotenv import load_dotenv
from decimal import Decimal

from .converter import CurrencyConverter
from features.Multilingual.translator import t

load_dotenv()

converter_instance = CurrencyConverter(
    api_key=os.getenv("EXCHANGE_RATE_API_KEY"),
    charge_gst_on_margin=False
)


def run_currency_conversion(payload: Dict) -> Dict:
    """Legacy API function for backward compatibility"""
    if not isinstance(payload, dict) or not payload:
        return {"success": False, "error": "Invalid payload (expected a non-empty dict)"}
    return converter_instance.convert(payload)


def render(db=None, T=None):
    """Main render function for Currency Calculator Streamlit UI"""
    st.subheader(f"💱 {t('Currency Calculator')}")

    # --- UI FIX: force readable text for metrics + expander headers ---
    theme_base = st.get_option("theme.base") or "light"
    fg = "#111111" if theme_base == "light" else "#f5f5f5"
    bg_open = "rgba(0,0,0,0.06)" if theme_base == "light" else "rgba(255,255,255,0.08)"

    st.markdown(
        f"""
        <style>
        [data-testid="stMetricLabel"] {{ color: {fg} !important; }}
        [data-testid="stMetricValue"] {{ color: {fg} !important; }}
        [data-testid="stExpander"] summary {{ color: {fg} !important; }}
        [data-testid="stExpander"] summary p {{ color: {fg} !important; }}
        [data-testid="stExpander"] summary svg {{ fill: {fg} !important; }}
        [data-testid="stExpander"] details[open] > summary {{
          background: {bg_open} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f"### {t('Conversion Details')}")

    col1, col2, col3 = st.columns(3)

    with col1:
        amount_inr = st.number_input(
            t("Amount in INR:"),
            min_value=0.0,
            value=10000.0,
            step=100.0,
            key="cc_amount_inr"
        )

    with col2:
        target_currency = st.selectbox(
            t("Target Currency:"),
            options=["USD", "EUR", "JPY"],
            key="cc_target"
        )

    with col3:
        # Internal English values + translated display labels
        method_options = ["Bank", "Forex Card", "Debit Card", "Credit Card"]
        conversion_method = st.selectbox(
            t("Payment Method:"),
            options=method_options,
            format_func=lambda x: t(x),
            key="cc_method"
        )

    st.markdown("---")
    st.markdown(f"### {t('Optional Charges (Leave unchecked to use typical values)')}")

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        use_margin = st.checkbox(
            t("Custom Bank Margin (%)"),
            value=False,
            key="cc_use_margin"
        )
        bank_margin_pct = None
        if use_margin:
            bank_margin_pct = st.number_input(
                t("Bank Margin (%):"),
                min_value=0.0,
                max_value=20.0,
                value=1.8,
                step=0.1,
                key="cc_margin"
            )

    with col_b:
        use_tcs = st.checkbox(
            t("Add TCS"),
            value=False,
            key="cc_use_tcs"
        )
        tcs_percent = None
        if use_tcs:
            tcs_percent = st.selectbox(
                t("TCS (%):"),
                options=[0, 0.5, 5, 20],
                index=0,
                key="cc_tcs"
            )

    with col_c:
        use_fee = st.checkbox(
            t("Card/Service Fee"),
            value=False,
            key="cc_use_fee"
        )
        card_fee_inr = None
        if use_fee:
            card_fee_inr = st.number_input(
                t("Card/Service Fee (INR):"),
                min_value=0.0,
                value=0.0,
                step=10.0,
                key="cc_fee"
            )

    charge_gst_on_margin = st.checkbox(
        t("Charge GST (18%) on Bank Margin (most banks don't charge this separately)"),
        value=False,
        key="cc_gst_toggle"
    )
    st.markdown("---")

    if st.button(
        f"💰 {t('Calculate Conversion')}",
        key="calc_btn",
        type="primary",
        use_container_width=True,
    ):
        if amount_inr <= 0:
            st.error(t("Amount must be greater than 0"))
            return

        # Create converter instance with current GST setting
        converter = CurrencyConverter(
            api_key=os.getenv("EXCHANGE_RATE_API_KEY"),
            charge_gst_on_margin=charge_gst_on_margin
        )

        # Build payload (English values internally — never translated)
        payload = {
            "amount_inr": amount_inr,
            "target_currency": target_currency,
            "conversion_method": conversion_method,
        }
        if bank_margin_pct is not None:
            payload["bank_margin_pct"] = bank_margin_pct
        if tcs_percent is not None:
            payload["tcs_percent"] = tcs_percent
        if card_fee_inr is not None:
            payload["card_fee_inr"] = card_fee_inr

        # Convert
        result = converter.convert(payload)

        if not result.get("success"):
            st.error(f"❌ {t(result.get('error', 'Conversion failed'))}")
            return

        # Display results
        st.success(f"✅ {t('Conversion Successful')}")

        # Main result cards
        col_result1, col_result2 = st.columns(2)

        with col_result1:
            st.markdown(f"#### 💵 {t('You Receive')}")
            receive_amount = result["result"]["you_receive"]["amount"]
            receive_currency = result["result"]["you_receive"]["currency"]
            st.markdown(f"### **{receive_amount:,.2f} {receive_currency}**")

        with col_result2:
            st.markdown(f"#### 💳 {t('You Pay')}")
            pay_amount = result["result"]["you_pay"]["total_inr"]
            st.markdown(f"### **₹{pay_amount:,.2f}**")

        st.markdown("---")

        # Exchange rates
        with st.expander(f"📊 {t('Exchange Rates')}", expanded=True):
            rates = result["rates"]

            col_r1, col_r2, col_r3, col_r4 = st.columns(4)

            with col_r1:
                st.metric(t("Interbank Rate"), f"₹{rates['interbank_rate']:.4f}")
            with col_r2:
                st.metric(t("Margin"), f"{rates['margin_percent']:.2f}%")
            with col_r3:
                st.metric(t("Customer Rate"), f"₹{rates['customer_rate']:.4f}")
            with col_r4:
                st.metric(t("Effective Rate"), f"₹{rates['effective_rate']:.4f}")

        # Charges breakdown
        with st.expander(f"💰 {t('Charges Breakdown')}"):
            charges = result["charges_breakdown_inr"]
            st.markdown(f"""
            - **{t('Base Amount')}:** ₹{charges['base_amount']:,.2f}
            - **{t('Bank Margin')}:** ₹{charges['bank_margin']:,.2f}
            - **{t('GST on Margin (18%)')}:** ₹{charges['gst_on_margin_18_percent']:,.2f}
            - **{t('TCS')}:** ₹{charges['tcs']:,.2f}
            - **{t('Card/Service Fee')}:** ₹{charges['card_service_fee']:,.2f}
            - **{t('Total Additional Charges')}:** ₹{charges['total_additional_charges']:,.2f}
            """)

        # Important notes
        with st.expander(f"ℹ️ {t('Important Information')}"):
            notes = result["important_notes"]
            st.info(f"**{t('Margin Application')}:** {t(notes['margin_application'])}")
            st.info(f"**{t('TCS')}:** {t(notes['tcs'])}")
            st.info(f"**{t('GST on Margin')}:** {t(notes['gst_on_margin'])}")
            st.info(f"**{t('Summary')}:** {t(notes['total_cost'])}")

        # Disclaimer
        st.caption(f"⚠️ {t(result['disclaimer'])}")

        # Log to database (action stored in English, translated at display time)
        if db:
            try:
                user_email = st.session_state.get('user_email', 'unknown')
                db.add_history(
                    user_email,
                    "Calculator",
                    f"Converted ₹{amount_inr} to {target_currency} via {conversion_method}"
                )
            except Exception:
                pass


if __name__ == "__main__":
    st.set_page_config(page_title="Currency Calculator", layout="wide")
    render()