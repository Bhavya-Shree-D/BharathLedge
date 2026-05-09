# Shared constants for the forecasting pipeline.
# FEATURE_SETS is defined here and imported by train.py, evaluate.py, predict.py, and targets.py.
# If anything changes here, all files pick it up automatically.

PAIRS    = ["USDINR", "EURINR", "JPYINR"]
HORIZONS = [1, 3, 5, 10, 21]
CALENDAR = ["day_of_week", "month", "is_month_end", "is_quarter_end"]

FEATURE_SETS = {
    "USDINR": {
        "short": ["USDINR_lr_lag1", "DXY_lr_lag1", "VIX_lag1"]                      + CALENDAR,
        # USDINR long uses both 10d and 21d rolling means — 21d for multi-week
        # trend and 10d for consistency with the INR leg in EURINR/JPYINR long models.
        "long":  ["USDINR_roll_mean_21", "USDINR_roll_mean_10", "DXY_roll_mean_10"]  + CALENDAR,
    },
    "EURINR": {
        "short": ["EURUSD_lr_lag1", "USDINR_lr_lag1", "VIX_lag1"]                   + CALENDAR,
        "long":  ["EURUSD_roll_mean_10", "USDINR_roll_mean_10",
                  "EUR_US_rate_spread"]                                               + CALENDAR,
    },
    "JPYINR": {
        "short": ["USDJPY_lr_lag1", "USDINR_lr_lag1", "VIX_lag1"]                   + CALENDAR,
        "long":  ["USDJPY_roll_mean_10", "USDINR_roll_mean_10",
                  "VIX_zscore_60d"]                                                   + CALENDAR,
    },
}

# Fixed test set boundary — defined once here so evaluate.py always uses
# the same date regardless of how many new rows daily updates have added.
TEST_START_DATE = "2023-06-12"  # string — pd.Timestamp parses this directly


def get_feature_set(pair: str, horizon: int) -> list:
    if pair not in FEATURE_SETS:
        raise ValueError(
            f"Unknown pair '{pair}'. Must be one of {list(FEATURE_SETS)}."
        )
    if horizon not in HORIZONS:
        raise ValueError(
            f"Unknown horizon {horizon}. Must be one of {HORIZONS}."
        )
    group = "short" if horizon in [1, 3, 5] else "long"
    # Return a copy — prevents callers from accidentally mutating the constant.
    return list(FEATURE_SETS[pair][group])