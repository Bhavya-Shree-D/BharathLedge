# Stage 5+6 — Model training: joins features and targets, trains 15 LightGBM
# models (3 pairs x 5 horizons) and saves them to models/ as pkl files.

import logging
from pathlib import Path

import joblib
import lightgbm as lgb
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from features.Forecasting.constants import PAIRS, HORIZONS, get_feature_set

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODELS_DIR    = PROJECT_ROOT / "models"

FEATURES_PATH = PROCESSED_DIR / "features.parquet"
TARGETS_PATH  = PROCESSED_DIR / "targets.parquet"

LGB_PARAMS = {
    "objective":        "regression_l1",
    "num_leaves":       20,
    "min_data_in_leaf": 20,
    "learning_rate":    0.03,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq":     5,
    "verbosity":        -1,
    "n_jobs":           -1,
}

N_ESTIMATORS      = 500   # higher ceiling — early stopping keeps actual count optimal
N_SPLITS          = 5
EARLY_STOPPING    = 30    # stop if no improvement for 30 rounds


def _train_single(X: pd.DataFrame, y: pd.Series, horizon: int) -> lgb.LGBMRegressor:
    tscv = TimeSeriesSplit(n_splits=N_SPLITS, gap=horizon)

    fold_maes  = []
    best_iters = []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X.iloc[train_idx], X.iloc[val_idx]
        y_tr, y_val = y.iloc[train_idx], y.iloc[val_idx]

        # Separate model per fold so best_iteration_ is isolated per fold.
        fold_model = lgb.LGBMRegressor(**LGB_PARAMS, n_estimators=N_ESTIMATORS)
        fold_model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            callbacks=[
                lgb.early_stopping(EARLY_STOPPING, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
        mae = (y_val - fold_model.predict(X_val)).abs().mean()
        fold_maes.append(mae)
        best_iters.append(fold_model.best_iteration_)
        log.info("  fold %d | val MAE: %.6f | best iter: %d", fold + 1, mae, fold_model.best_iteration_)

    log.info("  mean OOS MAE: %.6f", sum(fold_maes) / len(fold_maes))

    # Final model trained on all data using mean best_iteration from CV folds.
    # No eval_set here — early stopping is not needed since iteration count is fixed.
    valid_iters    = [b for b in best_iters if b > 1]
    mean_best_iter = max(10, round(sum(valid_iters) / len(valid_iters))) if valid_iters else 10
    log.info("  mean best iteration across folds: %d — using for final fit", mean_best_iter)

    final_model = lgb.LGBMRegressor(**LGB_PARAMS, n_estimators=mean_best_iter)
    final_model.fit(X, y, callbacks=[lgb.log_evaluation(period=-1)])
    return final_model


def run_training() -> None:
    log.info("=== Training started ===")

    if not FEATURES_PATH.exists() or not TARGETS_PATH.exists():
        raise FileNotFoundError(
            "features.parquet or targets.parquet not found. "
            "Run features.py and targets.py before train.py."
        )

    feat    = pd.read_parquet(FEATURES_PATH, engine="pyarrow")
    targets = pd.read_parquet(TARGETS_PATH,  engine="pyarrow")
    data    = feat.join(targets, how="inner")
    log.info("Joined dataset: %d rows x %d cols", len(data), len(data.columns))

    if not data.index.is_monotonic_increasing:
        raise ValueError("Joined dataset index is not sorted — cannot use TimeSeriesSplit.")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for pair in PAIRS:
        for h in HORIZONS:
            target_col = f"{pair}_{h}d"
            features   = get_feature_set(pair, h)

            missing_cols = [f for f in features if f not in data.columns]
            if missing_cols:
                raise ValueError(
                    f"Feature columns missing for {target_col}: {missing_cols}. "
                    "Re-run features.py."
                )

            subset = data[features + [target_col]].dropna()

            if len(subset) < 200:
                log.warning(
                    "%s — only %d rows after NaN drop. Model will be unreliable.",
                    target_col, len(subset),
                )

            X = subset[features]
            y = subset[target_col]

            log.info(
                "Training %s | horizon %dd | %d rows | %d features",
                pair, h, len(X), len(features),
            )

            model      = _train_single(X, y, horizon=h)
            model_path = MODELS_DIR / f"{pair}_{h}d.pkl"
            joblib.dump(model, model_path)

            if not model_path.exists():
                raise RuntimeError(
                    f"Failed to write {model_path}. "
                    "Check folder permissions — OneDrive-synced folders can lock files."
                )

            log.info("Saved %s", model_path.name)

    log.info("=== Training complete — %d models saved ===", len(PAIRS) * len(HORIZONS))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_training()