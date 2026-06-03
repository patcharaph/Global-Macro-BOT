"""
Backfill regime_history from historical indicator data in Supabase.

Reconstructs weekly regime signals from 2005-01-01 using the same
scoring pipeline as the live weekly job, then upserts each Friday
into the regime_history table.

Usage:
    python scripts/backfill_regime_history.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

from flowmacro.data.store import read_series, upsert_regime_history
from flowmacro.regime.indicators import INDICATORS, normalize
from flowmacro.regime.scorer import compute_scores
from flowmacro.regime.classifier import classify_series

_START_WARMUP   = "2005-01-01"
_START_BACKFILL = "2010-01-01"


def build_full_history() -> pd.DataFrame:
    """Return weekly DataFrame: regime, confidence, growth_score, inflation_score."""
    normalized: dict[str, pd.Series] = {}

    for ind in INDICATORS:
        try:
            raw = read_series(ind.series_id, start=_START_WARMUP)
            if raw.empty:
                logger.warning(f"No data for {ind.name} ({ind.series_id}) — skipped")
                continue
            daily = raw.resample("D").ffill()
            normed = normalize(daily, ind, window_years=5)
            normalized[ind.name] = normed
            logger.debug(f"{ind.name}: {len(normed)} rows, last={normed.last_valid_index().date()}")
        except Exception as exc:
            logger.warning(f"{ind.name} failed: {exc}")

    if len(normalized) < 5:
        raise ValueError(f"Only {len(normalized)} indicators — need at least 5")

    normed_df = pd.DataFrame(normalized).loc[_START_BACKFILL:]
    scores_df = compute_scores(normed_df)
    classified = classify_series(scores_df)

    # Resample to weekly Friday — each row = regime for that week
    weekly = classified.resample("W-FRI").last().dropna(subset=["regime"])
    logger.info(f"Built {len(weekly)} weekly rows ({weekly.index[0].date()} → {weekly.index[-1].date()})")
    logger.info(f"Distribution: {weekly['regime'].value_counts().to_dict()}")
    return weekly


def main() -> None:
    logger.info("=== Backfill regime_history ===")

    weekly = build_full_history()

    inserted = 0
    for ts, row in weekly.iterrows():
        try:
            upsert_regime_history(
                run_date=str(ts.date()),
                regime=str(row["regime"]),
                confidence=float(row["confidence"]) if pd.notna(row["confidence"]) else 0.0,
                growth_score=float(row["growth_score"]),
                inflation_score=float(row["inflation_score"]),
            )
            inserted += 1
        except Exception as exc:
            logger.warning(f"Skip {ts.date()}: {exc}")

    logger.info(f"Done — {inserted} rows upserted to regime_history")
    logger.info("Run the SQL query now to validate:")
    logger.info(
        "SELECT regime, COUNT(*) as weeks,\n"
        "       ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(),1) as pct\n"
        "FROM regime_history\n"
        "WHERE run_date BETWEEN '2010-01-01' AND '2015-01-01'\n"
        "GROUP BY regime ORDER BY weeks DESC;"
    )


if __name__ == "__main__":
    main()
