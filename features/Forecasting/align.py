# Stage 2 — Alignment: merges raw yfinance and FRED data onto a single
# intersection index where every series has a valid, fresh value.

import logging
from pathlib import Path
from typing import Tuple

import pandas as pd

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
RAW_DIR       = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

YFINANCE_PATH = RAW_DIR / "yfinance.parquet"
FRED_PATH     = RAW_DIR / "fred.parquet"
ALIGNED_PATH  = PROCESSED_DIR / "aligned.parquet"

DE10Y_FFILL_LIMIT = 23
US10Y_FFILL_LIMIT = 3
MIN_TRADING_DAYS_PER_YEAR = 220


def load_raw() -> Tuple[pd.DataFrame, pd.DataFrame]:
    if not YFINANCE_PATH.exists() or not FRED_PATH.exists():
        raise FileNotFoundError(
            "Raw parquet files missing. Run ingest.py full before align.py."
        )
    yf   = pd.read_parquet(YFINANCE_PATH, engine="pyarrow")
    fred = pd.read_parquet(FRED_PATH,     engine="pyarrow")

    if yf.empty:
        raise ValueError("yfinance.parquet is empty. Re-run ingest.py.")
    if fred.empty:
        raise ValueError("fred.parquet is empty. Re-run ingest.py.")

    return yf, fred


def build_aligned(yf: pd.DataFrame, fred: pd.DataFrame) -> pd.DataFrame:
    required_fred_cols = ["US10Y", "DE10Y"]
    missing = [c for c in required_fred_cols if c not in fred.columns]
    if missing:
        raise ValueError(
            f"fred.parquet is missing columns: {missing}. Re-run ingest.py."
        )

    fred = fred.copy()
    fred["DE10Y"] = fred["DE10Y"].ffill(limit=DE10Y_FFILL_LIMIT)
    fred["US10Y"] = fred["US10Y"].ffill(limit=US10Y_FFILL_LIMIT)

    yf   = yf.sort_index()
    fred = fred.sort_index()

    merged      = pd.concat([yf, fred], axis=1)
    rows_before = len(merged)
    aligned     = merged.dropna(how="any")
    rows_dropped = rows_before - len(aligned)

    if rows_dropped > 0:
        log.info(
            "dropna removed %d rows (%.1f%%) — calendar mismatches between sources.",
            rows_dropped, 100 * rows_dropped / rows_before,
        )

    aligned = aligned.sort_index()
    return aligned


def validate(aligned: pd.DataFrame) -> None:
    dupes = aligned.index.duplicated().sum()
    if dupes > 0:
        raise ValueError(
            f"Aligned dataset has {dupes} duplicate date(s) in the index. "
            "Re-run ingest.py — one of the raw parquet files has duplicate rows."
        )

    n_years      = (aligned.index[-1] - aligned.index[0]).days / 365.25
    expected_min = int(n_years * MIN_TRADING_DAYS_PER_YEAR)

    if len(aligned) < expected_min:
        log.warning(
            "Aligned dataset has only %d rows over %.1f years — "
            "expected at least %d. One source series likely has large gaps.",
            len(aligned), n_years, expected_min,
        )
    else:
        log.info(
            "Aligned dataset: %d rows | %.1f years | %d columns",
            len(aligned), n_years, len(aligned.columns),
        )


def run_alignment() -> pd.DataFrame:
    log.info("=== Alignment started ===")

    yf, fred = load_raw()
    aligned  = build_aligned(yf, fred)

    if aligned.empty:
        raise ValueError(
            "Alignment produced an empty DataFrame — every date was dropped. "
            "Check yfinance.parquet and fred.parquet for large gaps."
        )

    validate(aligned)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    aligned.to_parquet(ALIGNED_PATH, engine="pyarrow", compression="snappy")
    log.info("Saved aligned.parquet — %d rows x %d cols", len(aligned), len(aligned.columns))

    log.info("=== Alignment complete ===")
    return aligned


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_alignment()