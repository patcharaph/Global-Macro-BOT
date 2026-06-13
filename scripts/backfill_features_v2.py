"""
Step 3: Backfill features_v2 historical data (712+ weeks) to Supabase.

Fetches Group 2 (macro leading) + Group 3 (price leading) features
starting from 2007-01-01 — enough warmup for the 260W rolling window
plus 712+ valid data points.

Prerequisites:
  1. Create macro_features_v2 table in Supabase (see scripts/sql/create_features_v2.sql)
  2. FRED_API_KEY set in .env

Usage:
    python scripts/backfill_features_v2.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from loguru import logger

from flowmacro.data.features_v2 import build_features_v2
from flowmacro.data.store import upsert_features_v2

# 260W rolling warmup + 712 valid weeks ≈ 19Y total → start 2007
_BACKFILL_START = "2007-01-01"
_BATCH_SIZE     = 50


def main() -> None:
    logger.info(f"=== features_v2 backfill: {_BACKFILL_START} → today ===")

    df = build_features_v2(start=_BACKFILL_START)
    if df.empty:
        logger.error("No features built — check FRED_API_KEY and yfinance access")
        sys.exit(1)

    # Drop rows where every feature is NaN (rolling warmup period only)
    df = df.dropna(how="all")
    logger.info(f"Rows after dropping all-NaN warmup: {len(df)}")

    # NaN report per feature
    nan_report = df.isnull().mean() * 100
    logger.info("NaN % per feature:\n" + nan_report.to_string())

    bad = nan_report[nan_report > 5].index.tolist()
    if bad:
        logger.warning(f"Features with >5% NaN: {bad}")

    # Upsert in batches
    logger.info(f"Upserting {len(df)} rows to macro_features_v2 (batch={_BATCH_SIZE})...")
    errors = 0
    for i in range(0, len(df), _BATCH_SIZE):
        batch = df.iloc[i : i + _BATCH_SIZE]
        for dt, row in batch.iterrows():
            features = {col: val for col, val in row.items()}
            try:
                upsert_features_v2(str(dt.date()), features)
            except Exception as exc:
                logger.warning(f"Upsert failed for {dt.date()}: {exc}")
                errors += 1
        done = min(i + _BATCH_SIZE, len(df))
        logger.info(f"  {done}/{len(df)} rows upserted")

    # Acceptance criteria report
    full_rows    = df.dropna(how="any").shape[0]   # rows with ALL 14 features valid
    total_feats  = df.shape[1]                      # should be 14
    ratio        = full_rows / (17 + total_feats)   # 17 existing + new

    print("\n=== Acceptance Criteria ===")
    print(f"{'✅' if errors == 0 else '⚠️'} Upsert errors:      {errors}")
    print(f"{'✅' if len(df) >= 712 else '❌'} Rows stored:        {len(df)} (need ≥712)")
    print(f"{'✅' if full_rows >= 712 else '⚠️'} Full-feature rows:  {full_rows} (need ≥712 for ratio check)")
    print(f"{'✅' if ratio >= 20 else '❌'} Sample/feature ≥20: {ratio:.1f}:1  "
          f"({full_rows} rows / {17 + total_feats} features)")

    for col in df.columns:
        nan_pct = df[col].isnull().mean() * 100
        status  = "✅" if nan_pct < 5 else "⚠️"
        print(f"  {status} {col:<35} NaN={nan_pct:.1f}%")


if __name__ == "__main__":
    main()
