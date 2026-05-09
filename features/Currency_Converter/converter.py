import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)


class CurrencyConverter:
    SUPPORTED_CURRENCIES = {"USD", "EUR", "JPY"}
    PAYMENT_METHODS = {"Bank", "Forex Card", "Debit Card", "Credit Card"}

    VALID_TCS_RATES = {Decimal("0"), Decimal("0.5"), Decimal("5"), Decimal("20")}

    TYPICAL_MARGINS = {
        "Credit Card": Decimal("3.5"),
        "Debit Card": Decimal("2.5"),
        "Forex Card": Decimal("1.0"),
        "Bank": Decimal("1.8"),
    }

    GST_RATE = Decimal("0.18")

    def __init__(self, api_key: Optional[str] = None, charge_gst_on_margin: bool = False):
        self.api_key = api_key
        self.charge_gst_on_margin = charge_gst_on_margin
        self.cache: dict[str, tuple[Decimal, float]] = {}
        self.cache_ttl = 300  # seconds

    def _get_live_rate(self, currency: str) -> Decimal:
        """Return INR per 1 foreign unit."""
        key = f"INR_{currency}"
        now = datetime.now().timestamp()

        # cache
        if key in self.cache:
            rate, ts = self.cache[key]
            if now - ts < self.cache_ttl:
                return rate

        # API
        try:
            if self.api_key:
                url = f"https://v6.exchangerate-api.com/v6/{self.api_key}/latest/INR"
                resp = requests.get(url, timeout=6)
                resp.raise_for_status()
                data = resp.json()

                if data.get("result") == "success":
                    raw = data.get("conversion_rates", {}).get(currency)
                    if raw is None:
                        raise KeyError(f"Missing conversion_rates[{currency}]")

                    # API gives foreign per 1 INR -> invert to INR per 1 foreign
                    per_inr = Decimal(str(raw))
                    if per_inr <= 0:
                        raise ValueError(f"Non-positive rate for {currency}: {per_inr}")

                    rate = Decimal("1") / per_inr
                    self.cache[key] = (rate, now)
                    return rate

        except Exception as e:
            logger.warning(f"Live rate fetch failed for {currency}: {e}")

        # fallback
        fallback = {
            "USD": Decimal("83.48"),
            "EUR": Decimal("89.32"),
            "JPY": Decimal("0.547"),
        }
        rate = fallback.get(currency, Decimal("83.0"))
        logger.info(f"Using fallback rate {currency}: {rate}")
        return rate

    def convert(self, request: Dict) -> Dict:
        if not isinstance(request, dict) or not request:
            return {"success": False, "error": "Invalid payload (expected a non-empty dict)"}
        required = {"amount_inr", "target_currency", "conversion_method"}
        missing = required - request.keys()
        if missing:
            return {"success": False, "error": f"Missing fields: {', '.join(sorted(missing))}"}

        # amount
        try:
            amount_inr = Decimal(str(request["amount_inr"]))
        except (InvalidOperation, TypeError):
            return {"success": False, "error": "amount_inr must be a valid number"}
        if amount_inr <= 0:
            return {"success": False, "error": "amount_inr must be positive"}

        target = request["target_currency"]
        method = request["conversion_method"]

        if target not in self.SUPPORTED_CURRENCIES:
            return {"success": False, "error": f"Unsupported currency: {target}"}
        if method not in self.PAYMENT_METHODS:
            return {"success": False, "error": f"Unsupported method: {method}"}

        # optional inputs
        user_margin = request.get("bank_margin_pct")
        user_tcs = request.get("tcs_percent")
        user_card_fee = request.get("card_fee_inr")

        # margin %
        if user_margin is not None:
            try:
                margin_pct = Decimal(str(user_margin))
            except (InvalidOperation, TypeError):
                return {"success": False, "error": "bank_margin_pct must be numeric"}
            if margin_pct < 0 or margin_pct > 20:
                return {"success": False, "error": "bank_margin_pct must be 0–20"}
        else:
            margin_pct = self.TYPICAL_MARGINS.get(method, Decimal("1.5"))

        # tcs %
        if user_tcs is not None:
            try:
                tcs_pct = Decimal(str(user_tcs))
            except (InvalidOperation, TypeError):
                return {"success": False, "error": "tcs_percent must be numeric"}
            if tcs_pct not in self.VALID_TCS_RATES:
                allowed = sorted(self.VALID_TCS_RATES)
                return {"success": False, "error": f"tcs_percent must be one of {allowed}"}
        else:
            tcs_pct = Decimal("0")

        # card fee
        if user_card_fee is not None:
            try:
                card_fee_inr = Decimal(str(user_card_fee))
            except (InvalidOperation, TypeError):
                return {"success": False, "error": "card_fee_inr must be numeric"}
            if card_fee_inr < 0:
                return {"success": False, "error": "card_fee_inr must be >= 0"}
        else:
            card_fee_inr = Decimal("0")

        # rates
        interbank_rate = self._get_live_rate(target)
        if interbank_rate <= 0:
            return {"success": False, "error": "Invalid exchange rate"}

        m = margin_pct / Decimal("100")
        customer_rate = interbank_rate * (Decimal("1") + m)

        # FX received (economic, unrounded)
        foreign_raw = amount_inr / customer_rate

        # display rounding
        if target == "JPY":
            foreign_final = foreign_raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        else:
            foreign_final = foreign_raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        if foreign_final <= 0:
            return {"success": False, "error": "amount_inr too small; rounds to 0 in target currency"}

        # charges
        tcs_inr = (amount_inr * tcs_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        implied_margin_inr = (amount_inr - (foreign_raw * interbank_rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        gst_on_margin = Decimal("0.00")
        if self.charge_gst_on_margin and implied_margin_inr > 0:
            gst_on_margin = (implied_margin_inr * self.GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        total_extra = (tcs_inr + card_fee_inr + gst_on_margin).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_debited = (amount_inr + total_extra).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if foreign_raw <= 0:
            return {"success": False, "error": "Invalid conversion amount"}
        # effective rate should use foreign_raw (not rounded foreign_final)
        effective_rate = (total_debited / foreign_raw).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        # output quantization (UI stable)
        amount_inr_q = amount_inr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        card_fee_q = card_fee_inr.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        user_custom = (user_margin is not None) or (user_tcs is not None) or (user_card_fee is not None)
        disclaimer = (
            "Calculation based on the values you provided. Actual charges may vary by bank/service provider."
            if user_custom
            else f"Using typical {method} margins ({margin_pct}%). Charges are added on top. Real charges vary."
        )

        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "input": {
                "amount_inr": float(amount_inr_q),
                "target_currency": target,
                "payment_method": method,
            },
            "result": {
                "you_receive": {"amount": float(foreign_final), "currency": target},
                "you_pay": {"total_inr": float(total_debited), "currency": "INR"},
            },
            "rates": {
                "interbank_rate": float(interbank_rate.quantize(Decimal("0.0001"))),
                "margin_percent": float(margin_pct),
                "customer_rate": float(customer_rate.quantize(Decimal("0.0001"))),
                "effective_rate": float(effective_rate),
            },
            "charges_breakdown_inr": {
                "base_amount": float(amount_inr_q),
                "bank_margin": float(implied_margin_inr),
                "gst_on_margin_18_percent": float(gst_on_margin),
                "tcs": float(tcs_inr),
                "card_service_fee": float(card_fee_q),
                "total_additional_charges": float(total_extra),
            },
            "important_notes": {
                "margin_application": "Bank margin is built into the exchange rate (you receive fewer foreign units).",
                "tcs": "TCS is collected separately and can be claimed/adjusted in ITR.",
                "gst_on_margin": "GST on margin is optional – most banks do NOT charge it separately.",
                "total_cost": f"You pay ₹{float(total_debited)} to receive {float(foreign_final)} {target}",
            },
            "disclaimer": disclaimer,
        }
