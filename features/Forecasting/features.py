# Stage 3 — Feature engineering: computes all model inputs from the aligned
# price data and saves the result to data/processed/features.parquet.

import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ALIGNED_PATH  = PROCESSED_DIR / "aligned.parquet"
FEATURES_PATH = PROCESSED_DIR / "features.parquet"

REQUIRED_COLS = ["USDINR", "DXY", "EURUSD", "USDJPY", "VIX", "US10Y", "DE10Y"]

# VIX_zscore_60d needs 60 rows + 1 shift = 61 warm-up rows.
# Anything dropped beyond 65 suggests a mid-series gap upstream.
EXPECTED_WARMUP  = 61
WARMUP_TOLERANCE = 4


def _log_return(series: pd.Series) -> pd.Series:
    lr = np.log(series / series.shift(1)).shift(1)
    # isfinite rejects both inf (log of zero) and nan (log of negative price).
    if not np.isfinite(lr.iloc[2:]).all():
        bad = lr.iloc[2:][~np.isfinite(lr.iloc[2:])]
        raise ValueError(
            f"Non-finite log return in '{series.name}' at {len(bad)} row(s). "
            "Check for zero or negative prices in aligned.parquet."
        )
    return lr


def _roll_mean(series: pd.Series, window: int) -> pd.Series:
    # min_periods=window rejects partial windows — no misleading early-row values.
    return series.rolling(window=window, min_periods=window).mean().shift(1)


def _vix_zscore(vix: pd.Series, window: int = 60) -> pd.Series:
    roll = vix.rolling(window=window, min_periods=window)
    return ((vix - roll.mean()) / roll.std()).shift(1)


def _last_trading_day_of_period(index: pd.DatetimeIndex, freq: str) -> pd.Series:
    # pandas is_month_end marks the last calendar day — usually a weekend,
    # absent from a trading-day index. resample().last() finds the last date
    # actually observed per period instead.
    s        = pd.Series(index, index=index)
    last_set = set(s.resample(freq).last().values)
    return pd.Series([int(d in last_set) for d in index], index=index, dtype="int8")


def build_features(aligned: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLS if c not in aligned.columns]
    if missing:
        raise ValueError(
            f"aligned.parquet is missing columns: {missing}. "
            "Re-run ingest.py and align.py."
        )

    feat = pd.DataFrame(index=aligned.index)

    feat["USDINR_lr_lag1"] = _log_return(aligned["USDINR"])
    feat["DXY_lr_lag1"]    = _log_return(aligned["DXY"])
    feat["EURUSD_lr_lag1"] = _log_return(aligned["EURUSD"])
    feat["USDJPY_lr_lag1"] = _log_return(aligned["USDJPY"])

    # VIX level not return — absolute level captures risk-off severity.
    feat["VIX_lag1"] = aligned["VIX"].shift(1)

    feat["USDINR_roll_mean_21"] = _roll_mean(aligned["USDINR"], 21)
    feat["USDINR_roll_mean_10"] = _roll_mean(aligned["USDINR"], 10)
    feat["DXY_roll_mean_10"]    = _roll_mean(aligned["DXY"],    10)
    feat["EURUSD_roll_mean_10"] = _roll_mean(aligned["EURUSD"], 10)
    feat["USDJPY_roll_mean_10"] = _roll_mean(aligned["USDJPY"], 10)

    feat["VIX_zscore_60d"] = _vix_zscore(aligned["VIX"], window=60)

    # US10Y minus DE10Y as EUR/USD rate differential for the EURINR long model.
    # India 10Y is not available at daily frequency from free sources.
    feat["EUR_US_rate_spread"] = (aligned["US10Y"] - aligned["DE10Y"]).shift(1)

    # Calendar features are knowable at market open — no shift needed.
    feat["day_of_week"]    = aligned.index.dayofweek
    feat["month"]          = aligned.index.month
    feat["is_month_end"]   = _last_trading_day_of_period(aligned.index, "ME")
    feat["is_quarter_end"] = _last_trading_day_of_period(aligned.index, "QE")

    broken = [c for c in feat.columns if feat[c].isna().all()]
    if broken:
        log.warning("Entirely NaN columns — upstream data broken for: %s", broken)

    before  = len(feat)
    feat    = feat.dropna(how="any")
    dropped = before - len(feat)

    if dropped > EXPECTED_WARMUP + WARMUP_TOLERANCE:
        log.warning(
            "Dropped %d rows — expected ~%d. "
            "Possible mid-series NaN in aligned.parquet.",
            dropped, EXPECTED_WARMUP,
        )
    else:
        log.info("Dropped %d warm-up rows. %d rows remain.", dropped, len(feat))

    return feat


def run_feature_engineering() -> pd.DataFrame:
    log.info("=== Feature engineering started ===")

    if not ALIGNED_PATH.exists():
        raise FileNotFoundError(
            "aligned.parquet not found. Run align.py before features.py."
        )

    aligned = pd.read_parquet(ALIGNED_PATH, engine="pyarrow")

    if aligned.empty:
        raise ValueError("aligned.parquet is empty. Re-run ingest.py and align.py.")

    feat = build_features(aligned)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    feat.to_parquet(FEATURES_PATH, engine="pyarrow", compression="snappy")
    log.info("Saved features.parquet — %d rows x %d cols", len(feat), len(feat.columns))

    log.info("=== Feature engineering complete ===")
    return feat


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_feature_engineering()