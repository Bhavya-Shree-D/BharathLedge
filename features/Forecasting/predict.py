# Stage 8 — Prediction: loads the latest feature row, runs all 15 trained
# models, and returns predicted prices for each pair x horizon combination.

import logging
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from features.Forecasting.constants import PAIRS, HORIZONS, get_feature_set

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODELS_DIR    = PROJECT_ROOT / "models"

FEATURES_PATH = PROCESSED_DIR / "features.parquet"
ALIGNED_PATH  = PROCESSED_DIR / "aligned.parquet"


def _load_latest_feature_row(features: pd.DataFrame) -> pd.Series:
    if features.empty:
        raise ValueError(
            "features.parquet is empty. Run the full pipeline before predict.py."
        )

    row = features.iloc[-1]

    if row.isna().any():
        bad = row[row.isna()].index.tolist()
        raise ValueError(
            f"Latest feature row ({row.name.date()}) has NaN in: {bad}. "
            "Run features.py to regenerate features before predicting."
        )

    return row


def _get_current_price(aligned: pd.DataFrame, pair: str, as_of: pd.Timestamp) -> float:
    if pair not in aligned.columns:
        raise ValueError(
            f"Pair '{pair}' not found in aligned.parquet. "
            "Check ingest.py — the column may have been renamed."
        )

    available = aligned.loc[aligned.index <= as_of, pair].dropna()

    if available.empty:
        raise ValueError(
            f"No valid price found for '{pair}' on or before {as_of.date()}. "
            "Re-run ingest.py and align.py."
        )

    return float(available.iloc[-1])


def run_predict(as_of: str | None = None) -> pd.DataFrame:
    """Run predictions for all 15 models against the latest available feature row.

    Parameters
    ----------
    as_of : str or None
        ISO date string (e.g. '2026-05-01') to predict from.
        Defaults to the latest row in features.parquet.

    Returns
    -------
    pd.DataFrame with columns:
        pair, horizon_days, as_of_date, target_date,
        current_price, predicted_log_return, predicted_price

    Note: cache this function at the Streamlit layer with
    @st.cache_data(ttl=3600) to avoid repeated disk and model reads on reruns.
    """
    log.info("=== Prediction started ===")

    for path in [FEATURES_PATH, ALIGNED_PATH]:
        if not path.exists():
            raise FileNotFoundError(
                f"{path.name} not found. Run the full pipeline before predict.py."
            )

    if not MODELS_DIR.exists() or not any(MODELS_DIR.glob("*.pkl")):
        raise FileNotFoundError(
            "No model pkl files found in models/. Run train.py before predict.py."
        )

    features = pd.read_parquet(FEATURES_PATH, engine="pyarrow")
    aligned  = pd.read_parquet(ALIGNED_PATH,  engine="pyarrow")

    if not features.index.is_monotonic_increasing:
        raise ValueError(
            "features.parquet index is not sorted. Re-run features.py."
        )

    if as_of is not None:
        as_of_ts = pd.Timestamp(as_of)
        if as_of_ts not in features.index:
            available = features.index[features.index <= as_of_ts]
            if available.empty:
                raise ValueError(
                    f"No feature row available on or before {as_of}. "
                    f"Earliest available: {features.index[0].date()}"
                )
            as_of_ts = available[-1]
            log.warning(
                "Requested date %s not in features index — using closest prior date %s.",
                as_of, as_of_ts.date(),
            )
        feature_row = features.loc[as_of_ts]
    else:
        feature_row = _load_latest_feature_row(features)
        as_of_ts    = feature_row.name

    log.info("Predicting from feature row: %s", as_of_ts.date())

    # Validate all feature columns exist before loading any model from disk.
    # Fails fast — avoids loading 15 pkl files only to raise on a missing column.
    for pair in PAIRS:
        for h in HORIZONS:
            missing = [f for f in get_feature_set(pair, h) if f not in feature_row.index]
            if missing:
                raise ValueError(
                    f"Feature row is missing columns for {pair}_{h}d: {missing}. "
                    "Re-run features.py."
                )

    # Load all models once before the prediction loop.
    models: dict[str, object] = {}
    for pair in PAIRS:
        for h in HORIZONS:
            model_path = MODELS_DIR / f"{pair}_{h}d.pkl"
            if model_path.exists():
                models[f"{pair}_{h}d"] = joblib.load(model_path)
            else:
                log.warning("Model not found: %s — skipping.", model_path.name)

    if not models:
        raise RuntimeError(
            "No models were loaded. Run train.py before predict.py."
        )

    # Compute future trading dates once — constant across all iterations.
    future_dates = aligned.index[aligned.index > as_of_ts]

    results = []

    for pair in PAIRS:
        current_price = _get_current_price(aligned, pair, as_of_ts)

        for h in HORIZONS:
            key   = f"{pair}_{h}d"
            model = models.get(key)

            if model is None:
                continue

            feature_cols = get_feature_set(pair, h)
            X_df = pd.DataFrame([feature_row[feature_cols]])

            predicted_log_ret = float(model.predict(X_df)[0])
            predicted_price   = current_price * np.exp(predicted_log_ret)

            target_date = future_dates[h - 1] if len(future_dates) >= h else None

            results.append({
                "pair":                 pair,
                "horizon_days":         h,
                "as_of_date":           as_of_ts.date(),
                "target_date":          target_date.date() if target_date is not None else None,
                "current_price":        round(current_price,     4),
                "predicted_log_return": round(predicted_log_ret, 6),
                "predicted_price":      round(predicted_price,   4),
            })

            log.info(
                "%-8s %2dd | current: %.4f | pred log ret: %+.6f | pred price: %.4f",
                pair, h, current_price, predicted_log_ret, predicted_price,
            )

    if not results:
        raise RuntimeError(
            "No predictions were produced. "
            "Check that models/ has pkl files and features.parquet is populated."
        )

    df = pd.DataFrame(results)
    log.info("=== Prediction complete — %d predictions ===", len(df))
    return df


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    as_of_arg   = sys.argv[1] if len(sys.argv) > 1 else None
    predictions = run_predict(as_of=as_of_arg)
    print("\n" + predictions.to_string(index=False))