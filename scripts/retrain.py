"""
scripts/retrain.py
Runs the full retraining pipeline — rebuilds features, targets, and
retrains all 15 LightGBM models. Run weekly via GitHub Actions.

Run order:
    ingest.py update  → appends new rows
    align.py          → rebuilds aligned.parquet
    features.py       → rebuilds features.parquet
    targets.py        → rebuilds targets.parquet
    train.py          → retrains all 15 models
    evaluate.py       → logs OOS metrics for the retrained models
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from features.Forecasting.ingest   import run_daily_update
from features.Forecasting.align    import run_alignment
from features.Forecasting.features import run_feature_engineering
from features.Forecasting.targets  import run_target_engineering
from features.Forecasting.train    import run_training
from features.Forecasting.evaluate import run_evaluation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

log = logging.getLogger(__name__)


def main() -> None:
    log.info("=== Weekly retrain pipeline started ===")
    try:
        run_daily_update()
        run_alignment()
        run_feature_engineering()
        run_target_engineering()
        run_training()
        run_evaluation()
        log.info("=== Weekly retrain pipeline complete ===")
    except Exception as e:
        log.error("Weekly retrain pipeline failed: %s", e)
        raise


if __name__ == "__main__":
    main()