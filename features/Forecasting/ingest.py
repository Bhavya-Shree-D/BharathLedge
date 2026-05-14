# Stage 1 — Raw data ingestion: fetches all FX, macro, and volatility series
# from FRED and EIA, derives INR cross rates, and saves to data/raw/ as parquet.
# Note: BRENT is NOT fetched — it is not used as a model feature.

import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values
from fredapi import Fred

log = logging.getLogger(__name__)

PROJECT_ROOT  = Path(__file__).resolve().parents[2]
RAW_DIR       = PROJECT_ROOT / "data" / "raw"

PRICES_PATH = RAW_DIR / "yfinance.parquet"
FRED_PATH   = RAW_DIR / "fred.parquet"

# DEXJPUS is JPY per USD — JPYINR is derived after fetching.
# DEXINUS is INR per USD. DEXUSEU is USD per EUR.
FRED_PRICE_SERIES = {
    "DEXINUS":  "USDINR",
    "DEXUSEU":  "EURUSD",
    "DEXJPUS":  "USDJPY",
    "DTWEXBGS": "DXY",
    "VIXCLS":   "VIX",
}

# IRLTLT01DEM156N is monthly — align.py forward-fills it.
FRED_MACRO_SERIES = {
    "DGS10":           "US10Y",
    "IRLTLT01DEM156N": "DE10Y",
}

# Series that are published monthly and may return empty for short lookback windows.
MONTHLY_SERIES = {"IRLTLT01DEM156N"}

HISTORY_START        = "2012-01-01"
UPDATE_LOOKBACK_DAYS = 40
MONTHLY_LOOKBACK_DAYS = 120   # monthly series have publication lag of up to 3 months
FRED_MAX_RETRIES     = 3
FRED_RETRY_DELAY     = 5


def _load_env() -> dict:
    # In GitHub Actions, secrets are injected as env vars directly.
    if os.environ.get("FRED_API_KEY"):
        return {"FRED_API_KEY": os.environ["FRED_API_KEY"]}

    # Local development — fall back to .env file.
    env_path = PROJECT_ROOT / ".env"
    config   = dotenv_values(env_path)
    if not config.get("FRED_API_KEY"):
        raise EnvironmentError(
            "FRED_API_KEY not found in .env. "
            "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    return config


def _fetch_fred_series(series_map: dict, start: str, end: str, fred: Fred) -> pd.DataFrame:
    frames = {}
    for series_id, col_name in series_map.items():
        log.info("Fetching FRED: %s (%s)", series_id, col_name)
        last_error = None
        for attempt in range(FRED_MAX_RETRIES):
            try:
                series = fred.get_series(
                    series_id, observation_start=start, observation_end=end
                )

                # Monthly series may legitimately return empty for short windows
                # (publication lag). Warn and store empty — run_daily_update will
                # merge with existing data so no history is lost.
                if series.empty or series.isna().all():
                    if series_id in MONTHLY_SERIES:
                        log.warning(
                            "FRED returned empty/NaN for monthly series %s "
                            "(publication lag likely) — skipping, existing data retained.",
                            series_id,
                        )
                        frames[col_name] = pd.Series(dtype=float)
                        last_error = None
                        break
                    raise ValueError(
                        f"FRED returned empty data for {series_id}. "
                        "Check your API key and FRED availability."
                    )

                last_error = None
                break

            except Exception as e:
                last_error = e
                if attempt < FRED_MAX_RETRIES - 1:
                    log.warning(
                        "FRED fetch failed for %s (attempt %d/%d): %s. Retrying in %ds.",
                        series_id, attempt + 1, FRED_MAX_RETRIES, e, FRED_RETRY_DELAY,
                    )
                    time.sleep(FRED_RETRY_DELAY)

        if last_error is not None:
            raise ValueError(
                f"FRED fetch failed for {series_id} after {FRED_MAX_RETRIES} attempts: {last_error}"
            )
        frames[col_name] = frames.get(col_name, series)

    df = pd.DataFrame(frames)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = df.index.normalize()
    df.index.name = "date"
    df = df.dropna(how="all")
    return df


def _derive_cross_rates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Guard against zero or NaN in USDJPY before division.
    if (df["USDJPY"] == 0).any() or df["USDJPY"].isna().any():
        bad = df["USDJPY"][(df["USDJPY"] == 0) | df["USDJPY"].isna()]
        log.warning(
            "USDJPY has %d zero/NaN value(s) at: %s — JPYINR will be NaN for these rows.",
            len(bad), list(bad.index[:5]),
        )

    df["EURINR"] = df["EURUSD"] * df["USDINR"]
    df["JPYINR"] = (df["USDINR"] / df["USDJPY"].replace(0, float("nan"))) * 100

    return df


def _build_prices_df(start: str, end: str, fred: Fred) -> pd.DataFrame:
    price_df = _fetch_fred_series(FRED_PRICE_SERIES, start, end, fred)
    df       = _derive_cross_rates(price_df)

    cols    = ["USDINR", "EURINR", "JPYINR", "EURUSD", "USDJPY", "DXY", "VIX"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"Price DataFrame missing columns after derivation: {missing}")

    return df[cols]


def _dedup_sort(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df.index.duplicated(keep="last")].copy().sort_index()


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, engine="pyarrow", compression="snappy")
    for attempt in range(3):
        try:
            tmp.replace(path)
            break
        except PermissionError:
            if attempt < 2:
                log.warning(
                    "PermissionError writing %s — OneDrive may be syncing. "
                    "Retrying in 3 seconds (attempt %d/2).",
                    path.name, attempt + 1,
                )
                time.sleep(3)
            else:
                tmp.unlink(missing_ok=True)
                raise PermissionError(
                    f"Failed to write {path.name} after 3 attempts. "
                    "Pause OneDrive sync and rerun."
                )
    log.info("Saved %s — %d rows x %d cols", path.name, len(df), len(df.columns))


