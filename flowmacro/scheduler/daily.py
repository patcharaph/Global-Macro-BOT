import sys
from datetime import date, timedelta
import pandas as pd
from loguru import logger
from flowmacro.data.sources.prices import fetch_prices
from flowmacro.data.store import upsert_series

_PRICE_TICKERS = [
    "SPY", "QQQ", "IWM", "EFA", "EEM", "FXI", "EWJ",
    "TLT", "IEF", "SHY", "HYG",
    "GLD", "USO", "DBC", "SLV",
    "UUP", "FXE", "FXY",
    "HG=F", "GC=F",
    "THB=X",
]

# Fetch 7 days to cover weekends/holidays — full history is already in Supabase
_START_SEED  = "2005-01-01"   # used only by scripts/seed.py
_START_DAILY = str(date.today() - timedelta(days=7))
_BTC_START_DAILY = str(date.today() - timedelta(days=7))


def run() -> None:
    logger.info("Daily job: start")

    # ── 1. Fetch prices ──────────────────────────────────────────────────────────
    prices = pd.DataFrame()
    stale: dict[str, int] = {}
    failed_tickers: list[str] = []

    try:
        prices, stale = fetch_prices(_PRICE_TICKERS, start=_START_DAILY)
        failed_tickers = [t for t, d in stale.items() if d == -1]
        if failed_tickers:
            logger.warning(f"yfinance failed for: {failed_tickers}")
        logger.info(f"Prices fetched: {prices.shape[1]} tickers, {prices.shape[0]} rows")
    except Exception as exc:
        logger.warning(f"fetch_prices failed ({exc}) — skipping price update, using cached Supabase data")
        try:
            from flowmacro.alerts.gmail import send_alert
            send_alert("yfinance Total Failure", f"fetch_prices raised: {exc}")
        except Exception:
            pass

    # ── 2. Alert on partial yfinance failure ─────────────────────────────────────
    if failed_tickers:
        try:
            from flowmacro.alerts.gmail import send_alert
            send_alert(
                "yfinance Fetch Failed (partial)",
                f"Failed tickers: {', '.join(failed_tickers)}\n"
                f"Continuing with remaining {len(_PRICE_TICKERS) - len(failed_tickers)} tickers.",
            )
        except Exception:
            pass

    # ── 3. Store prices + derived indicators ─────────────────────────────────────
    if not prices.empty:
        try:
            for ticker in _PRICE_TICKERS:
                if ticker in prices.columns and not prices[ticker].dropna().empty:
                    upsert_series(ticker, prices[ticker].dropna())

            hg = prices["HG=F"].dropna()
            gc = prices["GC=F"].dropna()
            if not hg.empty and not gc.empty:
                upsert_series("copper_gold", (hg / gc).dropna())

            spy = prices["SPY"].dropna()
            if len(spy) >= 200:
                upsert_series("spy_200ma", ((spy / spy.rolling(200).mean()) - 1).mul(100).dropna())

            uup = prices["UUP"].dropna()
            if len(uup) >= 20:
                upsert_series("dxy_trend", ((uup / uup.rolling(20).mean()) - 1).mul(100).dropna())

        except Exception as exc:
            logger.error(f"Daily job failed (Supabase write): {exc}")
            try:
                from flowmacro.alerts.gmail import send_alert
                send_alert("Daily Job FAILED", f"Supabase write error: {exc}")
            except Exception:
                pass
            sys.exit(1)

    # ── 4. Staleness alert (> 3 days for market-priced tickers) ──────────────────
    stale_warn = {k: v for k, v in stale.items() if v > 3 and k in _PRICE_TICKERS[:17]}
    if stale_warn:
        try:
            from flowmacro.alerts.gmail import send_alert
            lines = "\n".join(f"  {k}: {v} days" for k, v in stale_warn.items())
            send_alert("Data Staleness Warning", f"Stale series (>3 days):\n{lines}")
        except Exception:
            pass

    # ── 5. BTC price from Binance ─────────────────────────────────────────────────
    try:
        from flowmacro.data.sources.binance import fetch_btc_price
        btc = fetch_btc_price(start=_BTC_START_DAILY)
        upsert_series("BTC-USD", btc.dropna())
        logger.info(f"BTC-USD: {len(btc)} rows upserted")
    except Exception as exc:
        logger.warning(f"BTC fetch skipped: {exc}")

    logger.info("Daily job: done")


if __name__ == "__main__":
    run()
