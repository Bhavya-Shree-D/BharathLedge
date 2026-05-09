# Stage 7a — Evaluation: runs each trained model on a held-out test set and
# reports MAE, directional accuracy, and IC to data/processed/evaluation.csv.

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from features.Forecasting.constants import PAIRS, HORIZONS, get_feature_set, TEST_START_DATE

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODELS_DIR    = PROJECT_ROOT / "models"

FEATURES_PATH   = PROCESSED_DIR / "features.parquet"
TARGETS_PATH    = PROCESSED_DIR / "targets.parquet"
EVALUATION_PATH = PROCESSED_DIR / "evaluation.csv"


def _directional_accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = y_true != 0
    if mask.sum() == 0:
        return float("nan")
    return float((np.sign(y_pred[mask]) == np.sign(y_true[mask])).mean())


def _ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    if np.std(y_pred) < 1e-10 or np.std(y_true) < 1e-10:
        return float("nan")
    corr, _ = spearmanr(y_true, y_pred)
    return float(corr)


def run_evaluation() -> pd.DataFrame:
    log.info("=== Evaluation started ===")

    for path in [FEATURES_PATH, TARGETS_PATH]:
        if not path.exists():
            raise FileNotFoundError(
                f"{path.name} not found. Run the full pipeline before evaluate.py."
            )

    if not MODELS_DIR.exists() or not any(MODELS_DIR.glob("*.pkl")):
        raise FileNotFoundError(
            "No model pkl files found in models/. Run train.py before evaluate.py."
        )

    feat    = pd.read_parquet(FEATURES_PATH, engine="pyarrow")
    targets = pd.read_parquet(TARGETS_PATH,  engine="pyarrow")
    data    = feat.join(targets, how="inner")

    if not data.index.is_monotonic_increasing:
        raise ValueError("Dataset index is not sorted — cannot define a temporal test split.")

    # Fixed test start from constants.py — does not shift as new rows are added daily.
    test_start = pd.Timestamp(TEST_START_DATE)
    log.info("Test set starts: %s (fixed boundary from constants.py)", test_start.date())

    results = []

    for pair in PAIRS:
        for h in HORIZONS:
            target_col = f"{pair}_{h}d"
            features   = get_feature_set(pair, h)
            model_path = MODELS_DIR / f"{pair}_{h}d.pkl"

            if not model_path.exists():
                log.warning("Model not found: %s — skipping.", model_path.name)
                continue

            model  = joblib.load(model_path)
            subset = data[features + [target_col]].dropna()
            test   = subset[subset.index >= test_start]

            if len(test) == 0:
                log.warning("%s — test set is empty after NaN drop. Skipping.", target_col)
                continue

            X_test = test[features]
            y_true = test[target_col].values
            y_pred = model.predict(X_test)

            mae    = float(np.abs(y_true - y_pred).mean())
            dir_ac = _directional_accuracy(y_true, y_pred)
            ic     = _ic(y_true, y_pred)

            if np.isnan(ic):
                log.warning("%s — IC is nan. Check model for constant predictions.", target_col)

            results.append({
                "pair":            pair,
                "horizon":         h,
                "test_rows":       len(test),
                "mae":             mae,
                "directional_acc": dir_ac,
                "ic":              ic,
            })

            log.info(
                "%-10s %2dd | MAE: %.4f | Dir acc: %.1f%% | IC: %.3f | n=%d",
                pair, h, mae, dir_ac * 100, ic, len(test),
            )

    if not results:
        raise RuntimeError(
            "No models were evaluated. Check that models/ has pkl files."
        )

    df = pd.DataFrame(results)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(EVALUATION_PATH, index=False, float_format="%.6f")
    log.info("Saved evaluation.csv — %d rows", len(df))

    below_50 = df[df["directional_acc"] < 0.50]
    if not below_50.empty:
        log.warning(
            "Models with directional accuracy below 50%% (worse than coin flip): %s",
            below_50[["pair", "horizon"]].to_dict("records"),
        )

    log.info("=== Evaluation complete ===")
    return df


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_evaluation()