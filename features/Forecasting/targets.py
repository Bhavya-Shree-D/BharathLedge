# Stage 4 — Target engineering: computes forward log returns for USDINR, EURINR,
# and JPYINR across 5 horizons and saves them to data/processed/targets.parquet.

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from features.Forecasting.constants import PAIRS, HORIZONS

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
ALIGNED_PATH  = PROCESSED_DIR / "aligned.parquet"
TARGETS_PATH  = PROCESSED_DIR / "targets.parquet"

MIN_ROWS_REQUIRED = max(HORIZONS) + 1   # need at least horizon+1 rows to compute any target


def _forward_log_return(prices: pd.Series, horizon: int) -> pd.Series:
    # log(close[t+N] / close[t]) — shift(-N) brings the future price to row t.
    # Last N rows will be NaN — no future data exists for them.
    # Not dropped here; train.py drops per model so shorter horizons
    # don't lose rows that are valid for them.
    fwd = np.log(prices.shift(-horizon) / prices)
    if len(fwd) > horizon and not np.isfinite(fwd.iloc[:-horizon]).all():
        bad = fwd.iloc[:-horizon][~np.isfinite(fwd.iloc[:-horizon])]
        raise ValueError(
            f"Non-finite return in '{prices.name}' at horizon {horizon}d "
            f"({len(bad)} row(s)). Check for zero/negative prices."
        )
    return fwd


def build_targets(aligned: pd.DataFrame) -> pd.DataFrame:
    if len(aligned) < MIN_ROWS_REQUIRED:
        raise ValueError(
            f"aligned has only {len(aligned)} rows — need at least {MIN_ROWS_REQUIRED} "
            f"to compute {max(HORIZONS)}d forward returns."
        )

    if not aligned.index.is_monotonic_increasing:
        raise ValueError(
            "aligned DataFrame index is not sorted. "
            "shift(-N) operates positionally — an unsorted index produces wrong targets."
        )

    missing = [p for p in PAIRS if p not in aligned.columns]
    if missing:
        raise ValueError(
            f"Pairs missing from aligned.parquet: {missing}. "
            "Check yfinance.parquet — tickers may have changed."
        )

    targets = pd.DataFrame(index=aligned.index)

    for pair in PAIRS:
        for h in HORIZONS:
            col = f"{pair}_{h}d"
            targets[col] = _forward_log_return(aligned[pair], h)
            nan_count = targets[col].isna().sum()
            if nan_count > h:
                log.warning(
                    "%s has %d NaN rows but expected %d — "
                    "possible mid-series gap in aligned.parquet.",
                    col, nan_count, h,
                )
            else:
                log.info("%-15s | %d NaN rows (expected %d)", col, nan_count, h)

    broken = [c for c in targets.columns if targets[c].isna().all()]
    if broken:
        log.warning("Entirely NaN targets — pair missing in aligned data: %s", broken)

    return targets


def run_target_engineering() -> pd.DataFrame:
    log.info("=== Target engineering started ===")

    if not ALIGNED_PATH.exists():
        raise FileNotFoundError(
            "aligned.parquet not found. Run align.py before targets.py."
        )

    aligned = pd.read_parquet(ALIGNED_PATH, engine="pyarrow")

    if aligned.empty:
        raise ValueError("aligned.parquet is empty. Re-run ingest.py and align.py.")

    targets = build_targets(aligned)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    targets.to_parquet(TARGETS_PATH, engine="pyarrow", compression="snappy")
    log.info("Saved targets.parquet — %d rows x %d cols", len(targets), len(targets.columns))

    log.info("=== Target engineering complete ===")
    return targets


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_target_engineering()