def run_full_ingest() -> None:
    log.info("=== Full ingest started (from %s) ===", HISTORY_START)

    config = _load_env()
    fred   = Fred(api_key=config["FRED_API_KEY"])
    end    = pd.Timestamp.today().strftime("%Y-%m-%d")

    prices_df = _build_prices_df(HISTORY_START, end, fred)
    macro_df  = _fetch_fred_series(FRED_MACRO_SERIES, HISTORY_START, end, fred)

    _write_parquet(_dedup_sort(prices_df), PRICES_PATH)
    _write_parquet(_dedup_sort(macro_df),  FRED_PATH)

    log.info("=== Full ingest complete ===")


def run_daily_update() -> None:
    log.info("=== Daily update started ===")

    if not PRICES_PATH.exists() or not FRED_PATH.exists():
        log.warning("Raw parquet files not found — running full ingest as fallback.")
        run_full_ingest()
        return

    config = _load_env()
    fred   = Fred(api_key=config["FRED_API_KEY"])

    end          = pd.Timestamp.today().strftime("%Y-%m-%d")
    start        = (pd.Timestamp.today() - pd.Timedelta(days=UPDATE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    start_macro  = (pd.Timestamp.today() - pd.Timedelta(days=MONTHLY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    # --- prices (daily series) ---
    old_prices = pd.read_parquet(PRICES_PATH, engine="pyarrow")
    new_prices = _build_prices_df(start, end, fred)
    merged     = _dedup_sort(pd.concat([old_prices, new_prices]))
    new_rows   = len(merged) - len(old_prices)
    if new_rows > 0:
        log.info("Daily update added %d new row(s) to prices.", new_rows)
    else:
        log.info("No new price rows today — market may be closed or FRED not yet updated.")
    _write_parquet(merged, PRICES_PATH)

    # --- macro (includes monthly series — use longer lookback to avoid empty returns) ---
    old_macro    = pd.read_parquet(FRED_PATH, engine="pyarrow")
    new_macro    = _fetch_fred_series(FRED_MACRO_SERIES, start_macro, end, fred)
    merged_macro = _dedup_sort(pd.concat([old_macro, new_macro]))
    new_mac_rows = len(merged_macro) - len(old_macro)
    if new_mac_rows > 0:
        log.info("Daily update added %d new row(s) to macro.", new_mac_rows)
    else:
        log.info("No new macro rows today.")
    _write_parquet(merged_macro, FRED_PATH)

    log.info("=== Daily update complete ===")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "full":
        run_full_ingest()
    elif mode == "update":
        run_daily_update()
    else:
        log.error("Unknown mode '%s'. Use: python ingest.py full | update", mode)
        sys.exit(1)