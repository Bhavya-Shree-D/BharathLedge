"""
scripts/daily_update.py
Runs the daily data update pipeline — fetches new rows, realigns, and
recomputes features. Does NOT retrain models (that runs weekly via retrain.py).

Run order:
    ingest.py update  → appends new rows to raw parquet files
    align.py          → rebuilds aligned.parquet
    features.py       → rebuilds features.parquet
    targets.py        → rebuilds targets.parquet
"""

import logging
import sys
from pathlib import Path

# Project root is two levels up from scripts/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from features.Forecasting.ingest   import run_daily_update
from features.Forecasting.align    import run_alignment
from features.Forecasting.features import run_feature_engineering
from features.Forecasting.targets  import run_target_engineering

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger(__name__)


def main() -> None:
    log.info("=== Daily update pipeline started ===")
    try:
        run_daily_update()
        run_alignment()
        run_feature_engineering()
        run_target_engineering()
        log.info("=== Daily update pipeline complete ===")
    except Exception as e:
        log.error("Daily update pipeline failed: %s", e)
        raise


if __name__ == "__main__":
    main()