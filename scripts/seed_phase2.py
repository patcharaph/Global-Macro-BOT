"""
Seed Phase 2 historical data into Supabase.

  BTC-USD  : Binance spot daily close, 2017-08-17 → today
  COT      : CFTC Legacy net speculative, 2014-01-01 → today (4 markets)

Run once after Phase 2 deployment:
  python scripts/seed_phase2.py
"""
import sys
from loguru import logger
from flowmacro.data.store import upsert_series
from flowmacro.data.sources.binance import fetch_btc_price
from flowmacro.data.sources.cot import fetch_cot_net, MARKET_SERIES

_BTC_START = "2017-08-17"   # earliest reliable Binance data
_COT_START = "2014-01-01"   # 5 years before _START_COMPUTE (2019) + buffer


def seed_btc() -> None:
    logger.info(f"Seeding BTC-USD from {_BTC_START} ...")
    try:
        series = fetch_btc_price(start=_BTC_START)
        rows = upsert_series("BTC-USD", series.dropna())
        logger.success(f"BTC-USD: {rows} rows upserted")
    except Exception as exc:
        logger.error(f"BTC seed failed: {exc}")
        sys.exit(1)


def seed_cot() -> None:
    errors: list[str] = []
    for series_id in MARKET_SERIES:
        logger.info(f"Seeding {series_id} from {_COT_START} ...")
        try:
            series = fetch_cot_net(series_id, start=_COT_START)
            rows = upsert_series(series_id, series.dropna())
            logger.success(f"{series_id}: {rows} rows upserted")
        except Exception as exc:
            logger.error(f"{series_id} failed: {exc}")
            errors.append(series_id)

    if errors:
        logger.warning(f"COT seed partial — failed: {errors}")
        sys.exit(1)


if __name__ == "__main__":
    logger.info("=== Phase 2 seed start ===")
    seed_btc()
    seed_cot()
    logger.info("=== Phase 2 seed complete ===")
