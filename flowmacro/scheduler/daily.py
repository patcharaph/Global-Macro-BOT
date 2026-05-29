import sys
import pandas as pd
from loguru import logger
from flowmacro.data.sources.prices import fetch_prices
from flowmacro.data.store import upsert_series

_PRICE_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "FXI", "EWJ",
    "TLT", "IEF", "HYG",
    "GLD", "USO", "DBC", "SLV",
    "UUP", "FXE", "FXY",
    "HG=F", "GC=F",
    "THB=X",
]

_START = "2005-01-01"


def run() -> None:
    logger.info("Daily job: start")

    # ── 1. Fetch prices (non-fatal: yfinance blocked on some CI environments) ──
    prices = pd.DataFrame()
    stale: dict[str, int] = {}
    try:
        prices, stale = fetch_prices(_PRICE_TICKERS, start=_START)
        logger.info(f"Prices fetched: {prices.shape[1]} tickers, {prices.shape[0]} rows")
    except Exception as exc:
        logger.warning(f"fetch_prices failed ({exc}) — skipping price update, using cached Supabase data")

    # ── 2. Store prices + derived indicators (only if fetch succeeded) ─────────
    if not prices.empty:
        try:
            for ticker in _PRICE_TICKERS:
                if ticker in prices.columns and not prices[ticker].dropna().empty:
                    upsert_series(ticker, prices[ticker].dropna())

            hg  = prices["HG=F"].dropna()
            gc  = prices["GC=F"].dropna()
            if not hg.empty and not gc.empty:
                upsert_series("copper_gold", (hg / gc).dropna())

            spy = prices["SPY"].dropna()
            if len(spy) >= 200:
                upsert_series("spy_200ma", ((spy / spy.rolling(200).mean()) - 1).mul(100).dropna())

            uup = prices["UUP"].dropna()
            if len(uup) >= 20:
                upsert_series("dxy_trend", ((uup / uup.rolling(20).mean()) - 1).mul(100).dropna())

        except Exception as exc:
            # Supabase write failure IS fatal — data pipeline broken
            logger.error(f"Daily job failed (Supabase write): {exc}")
            try:
                from flowmacro.alerts.gmail import send_alert
                send_alert("Daily Job FAILED", f"Supabase write error: {exc}")
            except Exception:
                pass
            sys.exit(1)

    # ── 3. Staleness alert ──────────────────────────────────────────────────────
    stale_warn = {k: v for k, v in stale.items() if v > 3 and k in _PRICE_TICKERS[:17]}
    if stale_warn:
        try:
            from flowmacro.alerts.gmail import send_alert
            send_alert("Data Staleness Warning", f"Stale series (>3 days):\n{stale_warn}")
        except Exception:
            pass

    logger.info("Daily job: done")


if __name__ == "__main__":
    run()
